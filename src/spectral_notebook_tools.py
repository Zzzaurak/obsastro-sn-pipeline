"""Notebook helpers for interactive spectral diagnostics.

These functions keep `notebooks/02_spectral_analysis_pipeline.ipynb` compact
while reusing the project-level logic in `src.spectral_pipeline`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from src import spectral_pipeline as sp


def load_observed_spectra(project_root: Path, target_metadata: dict[str, dict[str, object]] | None = None) -> tuple[list[dict], pd.DataFrame]:
    """Load local 1-D FITS spectra without reading TNS/output metadata."""
    target_metadata = target_metadata or {}
    data_dir = project_root / "data"
    fits_paths = sorted(
        p
        for p in data_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {".fits", ".fit", ".fts"}
    )
    spectra: list[dict] = []
    skipped = []
    for path in fits_paths:
        try:
            from astropy.io import fits

            with fits.open(path, memmap=False) as hdul:
                hdu = hdul[0]
                data = hdu.data
                if data is None or np.asarray(data).ndim != 1:
                    skipped.append({"file": str(path.relative_to(project_root)), "reason": "not 1D spectrum"})
                    continue
                flux = np.asarray(data, dtype=float)
                wave = sp.wavelength_axis_from_header(hdu.header, len(flux))
                if wave is None:
                    skipped.append({"file": str(path.relative_to(project_root)), "reason": "no wavelength WCS"})
                    continue
                target = target_key(hdu.header.get("OBJECT") or path.parent.name or path.stem.split("_")[0])
                meta = dict(target_metadata.get(target, {}))
                date_obs = sp.parse_datetime(hdu.header.get("DATE-OBS", ""))
                discovery = sp.parse_datetime(meta.get("discoverydate", ""))
                phase_days = np.nan
                if pd.notna(date_obs) and pd.notna(discovery):
                    phase_days = (date_obs - discovery).total_seconds() / 86400.0
                spectra.append(
                    {
                        "path": path,
                        "file": str(path.relative_to(project_root)),
                        "target": target,
                        "wave": np.asarray(wave, dtype=float),
                        "flux": flux,
                        "date_obs": date_obs,
                        "phase_days": phase_days,
                        "z": sp.parse_float(meta.get("z")),
                        "z_source": "manual_config" if np.isfinite(sp.parse_float(meta.get("z"))) else "unset",
                        "type": meta.get("type", ""),
                        "discoverydate": meta.get("discoverydate", ""),
                        "host": meta.get("host", ""),
                        "exptime": sp.parse_float(hdu.header.get("EXPTIME", hdu.header.get("EXPOSURE"))),
                        "telescope": hdu.header.get("TELESCOP", ""),
                        "instrument": hdu.header.get("INSTRUME", ""),
                        "setup": hdu.header.get("FILTER", hdu.header.get("GRISM", "")),
                        "bunit": hdu.header.get("BUNIT", ""),
                    }
                )
        except Exception as exc:
            skipped.append({"file": str(path.relative_to(project_root)), "reason": repr(exc)})
    return spectra, pd.DataFrame(skipped)


def target_key(value: object) -> str:
    return sp.normalize_target_name(value)


def line_keys_for(spec: dict, target_lines: dict[str, list[str]] | None = None) -> list[str]:
    target_lines = target_lines or {}
    return target_lines.get(spec["target"], sp.default_lines_for_type(spec.get("type", "")))


def rest_frame_wave(spec: dict) -> np.ndarray:
    z = spec.get("z", np.nan)
    return spec["wave"] / (1.0 + z) if np.isfinite(z) else spec["wave"].copy()


def observed_to_rest(wave_obs: np.ndarray | float, z: float) -> np.ndarray | float:
    if not np.isfinite(z):
        return wave_obs
    return np.asarray(wave_obs) / (1.0 + z)


def rest_to_observed(wave_rest: np.ndarray | float, z: float) -> np.ndarray | float:
    if not np.isfinite(z):
        return wave_rest
    return np.asarray(wave_rest) * (1.0 + z)


def line_rest_wave(line_name: str, rest_wave: float | None = None) -> float:
    """Return the rest wavelength for a host/SN line name or an explicit value."""
    explicit = sp.parse_float(rest_wave)
    if np.isfinite(explicit):
        return float(explicit)
    if line_name in sp.HOST_LINES:
        return float(sp.HOST_LINES[line_name])
    if line_name in sp.LINE_LIBRARY:
        return float(sp.LINE_LIBRARY[line_name]["rest"])
    known = sorted(set(sp.HOST_LINES) | set(sp.LINE_LIBRARY))
    raise KeyError(f"Unknown line {line_name!r}. Known line keys: {', '.join(known)}")


def target_redshift(spectra: Iterable[dict], target: str) -> float:
    z_values = [float(spec.get("z")) for spec in spectra if spec["target"] == target and np.isfinite(spec.get("z", np.nan))]
    return float(np.nanmedian(z_values)) if z_values else np.nan


def apply_redshift_overrides(spectra: list[dict], redshift_by_target: dict[str, float]) -> list[dict]:
    updated = []
    for spec in spectra:
        copy = dict(spec)
        z = redshift_by_target.get(copy["target"])
        if z is not None and np.isfinite(z):
            copy["z"] = float(z)
            copy["z_source"] = "manual"
        updated.append(copy)
    return updated


def line_params_for(
    spec: dict,
    line_key: str,
    *,
    line_half_width: float,
    line_smooth_window: int,
    line_edge_fraction: float,
    line_param_overrides: dict | None = None,
) -> dict[str, float]:
    params = {
        "half_width": line_half_width,
        "smooth_window": line_smooth_window,
        "edge_fraction": line_edge_fraction,
    }
    filename = Path(spec["file"]).name
    for key in [line_key, (spec["target"], line_key), (spec["target"], filename, line_key)]:
        params.update((line_param_overrides or {}).get(key, {}))
    return params


def fit_visual_absorption_profile(
    wave: np.ndarray,
    norm: np.ndarray,
    rest: float,
    result: dict,
    half_width: float,
    *,
    enabled: bool = True,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    if not enabled or result.get("status") != "ok":
        return None, None

    def model(x, center, sigma, depth, baseline, slope):
        return baseline + slope * (x - rest) - depth * np.exp(-0.5 * ((x - center) / sigma) ** 2)

    center0 = float(result["abs_wave"])
    depth0 = float(max(result.get("depth", 0.1), 0.05))
    fwhm0 = result.get("FWHM_A", np.nan)
    sigma0 = float(fwhm0 / 2.355) if np.isfinite(fwhm0) and fwhm0 > 0 else min(90.0, half_width / 3.0)
    sigma0 = max(8.0, min(float(sigma0), half_width))
    try:
        params, _ = curve_fit(
            model,
            wave,
            norm,
            p0=(center0, sigma0, depth0, 1.0, 0.0),
            bounds=(
                [rest - half_width, 5.0, 0.0, 0.2, -0.01],
                [rest + half_width, half_width, 1.5, 2.0, 0.01],
            ),
            maxfev=20000,
        )
        return model(wave, *params), params
    except Exception:
        return None, None


def measure_absorption_line_tuned(
    spec: dict,
    line_key: str,
    *,
    line_half_width: float = 420.0,
    line_smooth_window: int = 21,
    line_edge_fraction: float = 0.18,
    line_param_overrides: dict | None = None,
    fit_visual_gaussian: bool = True,
) -> tuple[dict, dict]:
    params = line_params_for(
        spec,
        line_key,
        line_half_width=line_half_width,
        line_smooth_window=line_smooth_window,
        line_edge_fraction=line_edge_fraction,
        line_param_overrides=line_param_overrides,
    )
    half_width = float(params["half_width"])
    smooth_window = int(params["smooth_window"])
    edge_fraction = float(params["edge_fraction"])

    line = sp.LINE_LIBRARY[line_key]
    rest = line["rest"]
    wave_rest = rest_frame_wave(spec)
    mask = (wave_rest > rest - half_width) & (wave_rest < rest + half_width)
    if mask.sum() < 12:
        return {"line": line_key, "status": "outside wavelength range"}, {}

    wave = np.asarray(wave_rest[mask], dtype=float)
    raw_flux = np.asarray(spec["flux"][mask], dtype=float)
    smooth = sp.smooth_flux(raw_flux, preferred_window=smooth_window)
    continuum = sp.local_linear_continuum(wave, smooth, edge_fraction=edge_fraction)
    valid = np.isfinite(wave) & np.isfinite(raw_flux) & np.isfinite(smooth) & np.isfinite(continuum) & (np.abs(continuum) > 0)
    if valid.sum() < 12:
        return {"line": line_key, "status": "bad local continuum"}, {}

    wave = wave[valid]
    raw_flux = raw_flux[valid]
    smooth = smooth[valid]
    continuum = continuum[valid]
    norm = smooth / continuum

    search = wave < rest if line.get("blue_only", True) else np.isfinite(wave)
    if search.sum() < 5:
        search = np.isfinite(wave)
    candidates = np.where(search)[0]
    min_i = candidates[np.nanargmin(norm[candidates])]
    abs_wave = float(wave[min_i])
    depth = max(0.0, 1.0 - float(norm[min_i]))
    velocity = sp.C_KMS * (rest - abs_wave) / rest
    absorption = np.clip(1.0 - norm, 0.0, None)
    pew = float(np.trapz(absorption, wave))
    fwhm = np.nan
    if depth > 0:
        half_level = 1.0 - depth / 2.0
        below = wave[norm <= half_level]
        if len(below) >= 2:
            fwhm = float(below.max() - below.min())

    result = {
        "line": line_key,
        "line_label": line["label"],
        "rest_wave": rest,
        "abs_wave": abs_wave,
        "velocity_kms": float(velocity),
        "pEW_A": pew,
        "FWHM_A": fwhm,
        "depth": depth,
        "status": "ok",
    }
    fit_norm, fit_params = fit_visual_absorption_profile(wave, norm, rest, result, half_width, enabled=fit_visual_gaussian)
    profile = {
        "wave": wave,
        "raw_flux": raw_flux,
        "smooth": smooth,
        "continuum": continuum,
        "norm": norm,
        "absorption": absorption,
        "fit_norm": fit_norm,
        "fit_params": fit_params,
        "params": params,
    }
    return result, profile


def normalize_window_observed(
    spec: dict,
    rest_wave: float,
    *,
    z_guess: float,
    half_width: float = 120.0,
    smooth_window: int = 21,
    edge_fraction: float = 0.18,
) -> dict:
    center_obs = rest_to_observed(rest_wave, z_guess)
    wave_obs = np.asarray(spec["wave"], dtype=float)
    mask = (wave_obs > center_obs - half_width) & (wave_obs < center_obs + half_width)
    if mask.sum() < 12:
        return {"status": "outside wavelength range"}
    wave = wave_obs[mask]
    raw_flux = np.asarray(spec["flux"][mask], dtype=float)
    smooth = sp.smooth_flux(raw_flux, preferred_window=smooth_window)
    continuum = sp.local_linear_continuum(wave, smooth, edge_fraction=edge_fraction)
    valid = np.isfinite(wave) & np.isfinite(raw_flux) & np.isfinite(smooth) & np.isfinite(continuum) & (np.abs(continuum) > 0)
    if valid.sum() < 12:
        return {"status": "bad local continuum"}
    return {
        "status": "ok",
        "wave_obs": wave[valid],
        "wave_rest_guess": observed_to_rest(wave[valid], z_guess),
        "raw_flux": raw_flux[valid],
        "smooth": smooth[valid],
        "continuum": continuum[valid],
        "norm": smooth[valid] / continuum[valid],
        "center_obs": center_obs,
    }


def auto_pick_line_wavelength(window: dict, *, mode: str = "emission") -> float:
    if window.get("status") != "ok":
        return np.nan
    norm = np.asarray(window["norm"], dtype=float)
    wave = np.asarray(window["wave_obs"], dtype=float)
    if mode == "absorption":
        return float(wave[np.nanargmin(norm)])
    return float(wave[np.nanargmax(norm)])


def redshift_from_observed(rest_wave: float, observed_wave: float) -> float:
    return float(observed_wave) / float(rest_wave) - 1.0


def redshift_guess_for_line(
    spectra: Iterable[dict],
    target: str,
    line_name: str,
    rest_wave: float,
    *,
    manual_observed_wave: float | None = None,
    measurements: list[dict] | None = None,
    default: float = 0.0,
) -> float:
    """Infer a plotting redshift guess from the local notebook context."""
    manual = sp.parse_float(manual_observed_wave)
    if np.isfinite(manual):
        return redshift_from_observed(rest_wave, manual)

    target_norm = target_key(target)
    candidates = []
    for item in measurements or []:
        if target_key(item.get("target")) != target_norm:
            continue
        if item.get("line") and str(item.get("line")) != line_name:
            continue
        try:
            item_rest = line_rest_wave(str(item.get("line") or line_name), item.get("rest_wave"))
        except KeyError:
            continue
        observed = sp.parse_float(item.get("observed_wave"))
        if np.isfinite(item_rest) and np.isfinite(observed):
            candidates.append(redshift_from_observed(item_rest, observed))
    if candidates:
        return float(np.nanmedian(candidates))

    existing = target_redshift(spectra, target_norm)
    if np.isfinite(existing):
        return float(existing)
    return float(default)


def redshift_table_from_measurements(measurements: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    rows = []
    for item in measurements:
        target = target_key(item.get("target"))
        try:
            rest_wave = line_rest_wave(str(item.get("line", "")), item.get("rest_wave"))
        except KeyError:
            rest_wave = np.nan
        observed_wave = sp.parse_float(item.get("observed_wave"))
        if not target or not np.isfinite(rest_wave) or not np.isfinite(observed_wave):
            continue
        rows.append(
            {
                "target": target,
                "file": item.get("file", ""),
                "line": item.get("line", ""),
                "kind": item.get("kind", "host/emission"),
                "rest_wave": rest_wave,
                "observed_wave": observed_wave,
                "z": redshift_from_observed(rest_wave, observed_wave),
                "note": item.get("note", ""),
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        return table, pd.DataFrame(), {}
    summary_rows = []
    overrides = {}
    for target, group in table.groupby("target"):
        z_values = pd.to_numeric(group["z"], errors="coerce").dropna()
        if z_values.empty:
            continue
        z_med = float(np.nanmedian(z_values))
        scatter = float(np.nanstd(z_values, ddof=1)) if len(z_values) > 1 else np.nan
        summary_rows.append({"target": target, "z_manual": z_med, "z_scatter": scatter, "n_lines": len(z_values)})
        overrides[target] = z_med
    return table, pd.DataFrame(summary_rows), overrides


def add_rest_top_axis(ax, z: float):
    if not np.isfinite(z):
        return None

    def obs_to_rest_axis(x):
        return np.asarray(x) / (1.0 + z)

    def rest_to_obs_axis(x):
        return np.asarray(x) * (1.0 + z)

    top = ax.secondary_xaxis("top", functions=(obs_to_rest_axis, rest_to_obs_axis))
    top.set_xlabel("Rest wavelength after redshift correction (Angstrom)")
    return top


def save_figure(fig, fig_dir: Path, filename: str, *, enabled: bool = True) -> Path | None:
    if not enabled:
        return None
    fig_dir.mkdir(parents=True, exist_ok=True)
    path = fig_dir / filename
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    print(f"saved {path}")
    return path


def plot_redshift_zoom(
    spec: dict,
    line_name: str,
    *,
    rest_wave: float,
    z_guess: float,
    half_width: float,
    manual_observed_wave: float | None = None,
    mode: str = "emission",
):
    window = normalize_window_observed(spec, rest_wave, z_guess=z_guess, half_width=half_width)
    if window.get("status") != "ok":
        print(window.get("status"))
        return window, np.nan
    auto_wave = auto_pick_line_wavelength(window, mode=mode)
    adopted_wave = float(manual_observed_wave) if manual_observed_wave is not None and np.isfinite(manual_observed_wave) else auto_wave
    z_adopted = redshift_from_observed(rest_wave, adopted_wave)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(window["wave_obs"], window["raw_flux"] / window["continuum"], color="0.7", lw=0.8, label="raw / local continuum")
    ax.plot(window["wave_obs"], window["norm"], color="black", lw=1.1, label="smoothed / local continuum")
    ax.axvline(window["center_obs"], color="red", ls="--", lw=1.0, label=f"{line_name} at z_guess")
    ax.axvline(auto_wave, color="#1b9e77", ls=":", lw=1.5, label=f"auto {mode} pick")
    ax.axvline(adopted_wave, color="#7b3294", ls="-.", lw=1.5, label=f"manual/adopted z={z_adopted:.5f}")
    ax.set_xlabel("Observed wavelength (Angstrom)")
    ax.set_ylabel("Local continuum-normalized flux")
    ax.set_title(f"{spec['target']} {Path(spec['file']).name}: redshift check with {line_name}")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    add_rest_top_axis(ax, z_adopted)
    return {"window": window, "auto_wave": auto_wave, "adopted_wave": adopted_wave, "z": z_adopted, "figure": fig}, z_adopted


def plot_spectral_sequence_dual_axis(
    target: str,
    spectra: list[dict],
    *,
    target_lines: dict[str, list[str]] | None,
    fig_dir: Path,
    save_figures: bool = True,
):
    items = sorted(
        [spec for spec in spectra if spec["target"] == target],
        key=lambda spec: pd.Timestamp.max if pd.isna(spec["date_obs"]) else spec["date_obs"],
    )
    if not items:
        print(f"No target {target}")
        return None
    z = target_redshift(spectra, target)
    line_keys = sorted({line for spec in items for line in line_keys_for(spec, target_lines) if line in sp.LINE_LIBRARY})
    fig, ax = plt.subplots(figsize=(11, max(3.5, 1.6 + 1.0 * len(items))))
    for i, spec in enumerate(items):
        flux = sp.smooth_flux(spec["flux"], preferred_window=11)
        finite = np.isfinite(flux)
        scale = np.nanmedian(np.abs(flux[finite])) if finite.any() else 1.0
        if not np.isfinite(scale) or scale == 0:
            scale = 1.0
        phase = spec["phase_days"]
        phase_label = "" if not np.isfinite(phase) else f", +{phase:.1f} d"
        date_label = "" if pd.isna(spec["date_obs"]) else spec["date_obs"].strftime("%Y-%m-%d")
        ax.plot(spec["wave"], flux / scale + i * 1.35, lw=0.8, label=f"{date_label}{phase_label}")
    for line_key in line_keys:
        rest = sp.LINE_LIBRARY[line_key]["rest"]
        observed = rest_to_observed(rest, z)
        ax.axvline(observed, color="0.55", ls="--", lw=0.8, alpha=0.6)
        ax.text(observed, 0.98, line_key, rotation=90, va="top", ha="right", transform=ax.get_xaxis_transform(), fontsize=8, color="0.35")
    ax.set_title(f"{target}: observed spectra with rest-wavelength top axis")
    ax.set_xlabel("Observed wavelength (Angstrom)")
    ax.set_ylabel("Scaled flux + offset")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8)
    add_rest_top_axis(ax, z)
    save_figure(fig, fig_dir, f"spectral_sequence_{target}.png", enabled=save_figures)
    return fig


def measure_all_features(
    spectra: list[dict],
    *,
    target_lines: dict[str, list[str]] | None,
    line_half_width: float,
    line_smooth_window: int,
    line_edge_fraction: float,
    line_param_overrides: dict | None,
    bb_wave_range: tuple[float, float],
    fit_visual_gaussian: bool,
):
    line_rows = []
    bb_rows = []
    for spec in spectra:
        wave_rest = rest_frame_wave(spec)
        base = {
            "target": spec["target"],
            "file": spec["file"],
            "date_obs": spec["date_obs"],
            "phase_days": spec["phase_days"],
            "type": spec["type"],
            "z": spec["z"],
        }
        bb_rows.append({**base, **sp.fit_blackbody_temperature(wave_rest, spec["flux"], bb_wave_range)})
        for line_key in line_keys_for(spec, target_lines):
            if line_key not in sp.LINE_LIBRARY:
                print(f"Skip unknown line {line_key}")
                continue
            result, _ = measure_absorption_line_tuned(
                spec,
                line_key,
                line_half_width=line_half_width,
                line_smooth_window=line_smooth_window,
                line_edge_fraction=line_edge_fraction,
                line_param_overrides=line_param_overrides,
                fit_visual_gaussian=fit_visual_gaussian,
            )
            line_rows.append({**base, **result})
    line_df = pd.DataFrame(line_rows)
    if not line_df.empty:
        line_df = line_df.sort_values(["target", "line", "date_obs", "file"]).reset_index(drop=True)
    bb_df = pd.DataFrame(bb_rows)
    if not bb_df.empty:
        bb_df = bb_df.sort_values(["target", "date_obs", "file"]).reset_index(drop=True)
    line_qc = sp.quality_flag_lines(line_df)
    host_lines, host_summary = sp.measure_host_lines(spectra)
    summary = sp.build_summary(spectra)
    target_status = sp.build_target_status(summary, line_qc, host_summary)
    return summary, line_df, line_qc, bb_df, host_lines, host_summary, target_status


def plot_quantity_by_target(table: pd.DataFrame, value_col: str, ylabel: str, title: str, filename: str, fig_dir: Path, *, save_figures: bool = True):
    selected = table[table["qc_flag"].isin(["adopt", "check"])].copy()
    if selected.empty:
        print(f"{value_col}: no adopt/check data")
        return None
    selected[value_col] = pd.to_numeric(selected[value_col], errors="coerce")
    selected = selected[selected[value_col].notna()]
    if selected.empty:
        print(f"{value_col}: no finite values")
        return None
    targets = sorted(selected["target"].unique())
    fig, axes = plt.subplots(len(targets), 1, figsize=(10, max(3.2, 2.5 * len(targets))), sharex=False)
    axes = np.atleast_1d(axes)
    for ax, target in zip(axes, targets):
        sub = selected[selected["target"] == target]
        for line_key, group in sub.groupby("line"):
            group = group.sort_values("phase_days")
            x = group["phase_days"] if group["phase_days"].notna().any() else pd.to_datetime(group["date_obs"])
            marker = "o" if group["qc_flag"].eq("adopt").any() else "s"
            alpha = 1.0 if group["qc_flag"].eq("adopt").any() else 0.5
            ax.plot(x, group[value_col], marker=marker, lw=1.2, alpha=alpha, label=line_key)
        ax.set_title(target)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, ncol=3)
    axes[-1].set_xlabel("Days since discovery / obs date")
    fig.suptitle(title, y=1.02)
    save_figure(fig, fig_dir, filename, enabled=save_figures)
    return fig


def plot_line_diagnostics_grid(
    spectra: list[dict],
    line_qc: pd.DataFrame,
    *,
    target: str | None,
    max_panels: int,
    fig_dir: Path,
    save_figures: bool,
    **measure_kwargs,
):
    rows = line_qc[line_qc["status"].eq("ok")].copy()
    if target:
        rows = rows[rows["target"].eq(target_key(target))]
    if rows.empty:
        print("No line diagnostics to plot.")
        return None
    rows = rows.head(max_panels)
    n = len(rows)
    ncols = 2
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 3.7 * nrows), squeeze=False)
    spec_by_file = {spec["file"]: spec for spec in spectra}
    for ax, (_, row) in zip(axes.ravel(), rows.iterrows()):
        spec = spec_by_file.get(row["file"])
        if spec is None:
            ax.axis("off")
            continue
        result, profile = measure_absorption_line_tuned(spec, row["line"], **measure_kwargs)
        if result.get("status") != "ok":
            ax.set_title(f"{row['target']} {row['line']}: {result.get('status')}")
            ax.axis("off")
            continue
        wave = profile["wave"]
        cont = profile["continuum"]
        ax.plot(wave, profile["raw_flux"] / cont, color="0.72", lw=0.7, label="raw/cont")
        ax.plot(wave, profile["norm"], color="black", lw=1.0, label="smooth/cont")
        if profile["fit_norm"] is not None:
            ax.plot(wave, profile["fit_norm"], color="#7b3294", lw=1.0, label="Gaussian visual fit")
        ax.axvline(result["rest_wave"], color="red", ls="--", lw=0.9, label="rest line")
        ax.axvline(result["abs_wave"], color="green", ls=":", lw=1.2, label="absorption minimum")
        ax.fill_between(wave, profile["norm"], 1.0, where=profile["norm"] < 1.0, color="#7b3294", alpha=0.15)
        title = f"{row['target']} {Path(row['file']).name} {row['line']}"
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("Rest wavelength (Angstrom)")
        ax.set_ylabel("Normalized flux")
        ax.grid(alpha=0.2)
        ax.text(
            0.02,
            0.05,
            f"v={result['velocity_kms']:.0f} km/s\npEW={result['pEW_A']:.1f} A, FWHM={result['FWHM_A']:.1f} A",
            transform=ax.transAxes,
            fontsize=8,
            bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "0.85"},
        )
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    axes.ravel()[0].legend(fontsize=7)
    save_figure(fig, fig_dir, "line_diagnostics_grid.png", enabled=save_figures)
    return fig


def plot_line_check(
    spectra: list[dict],
    *,
    target: str,
    line_key: str | None,
    spectrum_index: int,
    fig_dir: Path,
    save_figures: bool,
    **measure_kwargs,
):
    target = target_key(target)
    items = sorted(
        [spec for spec in spectra if spec["target"] == target],
        key=lambda spec: pd.Timestamp.max if pd.isna(spec["date_obs"]) else spec["date_obs"],
    )
    if not items:
        raise ValueError(f"No target {target}")
    spec = items[int(spectrum_index)]
    line_key = line_key or line_keys_for(spec)[0]
    result, profile = measure_absorption_line_tuned(spec, line_key, **measure_kwargs)
    result_table = pd.DataFrame(
        [
            {
                "target": spec["target"],
                "file": spec["file"],
                "date_obs": spec["date_obs"],
                "phase_days": spec["phase_days"],
                "type": spec["type"],
                "z": spec["z"],
                **result,
            }
        ]
    )
    if result.get("status") != "ok" or not profile:
        print(result.get("status"))
        return result_table, None

    wave = profile["wave"]
    raw_flux = profile["raw_flux"]
    smooth = profile["smooth"]
    continuum = profile["continuum"]
    norm = profile["norm"]
    fit_norm = profile["fit_norm"]
    rest = result["rest_wave"]
    abs_wave = result["abs_wave"]

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    axes[0].plot(wave, raw_flux, color="0.72", lw=0.7, label="raw local spectrum")
    axes[0].plot(wave, smooth, color="black", lw=1.0, label="smoothed observed profile")
    axes[0].plot(wave, continuum, color="#d99032", lw=1.2, label="local linear continuum")
    if fit_norm is not None:
        axes[0].plot(wave, fit_norm * continuum, color="#7b3294", lw=1.2, label="visual Gaussian absorption fit")
    axes[0].fill_between(wave, smooth, continuum, where=continuum > smooth, color="#7b3294", alpha=0.12)
    axes[0].axvline(rest, color="red", ls="--", lw=1.0, label="rest wavelength")
    axes[0].axvline(abs_wave, color="green", ls=":", lw=1.3, label="absorption minimum")
    axes[0].set_ylabel(spec.get("bunit", "Flux"))
    axes[0].set_title(f"{spec['target']} {Path(spec['file']).name} {line_key}")
    axes[0].grid(alpha=0.2)
    axes[0].legend(fontsize=8)

    raw_norm = raw_flux / continuum
    axes[1].plot(wave, raw_norm, color="0.72", lw=0.7, label="raw / continuum")
    axes[1].plot(wave, norm, color="black", lw=1.0, label="smoothed / continuum")
    if fit_norm is not None:
        axes[1].plot(wave, fit_norm, color="#7b3294", lw=1.2, label="visual fit / continuum")
    axes[1].fill_between(wave, norm, 1.0, where=norm < 1.0, color="#7b3294", alpha=0.18, label="pEW area")
    axes[1].axhline(1.0, color="#d99032", lw=1.0)
    axes[1].axvline(rest, color="red", ls="--", lw=1.0)
    axes[1].axvline(abs_wave, color="green", ls=":", lw=1.3)
    axes[1].set_xlabel("Rest wavelength (Angstrom)")
    axes[1].set_ylabel("Normalized flux")
    axes[1].grid(alpha=0.2)
    axes[1].legend(fontsize=8)

    text = (
        f"v={result['velocity_kms']:.0f} km/s, "
        f"pEW={result['pEW_A']:.1f} A, "
        f"FWHM={result['FWHM_A']:.1f} A, "
        f"depth={result['depth']:.2f}"
    )
    axes[1].text(
        0.02,
        0.05,
        text,
        transform=axes[1].transAxes,
        fontsize=10,
        bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "0.8"},
    )
    save_figure(fig, fig_dir, f"line_check_{spec['target']}_{Path(spec['file']).stem}_{line_key}.png", enabled=save_figures)
    return result_table, fig


def blackbody_profile(wave_rest: np.ndarray, flux: np.ndarray, wave_range: tuple[float, float]):
    mask = np.isfinite(wave_rest) & np.isfinite(flux) & (wave_rest >= wave_range[0]) & (wave_rest <= wave_range[1])
    if mask.sum() < 30:
        return {"status": "insufficient wavelength range"}
    wave = np.asarray(wave_rest[mask], dtype=float)
    local_flux = sp.smooth_flux(np.asarray(flux[mask], dtype=float), preferred_window=51)
    if np.nanmedian(local_flux) < 0:
        local_flux = -local_flux
    finite = np.isfinite(local_flux)
    wave = wave[finite]
    local_flux = local_flux[finite]
    local_flux = local_flux - np.nanpercentile(local_flux, 2)
    scale = np.nanmax(np.abs(local_flux))
    if not np.isfinite(scale) or scale <= 0:
        return {"status": "bad flux scale"}
    y = local_flux / scale
    try:
        params, cov = curve_fit(
            sp.planck_lambda_angstrom,
            wave,
            y,
            p0=(7000.0, 1e-13),
            bounds=([2500.0, 0.0], [25000.0, np.inf]),
            maxfev=10000,
        )
        return {
            "status": "ok",
            "wave": wave,
            "flux_norm": y,
            "model": sp.planck_lambda_angstrom(wave, *params),
            "T_bb_K": float(params[0]),
            "T_err_K": float(np.sqrt(cov[0, 0])) if np.isfinite(cov[0, 0]) else np.nan,
        }
    except Exception as exc:
        return {"status": f"fit failed: {exc}"}


def plot_blackbody_fit_grid(spectra: list[dict], *, target: str | None, wave_range: tuple[float, float], fig_dir: Path, save_figures: bool):
    items = [spec for spec in spectra if target is None or spec["target"] == target_key(target)]
    if not items:
        print("No spectra to plot.")
        return None
    ncols = 2
    nrows = int(np.ceil(len(items) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 3.5 * nrows), squeeze=False)
    for ax, spec in zip(axes.ravel(), items):
        prof = blackbody_profile(rest_frame_wave(spec), spec["flux"], wave_range)
        if prof.get("status") != "ok":
            ax.set_title(f"{spec['target']} {Path(spec['file']).name}: {prof.get('status')}")
            ax.axis("off")
            continue
        ax.plot(prof["wave"], prof["flux_norm"], color="black", lw=0.9, label="continuum proxy")
        ax.plot(prof["wave"], prof["model"], color="#d95f02", lw=1.2, label="blackbody fit")
        ax.set_title(f"{spec['target']} {Path(spec['file']).name}: T={prof['T_bb_K']:.0f} K", fontsize=9)
        ax.set_xlabel("Rest wavelength (Angstrom)")
        ax.set_ylabel("Scaled flux")
        ax.grid(alpha=0.2)
    for ax in axes.ravel()[len(items):]:
        ax.axis("off")
    axes.ravel()[0].legend(fontsize=8)
    save_figure(fig, fig_dir, "blackbody_fit_grid.png", enabled=save_figures)
    return fig


def plot_host_line_grid(host_lines: pd.DataFrame, *, target: str | None, fig_dir: Path, save_figures: bool):
    rows = host_lines[host_lines["status"].eq("detected")].copy()
    if target:
        rows = rows[rows["target"].eq(target_key(target))]
    if rows.empty:
        print("No detected host-line indices.")
        return None
    rows["label"] = rows["target"].astype(str) + " " + rows["line"].astype(str)
    fig, ax = plt.subplots(figsize=(10, max(4.5, 0.35 * len(rows))))
    ax.barh(rows["label"], pd.to_numeric(rows["snr"], errors="coerce"), color="#5b7c99")
    ax.set_xlabel("Line-index S/N")
    ax.set_title("Host/environment narrow-line indices")
    ax.grid(axis="x", alpha=0.25)
    save_figure(fig, fig_dir, "host_line_detections.png", enabled=save_figures)
    return fig
