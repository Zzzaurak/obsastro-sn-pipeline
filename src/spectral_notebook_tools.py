"""Notebook helpers for interactive spectral diagnostics.

These functions keep `notebooks/02_spectral_analysis_pipeline.ipynb` compact
while reusing the project-level logic in `src.spectral_pipeline`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from src import spectral_pipeline as sp


RAW_SEQUENCE_REFERENCE_LINES = [
    "CaIIHK",
    "Hgamma",
    "Hbeta",
    "FeII5169",
    "SII5640",
    "HeI5876",
    "SiII6355",
    "Halpha",
    "OI7774",
    "CaIINIR",
]


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


def _slug_part(value: object) -> str:
    text = str(value or "").strip().replace(" ", "")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("_")


def analysis_output_tag(targets: Iterable[object] | pd.Series | pd.DataFrame, output_tag: str | None = None) -> str:
    """Build a stable filename tag for a notebook analysis run."""
    explicit = _slug_part(output_tag)
    if explicit:
        return explicit
    if isinstance(targets, pd.DataFrame):
        values = targets["target"].tolist() if "target" in targets.columns else []
    else:
        values = list(targets)
    keys = sorted({target_key(value) for value in values if str(value or "").strip()})
    if len(keys) == 1:
        return keys[0]
    if len(keys) == 0:
        return "no_target"
    if len(keys) <= 3:
        return "_".join(keys)
    return f"{len(keys)}targets"


def tagged_filename(filename: str, tag: str | None = None) -> str:
    """Prefix a file with the analysis tag unless it is already tagged."""
    clean_tag = _slug_part(tag)
    if not clean_tag:
        return filename
    path = Path(filename)
    if path.name.startswith(f"{clean_tag}_"):
        return path.name
    return f"{clean_tag}_{path.name}"


def analysis_output_path(analysis_dir: Path, filename: str, *, tag: str | None = None, product_prefix: str = "") -> Path:
    prefix = _slug_part(product_prefix)
    full_tag = "_".join(part for part in [prefix, _slug_part(tag)] if part)
    return Path(analysis_dir) / tagged_filename(filename, full_tag)


def find_analysis_products(analysis_dir: Path, filename: str, *, tag: str | None = None) -> list[Path]:
    """Find tagged analysis products, newest first, with legacy untagged fallback."""
    analysis_dir = Path(analysis_dir)
    clean_tag = _slug_part(tag)
    candidates: list[Path] = []
    if clean_tag:
        tagged = analysis_dir / tagged_filename(filename, clean_tag)
        if tagged.exists():
            candidates.append(tagged)
    candidates.extend(sorted(analysis_dir.glob(f"*_{filename}"), key=lambda p: p.stat().st_mtime, reverse=True))
    legacy = analysis_dir / filename
    if legacy.exists():
        candidates.append(legacy)
    seen = set()
    unique = []
    for path in candidates:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def read_analysis_product(analysis_dir: Path, filename: str, *, tag: str | None = None, target: str | None = None) -> pd.DataFrame:
    for path in find_analysis_products(analysis_dir, filename, tag=tag):
        table = pd.read_csv(path)
        if target and "target" in table.columns:
            table = table[table["target"].eq(target_key(target))].reset_index(drop=True)
        if not table.empty:
            table["product_file"] = str(path)
            return table
    return pd.DataFrame()


def read_combined_analysis_products(analysis_dir: Path, filename: str, *, tag: str | None = None) -> pd.DataFrame:
    """Read tagged/legacy products, keeping the newest available rows per target."""
    frames = []
    seen_targets: set[str] = set()
    for path in find_analysis_products(analysis_dir, filename, tag=tag):
        table = pd.read_csv(path)
        table["product_file"] = path.name
        if "target" not in table.columns:
            return table
        table["target"] = table["target"].map(target_key)
        new = table[~table["target"].isin(seen_targets)].copy()
        if new.empty:
            continue
        frames.append(new)
        seen_targets.update(str(value) for value in new["target"].dropna().unique())
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def tns_redshift_reference(project_root: Path, target: str) -> dict[str, object]:
    """Return a TNS public-catalog redshift reference without using it in local measurements."""
    catalog_path = project_root / "data" / "tns_public_objects.csv"
    key = target_key(target)
    if not catalog_path.exists():
        return {"target": key, "z_tns": np.nan, "type_tns": "", "source": str(catalog_path), "status": "catalog missing"}
    metadata = sp.load_tns_metadata(catalog_path)
    row = metadata.get(key, {})
    z_tns = sp.parse_float(row.get("z"))
    status = "ok" if np.isfinite(z_tns) else "target missing or redshift unavailable"
    return {
        "target": key,
        "z_tns": z_tns,
        "type_tns": row.get("type", ""),
        "source": str(catalog_path),
        "status": status,
    }


def _first_finite(table: pd.DataFrame, columns: Iterable[str]) -> tuple[float, str]:
    for column in columns:
        if column not in table.columns:
            continue
        values = pd.to_numeric(table[column], errors="coerce").dropna()
        if not values.empty:
            return float(values.iloc[0]), column
    return np.nan, ""


def _first_text(table: pd.DataFrame, columns: Iterable[str]) -> tuple[str, str]:
    for column in columns:
        if column not in table.columns:
            continue
        values = [str(value).strip() for value in table[column].dropna() if str(value).strip()]
        if values:
            return values[0], column
    return "", ""


def _estimate_log_lsun(z: float, apparent_mag: float, sn_family: str) -> tuple[float, str]:
    if np.isfinite(apparent_mag) and np.isfinite(z) and z > 0:
        try:
            from astropy import units as u
            from astropy.cosmology import Planck18 as cosmo

            d_l_pc = cosmo.luminosity_distance(z).to(u.pc).value
            dist_modulus = 5.0 * np.log10(d_l_pc / 10.0)
            abs_mag = apparent_mag - dist_modulus
            return float(0.4 * (4.74 - abs_mag)), "manual apparent_mag + Planck18 luminosity distance"
        except Exception as exc:
            return np.nan, f"luminosity estimate failed: {exc}"
    defaults = {"Ia": 9.4, "II": 8.8, "Ibc": 9.0}
    return defaults.get(sn_family, 9.0), "type default; set MANUAL_LOG_LSUN or MANUAL_APPARENT_MAG"


def tardis_type_family(sn_type: object) -> str:
    canonical = sp.canonical_sn_type(sn_type)
    if canonical in {"ii", "iin"}:
        return "II"
    if canonical in {"iib", "ib", "ic", "icbl"}:
        return "Ibc"
    return "Ia"


def _choose_velocity(line_qc: pd.DataFrame, sn_type: object) -> tuple[float, str]:
    if line_qc.empty:
        return np.nan, ""
    rows = line_qc.copy()
    if "velocity_kms" not in rows.columns or "qc_flag" not in rows.columns:
        return np.nan, ""
    rows["velocity_kms"] = pd.to_numeric(rows.get("velocity_kms"), errors="coerce").abs()
    rows = rows[rows["velocity_kms"].notna() & rows["qc_flag"].isin(["adopt", "check"])]
    if rows.empty:
        return np.nan, ""
    primary = sp.primary_lines_for_type(sn_type)
    for flag in ["adopt", "check"]:
        subset = rows[rows["qc_flag"].eq(flag)]
        if subset.empty:
            continue
        if primary:
            primary_subset = subset[subset["line"].isin(primary)]
            if not primary_subset.empty:
                value = float(np.nanmedian(primary_subset["velocity_kms"]))
                lines = ", ".join(sorted(primary_subset["line"].unique()))
                return value, f"{flag} primary lines: {lines}"
        value = float(np.nanmedian(subset["velocity_kms"]))
        lines = ", ".join(sorted(subset["line"].unique()))
        return value, f"{flag} lines: {lines}"
    return np.nan, ""


def estimate_tardis_context(
    project_root: Path,
    target: str,
    *,
    analysis_tag: str | None = None,
    spectrum_index: int = 0,
    manual_z: float | None = None,
    manual_type: str = "",
    manual_velocity_kms: float | None = None,
    manual_epoch_days: float | None = None,
    manual_apparent_mag: float | None = None,
    manual_log_lsun: float | None = None,
) -> dict[str, object]:
    """Collect a first-pass TARDIS starting point from local spectra and 02 products."""
    project_root = Path(project_root)
    key = target_key(target)
    analysis_dir = project_root / "output" / "analysis_pipeline"
    spectra_all, skipped = load_observed_spectra(project_root, target_metadata={})
    spectra = sorted(
        [spec for spec in spectra_all if spec["target"] == key],
        key=lambda spec: pd.Timestamp.max if pd.isna(spec["date_obs"]) else spec["date_obs"],
    )
    if not spectra:
        raise FileNotFoundError(f"No local 1-D FITS spectra found for {key} under {project_root / 'data'}")

    target_status = read_combined_analysis_products(analysis_dir, "target_status.csv", tag=analysis_tag)
    spectra_summary = read_combined_analysis_products(analysis_dir, "spectra_summary.csv", tag=analysis_tag)
    redshift_summary = read_combined_analysis_products(analysis_dir, "manual_redshift_summary.csv", tag=analysis_tag)
    line_qc = read_combined_analysis_products(analysis_dir, "line_diagnostics_qc.csv", tag=analysis_tag)
    bb_table = read_combined_analysis_products(analysis_dir, "blackbody_temperature.csv", tag=analysis_tag)

    target_status = target_status[target_status["target"].eq(key)] if "target" in target_status.columns else pd.DataFrame()
    spectra_summary = spectra_summary[spectra_summary["target"].eq(key)] if "target" in spectra_summary.columns else pd.DataFrame()
    redshift_summary = redshift_summary[redshift_summary["target"].eq(key)] if "target" in redshift_summary.columns else pd.DataFrame()
    line_qc = line_qc[line_qc["target"].eq(key)] if "target" in line_qc.columns else pd.DataFrame()
    bb_table = bb_table[bb_table["target"].eq(key)] if "target" in bb_table.columns else pd.DataFrame()

    z_manual = sp.parse_float(manual_z)
    if np.isfinite(z_manual):
        z, z_source = z_manual, "manual override"
    else:
        z, z_col = _first_finite(redshift_summary, ["z_manual", "z"])
        z_source = f"manual_redshift_summary.{z_col}" if z_col else ""
        if not np.isfinite(z):
            z, z_col = _first_finite(target_status, ["z"])
            z_source = f"target_status.{z_col}" if z_col else ""
        if not np.isfinite(z):
            z, z_col = _first_finite(spectra_summary, ["z"])
            z_source = f"spectra_summary.{z_col}" if z_col else "unset"

    sn_type = str(manual_type).strip()
    type_source = "manual override" if sn_type else ""
    if not sn_type:
        sn_type, type_col = _first_text(target_status, ["type", "rough_type", "template_type"])
        type_source = f"target_status.{type_col}" if type_col else ""
    if not sn_type:
        sn_type, type_col = _first_text(spectra_summary, ["type", "rough_type"])
        type_source = f"spectra_summary.{type_col}" if type_col else "unset"
    if not sn_type:
        sn_type = "Unclassified"

    sn_family = tardis_type_family(sn_type)
    velocity_manual = sp.parse_float(manual_velocity_kms)
    if np.isfinite(velocity_manual):
        velocity_kms, velocity_source = velocity_manual, "manual override"
    else:
        velocity_kms, velocity_source = _choose_velocity(line_qc, sn_type)
        if not np.isfinite(velocity_kms):
            velocity_defaults = {"Ia": 11000.0, "II": 8000.0, "Ibc": 10000.0}
            velocity_kms = velocity_defaults.get(sn_family, 10000.0)
            velocity_source = "type default; set MANUAL_VELOCITY_KMS"

    epoch_manual = sp.parse_float(manual_epoch_days)
    if np.isfinite(epoch_manual):
        epoch_days, epoch_source = epoch_manual, "manual override"
    else:
        phases = pd.to_numeric(spectra_summary.get("phase_days", pd.Series(dtype=float)), errors="coerce").dropna()
        if phases.empty:
            phases = pd.Series([spec["phase_days"] for spec in spectra], dtype=float).dropna()
        rise_default = {"Ia": 18.0, "II": 15.0, "Ibc": 15.0}.get(sn_family, 15.0)
        if not phases.empty:
            epoch_days = max(5.0, float(np.nanmedian(phases)) + rise_default)
            epoch_source = f"median phase_days + {rise_default:g} d type default rise"
        else:
            epoch_days = rise_default
            epoch_source = "type default; set MANUAL_EPOCH_DAYS"

    log_manual = sp.parse_float(manual_log_lsun)
    if np.isfinite(log_manual):
        log_lsun, luminosity_source = log_manual, "manual override"
    else:
        apparent = sp.parse_float(manual_apparent_mag)
        log_lsun, luminosity_source = _estimate_log_lsun(z, apparent, sn_family)

    if sn_family == "Ia":
        v_phot = 0.7 * velocity_kms
    else:
        v_phot = velocity_kms
    v_start = max(2500.0, 0.6 * v_phot)
    v_stop = min(35000.0, max(v_start + 3000.0, 1.3 * velocity_kms))

    for spec in spectra:
        if np.isfinite(z):
            spec["z"] = z
            spec["z_source"] = z_source
        spec["type"] = sn_type
    spectrum_index = int(np.clip(spectrum_index, 0, len(spectra) - 1))
    spectrum = spectra[spectrum_index]
    return {
        "target": key,
        "spectra": spectra,
        "spectrum": spectrum,
        "spectrum_index": spectrum_index,
        "skipped_fits": skipped,
        "z": float(z) if np.isfinite(z) else np.nan,
        "z_source": z_source,
        "sn_type": sn_type,
        "type_source": type_source,
        "sn_family": sn_family,
        "velocity_kms": float(velocity_kms),
        "velocity_source": velocity_source,
        "epoch_days": float(epoch_days),
        "epoch_source": epoch_source,
        "log_lsun": float(log_lsun) if np.isfinite(log_lsun) else np.nan,
        "luminosity_source": luminosity_source,
        "v_start_kms": float(v_start),
        "v_stop_kms": float(v_stop),
        "analysis_tables": {
            "target_status": target_status,
            "spectra_summary": spectra_summary,
            "manual_redshift_summary": redshift_summary,
            "line_diagnostics_qc": line_qc,
            "blackbody_temperature": bb_table,
        },
    }


def tardis_context_table(context: dict[str, object]) -> pd.DataFrame:
    fields = [
        ("target", context.get("target"), ""),
        ("selected spectrum", context.get("spectrum", {}).get("file", ""), f"index={context.get('spectrum_index')}"),
        ("redshift z", context.get("z"), context.get("z_source")),
        ("SN type", context.get("sn_type"), context.get("type_source")),
        ("TARDIS family", context.get("sn_family"), "Ia / II / Ibc abundance preset"),
        ("line velocity", context.get("velocity_kms"), context.get("velocity_source")),
        ("time_explosion", context.get("epoch_days"), context.get("epoch_source")),
        ("luminosity", context.get("log_lsun"), context.get("luminosity_source")),
        ("velocity start", context.get("v_start_kms"), "0.6 x photospheric proxy"),
        ("velocity stop", context.get("v_stop_kms"), "1.3 x line velocity proxy"),
    ]
    return pd.DataFrame(fields, columns=["parameter", "value", "source_or_note"])


def build_tardis_config_from_context(
    context: dict[str, object],
    *,
    project_root: Path,
    base_config_path: Path | None = None,
    output_config_path: Path | None = None,
) -> tuple[dict, Path]:
    import yaml

    project_root = Path(project_root)
    base_config_path = base_config_path or project_root / "configs" / "tardis" / "base_Ia.yml"
    output_config_path = output_config_path or project_root / "configs" / "tardis" / f"{context['target']}.yml"
    config = yaml.safe_load(base_config_path.read_text())
    config.setdefault("supernova", {})
    config["supernova"]["luminosity_requested"] = f"{context['log_lsun']:.2f} log_lsun"
    config["supernova"]["time_explosion"] = f"{context['epoch_days']:.1f} day"
    config.setdefault("model", {}).setdefault("structure", {}).setdefault("velocity", {})
    config["model"]["structure"]["velocity"]["start"] = f"{context['v_start_kms']:.1f} km/s"
    config["model"]["structure"]["velocity"]["stop"] = f"{context['v_stop_kms']:.1f} km/s"
    config["atom_data"] = str((project_root / "data" / "kurucz_cd23_chianti_H_He_latest.h5").resolve())

    family = str(context.get("sn_family", "Ia"))
    if family == "II":
        config["model"]["abundances"] = {
            "type": "uniform",
            "H": 0.70,
            "He": 0.28,
            "O": 0.01,
            "Si": 0.005,
            "S": 0.005,
        }
    elif family == "Ibc":
        config["model"]["abundances"] = {
            "type": "uniform",
            "He": 0.50,
            "O": 0.30,
            "C": 0.15,
            "Si": 0.03,
            "S": 0.02,
        }

    output_config_path.parent.mkdir(parents=True, exist_ok=True)
    output_config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config, output_config_path


def extract_tardis_spectrum_arrays(sim) -> tuple[np.ndarray, np.ndarray]:
    spectrum = sim.spectrum_solver.spectrum_real_packets
    wave = np.asarray(spectrum.wavelength.value, dtype=float)
    flux = np.asarray(spectrum.luminosity_density_lambda.value, dtype=float)
    order = np.argsort(wave)
    return wave[order], flux[order]


def normalize_for_comparison(flux: np.ndarray) -> np.ndarray:
    finite = np.isfinite(flux)
    if not finite.any():
        return flux
    scale = np.nanpercentile(np.abs(flux[finite]), 95)
    return flux / scale if np.isfinite(scale) and scale else flux


def plot_tardis_comparison(
    observed_spec: dict,
    tardis_wave: np.ndarray,
    tardis_flux: np.ndarray,
    *,
    z: float,
    target: str,
    output_path: Path | None = None,
):
    obs_wave = observed_to_rest(observed_spec["wave"], z)
    obs_flux = normalize_for_comparison(observed_spec["flux"])
    sim_wave = np.asarray(tardis_wave, dtype=float)
    sim_flux = normalize_for_comparison(np.asarray(tardis_flux, dtype=float))
    order = np.argsort(sim_wave)
    sim_wave = sim_wave[order]
    sim_flux = sim_flux[order]

    fig, axes = plt.subplots(2, 1, figsize=(10.5, 6.2), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(obs_wave, obs_flux, color="black", lw=0.8, label="Observed rest-frame spectrum")
    axes[0].plot(sim_wave, sim_flux, color="#d95f02", lw=1.0, alpha=0.85, label="TARDIS synthetic spectrum")
    axes[0].set_ylabel("Normalized flux / luminosity density")
    axes[0].set_title(f"{target}: qualitative TARDIS comparison")
    axes[0].grid(alpha=0.25)
    axes[0].legend(fontsize=8)

    mask = np.isfinite(obs_wave) & np.isfinite(obs_flux)
    common = mask & (obs_wave >= np.nanmin(sim_wave)) & (obs_wave <= np.nanmax(sim_wave))
    if common.sum() > 10:
        interp = np.interp(obs_wave[common], sim_wave, sim_flux)
        axes[1].plot(obs_wave[common], obs_flux[common] - interp, color="0.25", lw=0.7)
    axes[1].axhline(0, color="0.55", ls="--", lw=0.8)
    axes[1].set_xlabel("Rest wavelength (Angstrom)")
    axes[1].set_ylabel("Residual")
    axes[1].grid(alpha=0.25)
    axes[1].set_xlim(3000, 10000)
    if output_path is not None:
        output_path = Path(output_path)
        save_figure(fig, output_path.parent, output_path.name, enabled=True)
    return fig


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


def selected_line_plan(spectra: Iterable[dict], target_lines: dict[str, list[str]] | None = None) -> pd.DataFrame:
    rows = []
    for spec in spectra:
        rows.append(
            {
                "target": spec["target"],
                "type": spec.get("type", ""),
                "type_source": spec.get("type_source", ""),
                "selected_lines": ", ".join(line_keys_for(spec, target_lines)),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["target", "type", "type_source", "selected_lines"])
    return pd.DataFrame(rows).drop_duplicates().sort_values(["target", "type"]).reset_index(drop=True)


def _robust_noise(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 5:
        return np.nan
    med = np.nanmedian(values)
    noise = 1.4826 * np.nanmedian(np.abs(values - med))
    if not np.isfinite(noise) or noise <= 0:
        noise = np.nanstd(values)
    return float(noise)


def _line_emission_snr(wave: np.ndarray, flux: np.ndarray, center: float) -> float:
    signal = (wave > center - 7.0) & (wave < center + 7.0)
    side = ((wave > center - 65.0) & (wave < center - 18.0)) | ((wave > center + 18.0) & (wave < center + 65.0))
    if signal.sum() < 3 or side.sum() < 8:
        return np.nan
    continuum = np.nanmedian(flux[side])
    noise = _robust_noise(flux[side])
    if not np.isfinite(noise) or noise <= 0:
        return np.nan
    return float((np.nanmax(flux[signal]) - continuum) / noise)


def estimate_host_redshift_rough(
    spec: dict,
    *,
    z_min: float = 0.0,
    z_max: float = 0.08,
    z_step: float = 0.0005,
) -> dict[str, object]:
    """Rough host redshift from narrow emission-line coincidences in the observed spectrum."""
    wave = np.asarray(spec["wave"], dtype=float)
    flux = sp.smooth_flux(np.asarray(spec["flux"], dtype=float), preferred_window=11)
    valid = np.isfinite(wave) & np.isfinite(flux)
    wave = wave[valid]
    flux = flux[valid]
    if wave.size < 50:
        return {"z_rough": np.nan, "host_score": 0.0, "host_lines": "", "status": "too few points"}

    host_lines = ["Halpha", "Hbeta", "OIII5007", "OIII4959", "SII6716", "SII6731"]
    best = {"z_rough": np.nan, "host_score": 0.0, "host_lines": "", "status": "no narrow host-line match"}
    for z in np.arange(z_min, z_max + z_step / 2.0, z_step):
        scores = []
        labels = []
        for line in host_lines:
            rest = sp.HOST_LINES[line]
            center = rest * (1.0 + z)
            if center < np.nanmin(wave) + 70.0 or center > np.nanmax(wave) - 70.0:
                continue
            snr = _line_emission_snr(wave, flux, center)
            if np.isfinite(snr) and snr > 2.5:
                scores.append(min(float(snr), 12.0))
                labels.append(f"{line}:{snr:.1f}")
        if not scores:
            continue
        score = float(np.sum(np.maximum(np.asarray(scores) - 2.0, 0.0)))
        if len(scores) >= 2:
            score *= 1.35
        if score > best["host_score"]:
            best = {"z_rough": float(z), "host_score": score, "host_lines": ", ".join(labels), "status": "host emission heuristic"}
    if best["host_score"] < 1.0:
        best["z_rough"] = np.nan
    return best


def _feature_signal(row: pd.Series | dict) -> float:
    status = row.get("status", "")
    if status != "ok":
        return 0.0
    depth = sp.parse_float(row.get("depth"))
    pew = sp.parse_float(row.get("pEW_A"))
    velocity = sp.parse_float(row.get("velocity_kms"))
    if not np.isfinite(depth) or depth <= 0:
        return 0.0
    if np.isfinite(velocity) and (velocity < 500 or velocity > 35000):
        return 0.0
    return float(np.clip(2.8 * depth, 0.0, 1.0) + np.clip(pew / 120.0, 0.0, 0.45))


def rough_line_features_for_spectrum(spec: dict, z: float, line_keys: Iterable[str] | None = None) -> pd.DataFrame:
    wave_rest = spec["wave"] / (1.0 + z) if np.isfinite(z) else spec["wave"].copy()
    rows = []
    for line_key in line_keys or sp.LINE_LIBRARY.keys():
        if line_key not in sp.LINE_LIBRARY:
            continue
        row = sp.measure_absorption_line(wave_rest, spec["flux"], line_key, half_width=520.0)
        row.update(
            {
                "target": spec["target"],
                "file": spec["file"],
                "date_obs": spec["date_obs"],
                "line_signal": _feature_signal(row),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def rough_type_scores(feature_table: pd.DataFrame) -> dict[str, float]:
    if feature_table.empty:
        return {"SN Ia": 0.0, "SN II": 0.0, "SN IIb": 0.0, "SN Ib": 0.0, "SN Ic": 0.0}
    signal = {row["line"]: _feature_signal(row) for _, row in feature_table.iterrows()}

    def s(name: str) -> float:
        return float(signal.get(name, 0.0))

    h = max(s("Halpha"), 0.8 * s("Hbeta"), 0.6 * s("Hgamma"))
    he = max(s("HeI5876"), 0.8 * s("HeI6678"), 0.7 * s("HeI7065"))
    ca = max(s("CaIIHK"), 0.9 * s("CaIINIR"))
    fe = max(s("FeII5169"), 0.8 * s("FeII5018"), 0.7 * s("FeII4924"))
    si = max(s("SiII6355"), 0.8 * s("SiII5972"))
    scores = {
        "SN Ia": 1.6 * s("SiII6355") + 0.8 * s("SiII5972") + 0.8 * s("SII5640") + 0.45 * ca - 0.45 * h - 0.35 * he,
        "SN II": 1.55 * s("Halpha") + 0.85 * s("Hbeta") + 0.75 * fe + 0.35 * s("ScII5527") - 0.4 * si,
        "SN IIb": 0.95 * s("Halpha") + 1.05 * s("HeI5876") + 0.6 * s("HeI6678") + 0.45 * fe - 0.35 * si,
        "SN Ib": 1.35 * s("HeI5876") + 0.8 * s("HeI6678") + 0.65 * s("HeI7065") + 0.3 * ca - 0.65 * s("Halpha") - 0.35 * si,
        "SN Ic": 1.15 * s("OI7774") + 0.7 * ca + 0.35 * fe + 0.35 * s("CII6580") - 0.75 * h - 0.75 * he - 0.35 * si,
    }
    return {key: float(max(value, 0.0)) for key, value in scores.items()}


def rough_classify_spectra(spectra: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Heuristic SN type/parameter estimate from local spectra only.

    This is a lightweight first-pass classifier, not a replacement for DASH,
    SNID, or Superfit template matching.
    """
    spectrum_rows = []
    feature_frames = []
    for spec in spectra:
        host_z = estimate_host_redshift_rough(spec)
        existing_z = sp.parse_float(spec.get("z"))
        z_used = host_z["z_rough"] if np.isfinite(host_z["z_rough"]) else existing_z
        if not np.isfinite(z_used):
            z_used = 0.0
        features = rough_line_features_for_spectrum(spec, z_used)
        scores = rough_type_scores(features)
        positives = {key: value for key, value in scores.items() if value > 0}
        if positives:
            ranked = sorted(positives.items(), key=lambda item: item[1], reverse=True)
            rough_type = ranked[0][0]
            best_score = ranked[0][1]
            runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
            confidence = best_score / (sum(positives.values()) + 1e-9)
            if best_score < 0.35 or best_score - runner_up < 0.08:
                confidence *= 0.55
            if confidence < 0.35:
                rough_type = "Unclassified"
        else:
            ranked = []
            rough_type = "Unclassified"
            best_score = 0.0
            runner_up = 0.0
            confidence = 0.0

        primary = sp.primary_lines_for_type(rough_type)
        candidate_features = features[features["line"].isin(primary)].copy() if primary else features.copy()
        if candidate_features.empty:
            candidate_features = features.copy()
        candidate_features["line_signal"] = pd.to_numeric(candidate_features["line_signal"], errors="coerce")
        best_line = candidate_features.sort_values("line_signal", ascending=False).head(1)
        if best_line.empty:
            velocity_line = ""
            velocity_kms = np.nan
        else:
            velocity_line = str(best_line.iloc[0]["line"])
            velocity_kms = sp.parse_float(best_line.iloc[0].get("velocity_kms"))

        bb = sp.fit_blackbody_temperature(spec["wave"] / (1.0 + z_used), spec["flux"])
        spectrum_rows.append(
            {
                "target": spec["target"],
                "file": spec["file"],
                "date_obs": spec["date_obs"],
                "rough_type": rough_type,
                "rough_type_confidence": float(confidence),
                "rough_type_score": float(best_score),
                "rough_type_runner_up_score": float(runner_up),
                "rough_z": float(z_used) if np.isfinite(z_used) else np.nan,
                "rough_z_source": host_z["status"] if np.isfinite(host_z["z_rough"]) else ("manual_config" if np.isfinite(existing_z) else "none"),
                "host_line_score": host_z["host_score"],
                "host_line_matches": host_z["host_lines"],
                "rough_velocity_line": velocity_line,
                "rough_velocity_kms": velocity_kms,
                "T_bb_K": bb.get("T_bb_K", np.nan),
                "T_status": bb.get("status", ""),
                "score_detail": "; ".join(f"{key}={value:.2f}" for key, value in sorted(scores.items())),
                "method_note": "heuristic line-score classifier; verify with DASH/SNID/Superfit before final claims",
            }
        )
        feature_frames.append(features.assign(rough_z=z_used, rough_type=rough_type))

    spectrum_table = pd.DataFrame(spectrum_rows)
    feature_table = pd.concat(feature_frames, ignore_index=True) if feature_frames else pd.DataFrame()
    target_rows = []
    if not spectrum_table.empty:
        for target, group in spectrum_table.groupby("target"):
            type_counts = group.groupby("rough_type")["rough_type_confidence"].sum().sort_values(ascending=False)
            rough_type = str(type_counts.index[0]) if not type_counts.empty else "Unclassified"
            z_values = pd.to_numeric(group["rough_z"], errors="coerce").replace(0.0, np.nan).dropna()
            conf = pd.to_numeric(group.loc[group["rough_type"].eq(rough_type), "rough_type_confidence"], errors="coerce")
            velocities = pd.to_numeric(group["rough_velocity_kms"], errors="coerce").dropna()
            target_rows.append(
                {
                    "target": target,
                    "rough_type": rough_type,
                    "rough_type_confidence": float(conf.mean()) if not conf.empty else np.nan,
                    "n_spectra": len(group),
                    "rough_z_median": float(z_values.median()) if not z_values.empty else np.nan,
                    "rough_z_scatter": float(z_values.std(ddof=1)) if len(z_values) > 1 else np.nan,
                    "rough_velocity_median_kms": float(velocities.median()) if not velocities.empty else np.nan,
                    "type_votes": "; ".join(f"{idx}:{val:.2f}" for idx, val in type_counts.items()),
                    "selected_lines": ", ".join(sp.default_lines_for_type(rough_type)),
                }
            )
    target_table = pd.DataFrame(target_rows).sort_values("target").reset_index(drop=True) if target_rows else pd.DataFrame()
    return spectrum_table, target_table, feature_table


def apply_rough_classification_to_spectra(
    spectra: list[dict],
    rough_target_table: pd.DataFrame,
    *,
    apply_type: bool = True,
    apply_z: bool = False,
    overwrite_existing_type: bool = False,
) -> list[dict]:
    if rough_target_table.empty:
        return [dict(spec) for spec in spectra]
    by_target = rough_target_table.set_index("target").to_dict(orient="index")
    updated = []
    for spec in spectra:
        copy = dict(spec)
        row = by_target.get(copy["target"])
        if row:
            rough_type = str(row.get("rough_type", ""))
            if apply_type and rough_type and rough_type != "Unclassified":
                existing = str(copy.get("type", "") or "").strip()
                if overwrite_existing_type or not existing:
                    copy["type"] = rough_type
                    copy["type_source"] = "rough_auto"
            z = sp.parse_float(row.get("rough_z_median"))
            if apply_z and np.isfinite(z) and not np.isfinite(sp.parse_float(copy.get("z"))):
                copy["z"] = z
                copy["z_source"] = "rough_auto"
        updated.append(copy)
    return updated


def normalize_template_type(value: object) -> str:
    text = str(value or "").strip()
    key = sp.canonical_sn_type(text)
    labels = {
        "ia": "SN Ia",
        "ii": "SN II",
        "iin": "SN IIn",
        "iib": "SN IIb",
        "ib": "SN Ib",
        "ic": "SN Ic",
        "icbl": "SN Ic-BL",
    }
    return labels.get(key, "Unclassified")


def _target_filter(targets: Iterable[str] | None) -> set[str]:
    return {target_key(target) for target in (targets or []) if target_key(target)}


def local_spectrum_text_files(project_root: Path, targets: Iterable[str] | None = None) -> list[Path]:
    wanted = _target_filter(targets)
    files = []
    for path in sorted((project_root / "data").glob("SN*/SN*.txt")):
        if path.parent.name == "superfit" or "superfit" in path.parts or path.name.endswith("_binned.txt"):
            continue
        target = target_key(path.parent.name)
        if wanted and target not in wanted:
            continue
        files.append(path)
    return files


def run_superfit_batch(
    project_root: Path,
    *,
    targets: Iterable[str] | None = None,
    z_by_target: dict[str, float] | None = None,
    z_range: tuple[float, float] = (0.0, 0.08),
    z_step: float = 0.005,
    resolution: int = 30,
    how_many_plots: int = 5,
) -> pd.DataFrame:
    """Run NGSF/Superfit on local 2-column spectra under data/SN*/."""
    z_by_target = {target_key(k): sp.parse_float(v) for k, v in (z_by_target or {}).items()}
    files = local_spectrum_text_files(project_root, targets)
    if not files:
        return pd.DataFrame([{"status": "no input spectra"}])

    sn_template_types = [
        "Ia-norm",
        "Ia 91T-like",
        "Ia 91bg-like",
        "Ia-pec",
        "II",
        "IIn",
        "IIb",
        "Ib",
        "Ic",
        "Ic-BL",
        "SLSN-I",
        "SLSN-II",
        "TDE H",
        "TDE H+He",
    ]
    galaxy_template_types = ["E", "S0", "Sa", "Sb", "Sc"]
    runner_code = r'''
import json
import sys
import matplotlib
matplotlib.use("Agg")

params = json.loads(sys.argv[1])
sys.argv = ["ngsf_notebook", json.dumps(params)]

from NGSF.sf_class import Superfit

fit = Superfit()
fit.superfit()
print(fit.results_path)
'''

    rows = []
    for spec_file in files:
        target = target_key(spec_file.parent.name)
        out_dir = spec_file.parent / "superfit"
        out_dir.mkdir(parents=True, exist_ok=True)
        z_exact = z_by_target.get(target, np.nan)
        use_exact_z = bool(np.isfinite(z_exact))
        params = {
            "object_to_fit": str(spec_file.resolve()),
            "use_exact_z": 1 if use_exact_z else 0,
            "z_exact": float(z_exact) if use_exact_z else 0.0,
            "z_range_begin": float(z_range[0]),
            "z_range_end": float(z_range[1]),
            "z_int": float(z_step),
            "resolution": int(resolution),
            "temp_sn_tr": sn_template_types,
            "temp_gal_tr": galaxy_template_types,
            "lower_lam": 3800,
            "upper_lam": 8500,
            "error_spectrum": "sg",
            "saving_results_path": str(out_dir.resolve()) + "/",
            "show_plot": 0,
            "show_plot_png": True,
            "how_many_plots": int(how_many_plots),
            "mask_galaxy_lines": 1 if use_exact_z else 0,
            "mask_telluric": 1,
            "minimum_overlap": 0.6,
            "epoch_high": 0,
            "epoch_low": 0,
            "Alam_high": 1.5,
            "Alam_low": -1.5,
            "Alam_interval": 0.5,
        }
        (out_dir / "parameters_used.json").write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-c", runner_code, json.dumps(params)],
            cwd=str(project_root),
            text=True,
            capture_output=True,
        )
        result_csv = out_dir / f"{spec_file.stem}.csv"
        status = "ok" if completed.returncode == 0 and result_csv.exists() else "failed"
        rows.append(
            {
                "target": target,
                "file": str(spec_file.relative_to(project_root)),
                "result_csv": str(result_csv.relative_to(project_root)) if result_csv.exists() else "",
                "status": status,
                "stdout": completed.stdout.strip()[-500:],
                "stderr": completed.stderr.strip()[-500:],
            }
        )
    return pd.DataFrame(rows)


def run_dash_batch(
    project_root: Path,
    *,
    targets: Iterable[str] | None = None,
    z_by_target: dict[str, float] | None = None,
    known_z: bool = False,
    output_path: Path | None = None,
    top_n: int = 5,
) -> pd.DataFrame:
    """Run AstroDash on local 2-column spectra and update DASH_matches.txt."""
    files = local_spectrum_text_files(project_root, targets)
    if not files:
        return pd.DataFrame([{"status": "no input spectra"}])
    output_path = output_path or (project_root / "notebooks" / "DASH_matches.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    z_by_target = {target_key(k): sp.parse_float(v) for k, v in (z_by_target or {}).items()}
    use_known_z = bool(known_z)
    redshifts = []
    if use_known_z:
        for path in files:
            z = z_by_target.get(target_key(path.parent.name), np.nan)
            if not np.isfinite(z):
                use_known_z = False
                break
            redshifts.append(float(z))
    if not use_known_z:
        redshifts = []

    try:
        from astrodash import Classify

        classifier = Classify(
            filenames=[str(path) for path in files],
            redshifts=redshifts,
            knownZ=use_known_z,
            classifyHost=False,
            rlapScores=True,
        )
        classifier.list_best_matches(n=int(top_n), saveFilename=str(output_path))
        parsed = summarize_existing_dash_results(project_root)
        if not parsed.empty:
            parsed = parsed[parsed["file"].isin([path.name for path in files])].reset_index(drop=True)
            parsed["status"] = "ok"
            parsed["output_file"] = str(output_path.relative_to(project_root))
            return parsed
        return pd.DataFrame(
            [
                {
                    "target": target_key(path.parent.name),
                    "file": path.name,
                    "status": "ok",
                    "output_file": str(output_path.relative_to(project_root)),
                }
                for path in files
            ]
        )
    except Exception as exc:
        return pd.DataFrame(
            [
                {
                    "target": target_key(path.parent.name),
                    "file": str(path.relative_to(project_root)),
                    "status": "failed",
                    "error": repr(exc),
                    "output_file": str(output_path.relative_to(project_root)),
                }
                for path in files
            ]
        )


def summarize_existing_dash_results(project_root: Path) -> pd.DataFrame:
    path = project_root / "notebooks" / "DASH_matches.txt"
    if not path.exists():
        return pd.DataFrame()
    rows = []
    pattern = re.compile(
        r"^(?P<file>\S+)\s+z=(?P<z>[0-9.\-]+)\s+\('(?P<dash_type>[^']+)',\s*'(?P<phase>[^']+)',\s*(?P<prob>[^)]+)\).*?rlap:\s*(?P<rlap>[0-9.]+)",
        re.IGNORECASE,
    )
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line.strip())
        if not match:
            continue
        file_name = match.group("file")
        target = target_key(file_name.split("_")[0])
        dash_type = match.group("dash_type")
        rows.append(
            {
                "target": target,
                "file": file_name,
                "method": "DASH",
                "template_type_raw": dash_type,
                "template_type": normalize_template_type(dash_type),
                "z": sp.parse_float(match.group("z")),
                "phase": match.group("phase"),
                "score": sp.parse_float(match.group("rlap")),
                "weight": max(0.2, sp.parse_float(match.group("rlap")) / 10.0),
            }
        )
    return pd.DataFrame(rows)


def summarize_local_template_classifications(project_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    superfit = summarize_existing_superfit_results(project_root)
    if not superfit.empty:
        for _, row in superfit.iterrows():
            sn_fraction = sp.parse_float(row.get("sn_fraction"))
            chi = sp.parse_float(row.get("chi2_dof2"))
            weight = sn_fraction if np.isfinite(sn_fraction) and sn_fraction > 0 else 0.5
            if np.isfinite(chi) and chi > 0:
                weight *= min(2.0, 0.05 / chi)
            rows.append(
                {
                    "target": row["target"],
                    "file": row["file"],
                    "method": "Superfit",
                    "template_type_raw": row["best_superfit_type"],
                    "template_type": normalize_template_type(row["best_superfit_type"]),
                    "z": row.get("z", np.nan),
                    "phase": row.get("phase", np.nan),
                    "score": row.get("chi2_dof2", np.nan),
                    "weight": float(max(weight, 0.1)),
                }
            )
    dash = summarize_existing_dash_results(project_root)
    if not dash.empty:
        rows.extend(dash.to_dict(orient="records"))
    spectrum_table = pd.DataFrame(rows)
    if spectrum_table.empty:
        return spectrum_table, pd.DataFrame()

    target_rows = []
    for target, group in spectrum_table.groupby("target"):
        valid = group[group["template_type"].ne("Unclassified")].copy()
        if valid.empty:
            template_type = "Unclassified"
            confidence = 0.0
            votes = ""
        else:
            votes_series = valid.groupby("template_type")["weight"].sum().sort_values(ascending=False)
            template_type = str(votes_series.index[0])
            confidence = float(votes_series.iloc[0] / votes_series.sum()) if votes_series.sum() > 0 else 0.0
            votes = "; ".join(f"{idx}:{val:.2f}" for idx, val in votes_series.items())
        z_values = pd.to_numeric(valid["z"], errors="coerce").dropna() if not valid.empty else pd.Series(dtype=float)
        target_rows.append(
            {
                "target": target,
                "template_type": template_type,
                "template_type_confidence": confidence,
                "template_z_median": float(z_values.median()) if not z_values.empty else np.nan,
                "n_template_results": len(group),
                "template_votes": votes,
                "method": ", ".join(sorted(group["method"].unique())),
            }
        )
    target_table = pd.DataFrame(target_rows).sort_values("target").reset_index(drop=True)
    return spectrum_table.sort_values(["target", "method", "file"]).reset_index(drop=True), target_table


def combine_template_and_rough_classifications(template_target_table: pd.DataFrame, rough_target_table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    targets = sorted(set(template_target_table.get("target", [])) | set(rough_target_table.get("target", [])))
    template_by_target = template_target_table.set_index("target") if not template_target_table.empty else pd.DataFrame()
    rough_by_target = rough_target_table.set_index("target") if not rough_target_table.empty else pd.DataFrame()
    for target in targets:
        trow = template_by_target.loc[target] if target in template_by_target.index else None
        rrow = rough_by_target.loc[target] if target in rough_by_target.index else None
        template_type = trow.get("template_type", "Unclassified") if isinstance(trow, pd.Series) else "Unclassified"
        rough_type = rrow.get("rough_type", "Unclassified") if isinstance(rrow, pd.Series) else "Unclassified"
        if template_type and template_type != "Unclassified":
            adopted_type = template_type
            source = f"local_template:{trow.get('method', '')}"
            confidence = sp.parse_float(trow.get("template_type_confidence"))
        elif rough_type and rough_type != "Unclassified":
            adopted_type = rough_type
            source = "heuristic_line_score"
            confidence = sp.parse_float(rrow.get("rough_type_confidence"))
        else:
            adopted_type = "Unclassified"
            source = "none"
            confidence = np.nan
        template_z = sp.parse_float(trow.get("template_z_median")) if isinstance(trow, pd.Series) else np.nan
        rough_z = sp.parse_float(rrow.get("rough_z_median")) if isinstance(rrow, pd.Series) else np.nan
        rows.append(
            {
                "target": target,
                "adopted_type": adopted_type,
                "type_source": source,
                "type_confidence": confidence,
                "template_type": template_type,
                "rough_type": rough_type,
                "template_z_median": template_z,
                "rough_z_median": rough_z,
                "selected_lines": ", ".join(sp.default_lines_for_type(adopted_type)),
            }
        )
    return pd.DataFrame(rows).sort_values("target").reset_index(drop=True)


def apply_classification_context_to_spectra(
    spectra: list[dict],
    classification_target_table: pd.DataFrame,
    *,
    apply_type: bool = True,
    apply_z: bool = False,
    overwrite_existing_type: bool = False,
) -> list[dict]:
    if classification_target_table.empty:
        return [dict(spec) for spec in spectra]
    by_target = classification_target_table.set_index("target").to_dict(orient="index")
    updated = []
    for spec in spectra:
        copy = dict(spec)
        row = by_target.get(copy["target"])
        if row:
            adopted_type = str(row.get("adopted_type", ""))
            if apply_type and adopted_type and adopted_type != "Unclassified":
                existing = str(copy.get("type", "") or "").strip()
                if overwrite_existing_type or not existing:
                    copy["type"] = adopted_type
                    copy["type_source"] = row.get("type_source", "local_classification")
            z = sp.parse_float(row.get("template_z_median"))
            if not np.isfinite(z):
                z = sp.parse_float(row.get("rough_z_median"))
            if apply_z and np.isfinite(z) and not np.isfinite(sp.parse_float(copy.get("z"))):
                copy["z"] = z
                copy["z_source"] = "local_classification"
        updated.append(copy)
    return updated


def plot_rough_classification_summary(target_table: pd.DataFrame, fig_dir: Path, *, save_figures: bool = True):
    if target_table.empty:
        print("No rough-classification results to plot.")
        return None
    table = target_table.copy()
    type_col = "adopted_type" if "adopted_type" in table.columns else "rough_type"
    conf_col = "type_confidence" if "type_confidence" in table.columns else "rough_type_confidence"
    table[conf_col] = pd.to_numeric(table[conf_col], errors="coerce").fillna(0.0)
    fig, ax = plt.subplots(figsize=(10, max(3.5, 0.55 * len(table))))
    labels = table["target"].astype(str) + "  " + table[type_col].astype(str)
    ax.barh(labels, table[conf_col], color="#5b7c99")
    ax.set_xlim(0, 1)
    ax.set_xlabel("Type confidence / vote fraction")
    ax.set_title("Automatic local-spectrum classification context")
    ax.grid(axis="x", alpha=0.25)
    save_figure(fig, fig_dir, "rough_classification_summary.png", enabled=save_figures)
    return fig


def summarize_existing_superfit_results(project_root: Path) -> pd.DataFrame:
    rows = []
    for csv_path in sorted((project_root / "data").glob("SN*/superfit/*.csv")):
        try:
            table = pd.read_csv(csv_path)
        except Exception:
            continue
        if table.empty or "SN" not in table.columns:
            continue
        best = table.iloc[0]
        template = str(best.get("SN", ""))
        rows.append(
            {
                "target": target_key(csv_path.parents[1].name),
                "file": str(csv_path.relative_to(project_root)),
                "best_superfit_type": template.split("/")[0],
                "best_template": template,
                "z": sp.parse_float(best.get("Z")),
                "phase": best.get("Phase", np.nan),
                "chi2_dof2": sp.parse_float(best.get("CHI2/dof2")),
                "sn_fraction": sp.parse_float(best.get("Frac(SN)")),
            }
        )
    return pd.DataFrame(rows).sort_values(["target", "file"]).reset_index(drop=True) if rows else pd.DataFrame()


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


def measure_absorption_line_tuned(
    spec: dict,
    line_key: str,
    *,
    line_half_width: float = 420.0,
    line_smooth_window: int = 21,
    line_edge_fraction: float = 0.18,
    line_param_overrides: dict | None = None,
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
        return sp.format_absorption_line_result(
            line_key,
            line,
            {"status": "outside wavelength range", "fit_method": "gaussian_absorption"},
            pEW_A=np.nan,
        ), {}

    wave = np.asarray(wave_rest[mask], dtype=float)
    raw_flux = np.asarray(spec["flux"][mask], dtype=float)
    smooth = sp.smooth_flux(raw_flux, preferred_window=smooth_window)
    continuum = sp.local_linear_continuum(wave, smooth, edge_fraction=edge_fraction)
    valid = np.isfinite(wave) & np.isfinite(raw_flux) & np.isfinite(smooth) & np.isfinite(continuum) & (np.abs(continuum) > 0)
    if valid.sum() < 12:
        return sp.format_absorption_line_result(
            line_key,
            line,
            {"status": "bad local continuum", "fit_method": "gaussian_absorption"},
            pEW_A=np.nan,
        ), {}

    wave = wave[valid]
    raw_flux = raw_flux[valid]
    smooth = smooth[valid]
    continuum = continuum[valid]
    norm = smooth / continuum

    absorption = np.clip(1.0 - norm, 0.0, None)
    pew = float(np.trapz(absorption, wave))
    fit = sp.fit_normalized_absorption_line(wave, norm, rest, half_width, blue_only=line.get("blue_only", True))
    chi2 = sp.estimate_reduced_chi2(norm, fit.get("fit_norm"), noise_proxy=raw_flux / continuum - norm)
    result = sp.format_absorption_line_result(line_key, line, fit, pEW_A=pew, fit_chi2_red=chi2)
    profile = {
        "wave": wave,
        "raw_flux": raw_flux,
        "smooth": smooth,
        "continuum": continuum,
        "norm": norm,
        "absorption": absorption,
        "fit_norm": fit.get("fit_norm"),
        "fit_info": fit,
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


def fit_redshift_line_gaussian(
    window: dict,
    *,
    mode: str,
    center_guess: float,
    half_width: float,
) -> dict:
    if window.get("status") != "ok":
        status = window.get("status", "window unavailable")
        return {
            "gaussian_status": status,
            "gaussian_wave": np.nan,
            "gaussian_z": np.nan,
            "gaussian_params": {},
            "gaussian_model_norm": None,
            "gaussian_fit_wave": None,
            "gaussian_fit_norm": None,
        }

    wave = np.asarray(window["wave_obs"], dtype=float)
    norm = np.asarray(window["norm"], dtype=float)
    center0 = sp.parse_float(center_guess)
    if not np.isfinite(center0):
        center0 = float(window.get("center_obs", np.nanmedian(wave)))
    local_half = float(min(40.0, max(float(half_width) / 2.0, 1.0)))
    fit_mask = np.isfinite(wave) & np.isfinite(norm) & (wave >= center0 - local_half) & (wave <= center0 + local_half)
    if fit_mask.sum() < 8:
        return {
            "gaussian_status": "fit failed: insufficient local points",
            "gaussian_wave": np.nan,
            "gaussian_z": np.nan,
            "gaussian_params": {},
            "gaussian_model_norm": None,
            "gaussian_fit_wave": None,
            "gaussian_fit_norm": None,
        }

    wave_fit = wave[fit_mask]
    norm_fit = norm[fit_mask]
    x_scale = max(local_half, 1.0)

    baseline0 = float(np.nanmedian(norm_fit))
    if not np.isfinite(baseline0):
        baseline0 = 1.0
    if mode == "absorption":
        amp0 = float(np.nanmin(norm_fit) - baseline0)
        if not np.isfinite(amp0) or amp0 >= 0:
            amp0 = -0.1
        amp_bounds = (-1.5, 0.0)
    else:
        amp0 = float(np.nanmax(norm_fit) - baseline0)
        if not np.isfinite(amp0) or amp0 <= 0:
            amp0 = 0.1
        amp_bounds = (0.0, 1.5)
    sigma0 = float(np.clip(np.nanstd(wave_fit) / 2.0, 5.0, 10.0))
    slope0 = 0.0
    center_delta = min(25.0, local_half)

    def model(wave_vals, center, sigma, amp, baseline, slope):
        x_scaled = (wave_vals - center0) / x_scale
        return baseline + slope * x_scaled + amp * np.exp(-0.5 * ((wave_vals - center) / sigma) ** 2)

    try:
        params, _cov = curve_fit(
            model,
            wave_fit,
            norm_fit,
            p0=(center0, sigma0, amp0, baseline0, slope0),
            bounds=(
                (center0 - center_delta, 0.8, amp_bounds[0], 0.5, -0.5),
                (center0 + center_delta, 50.0, amp_bounds[1], 1.5, 0.5),
            ),
            maxfev=20000,
        )
        fit_norm = model(wave, *params)
        center = float(params[0])
        result = {
            "gaussian_status": "ok",
            "gaussian_wave": center,
            "gaussian_z": np.nan,
            "gaussian_params": {
                "center": center,
                "sigma": float(params[1]),
                "amp": float(params[2]),
                "baseline": float(params[3]),
                "slope": float(params[4]),
            },
            "gaussian_model_norm": fit_norm,
            "gaussian_fit_wave": wave_fit,
            "gaussian_fit_norm": model(wave_fit, *params),
        }
        return result
    except Exception as exc:
        return {
            "gaussian_status": f"fit failed: {exc}",
            "gaussian_wave": np.nan,
            "gaussian_z": np.nan,
            "gaussian_params": {},
            "gaussian_model_norm": None,
            "gaussian_fit_wave": None,
            "gaussian_fit_norm": None,
        }


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
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="This figure includes Axes that are not compatible with tight_layout.*")
            fig.tight_layout()
    except Exception:
        pass
    fig.savefig(path, dpi=180, bbox_inches="tight")
    print(f"saved {path}")
    return path


def show_figure(fig) -> None:
    """Display one figure immediately in notebooks and close it to avoid delayed output."""
    if fig is None:
        return
    try:
        from IPython.display import display as ipy_display

        ipy_display(fig)
    except Exception:
        plt.show()
    finally:
        try:
            plt.close(fig)
        except Exception:
            pass


def spectrum_choice_table(spectra: list[dict], target: str | None = None) -> pd.DataFrame:
    rows = []
    items = spectra
    if target is not None:
        items = [spec for spec in spectra if spec["target"] == target_key(target)]
    items = sorted(items, key=lambda spec: pd.Timestamp.max if pd.isna(spec["date_obs"]) else spec["date_obs"])
    for i, spec in enumerate(items):
        rows.append(
            {
                "spectrum_index": i,
                "target": spec["target"],
                "date_obs": spec["date_obs"],
                "file": spec["file"],
                "z": spec.get("z", np.nan),
                "type": spec.get("type", ""),
            }
        )
    return pd.DataFrame(rows)


def plot_raw_spectral_sequence(
    target: str,
    spectra: list[dict],
    *,
    fig_dir: Path,
    save_figures: bool = True,
    reference_lines: Iterable[str] | None = None,
):
    items = sorted(
        [spec for spec in spectra if spec["target"] == target_key(target)],
        key=lambda spec: pd.Timestamp.max if pd.isna(spec["date_obs"]) else spec["date_obs"],
    )
    if not items:
        print(f"No target {target}")
        return None
    fig, ax = plt.subplots(figsize=(11, max(3.5, 1.6 + 1.0 * len(items))))
    for i, spec in enumerate(items):
        flux = sp.smooth_flux(spec["flux"], preferred_window=11)
        finite = np.isfinite(flux)
        scale = np.nanmedian(np.abs(flux[finite])) if finite.any() else 1.0
        if not np.isfinite(scale) or scale == 0:
            scale = 1.0
        date_label = "" if pd.isna(spec["date_obs"]) else spec["date_obs"].strftime("%Y-%m-%d")
        ax.plot(spec["wave"], flux / scale + i * 1.35, lw=0.8, label=f"{i}: {date_label}")
    for line_key in reference_lines or RAW_SEQUENCE_REFERENCE_LINES:
        if line_key not in sp.LINE_LIBRARY:
            continue
        rest = float(sp.LINE_LIBRARY[line_key]["rest"])
        ax.axvline(rest, color="#a66f00", ls=":", lw=0.8, alpha=0.62)
        ax.text(
            rest,
            0.98,
            line_key,
            rotation=90,
            va="top",
            ha="right",
            transform=ax.get_xaxis_transform(),
            fontsize=7,
            color="#6b4b00",
        )
    ax.set_title(f"{target}: raw observed spectra before redshift/type processing")
    ax.set_xlabel("Observed wavelength (Angstrom)")
    ax.set_ylabel("Scaled flux + offset")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8)
    save_figure(fig, fig_dir, f"raw_spectral_sequence_{target}.png", enabled=save_figures)
    return fig


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
        return {
            **window,
            "gaussian_status": window.get("status", "window unavailable"),
            "gaussian_wave": np.nan,
            "gaussian_z": np.nan,
            "gaussian_params": {},
            "gaussian_model_norm": None,
            "gaussian_fit_wave": None,
            "gaussian_fit_norm": None,
        }, np.nan
    auto_wave = auto_pick_line_wavelength(window, mode=mode)
    gaussian_result = fit_redshift_line_gaussian(window, mode=mode, center_guess=auto_wave, half_width=half_width)
    if gaussian_result.get("gaussian_status") == "ok" and np.isfinite(gaussian_result.get("gaussian_wave", np.nan)):
        gaussian_result["gaussian_z"] = redshift_from_observed(rest_wave, gaussian_result["gaussian_wave"])
    z_auto = redshift_from_observed(rest_wave, auto_wave)
    adopted_wave = float(manual_observed_wave) if manual_observed_wave is not None and np.isfinite(manual_observed_wave) else auto_wave
    z_adopted = redshift_from_observed(rest_wave, adopted_wave)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(window["wave_obs"], window["raw_flux"] / window["continuum"], color="0.7", lw=0.8, label="raw / local continuum")
    ax.plot(window["wave_obs"], window["norm"], color="black", lw=1.1, label="smoothed / local continuum")
    if gaussian_result.get("gaussian_status") == "ok" and gaussian_result.get("gaussian_model_norm") is not None:
        gaussian_label = f"Gaussian fit center={gaussian_result['gaussian_wave']:.2f} A"
        ax.plot(
            window["wave_obs"],
            np.asarray(gaussian_result["gaussian_model_norm"], dtype=float),
            color="#1f77b4",
            lw=1.3,
            label=gaussian_label,
        )
    ax.axvline(window["center_obs"], color="red", ls="--", lw=1.0, label=f"{line_name} at z_guess")
    ax.axvline(auto_wave, color="#1b9e77", ls=":", lw=1.5, label=f"green auto {mode} pick z={z_auto:.5f}")
    ax.axvline(adopted_wave, color="#7b3294", ls="-.", lw=1.5, label=f"purple manual/adopted z={z_adopted:.5f}")
    ax.set_xlabel("Observed wavelength (Angstrom)")
    ax.set_ylabel("Local continuum-normalized flux")
    ax.set_title(f"{spec['target']} {Path(spec['file']).name}: redshift check with {line_name}")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    add_rest_top_axis(ax, z_adopted)
    return {
        "window": window,
        "auto_wave": auto_wave,
        "auto_z": z_auto,
        "adopted_wave": adopted_wave,
        "adopted_z": z_adopted,
        "z": z_adopted,
        **gaussian_result,
        "figure": fig,
    }, z_auto


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
    filename_tag: str | None = None,
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
    fig = plt.figure(figsize=(12, 5.7 * nrows))
    height_ratios = []
    for _ in range(nrows):
        height_ratios.extend([1.0, 1.15])
    grid = fig.add_gridspec(nrows * 2, ncols, height_ratios=height_ratios, hspace=0.42, wspace=0.24)
    used_axes = []
    spec_by_file = {spec["file"]: spec for spec in spectra}
    for panel_i, (_, row) in enumerate(rows.iterrows()):
        panel_row = panel_i // ncols
        panel_col = panel_i % ncols
        ax_flux = fig.add_subplot(grid[panel_row * 2, panel_col])
        ax_norm = fig.add_subplot(grid[panel_row * 2 + 1, panel_col], sharex=ax_flux)
        used_axes.extend([ax_flux, ax_norm])
        spec = spec_by_file.get(row["file"])
        if spec is None:
            ax_flux.axis("off")
            ax_norm.axis("off")
            continue
        result, profile = measure_absorption_line_tuned(spec, row["line"], **measure_kwargs)
        if result.get("status") != "ok":
            ax_flux.set_title(f"{row['target']} {row['line']}: {result.get('status')}", fontsize=9)
            ax_flux.axis("off")
            ax_norm.axis("off")
            continue
        wave = profile["wave"]
        raw_flux = profile["raw_flux"]
        smooth = profile["smooth"]
        continuum = profile["continuum"]
        norm = profile["norm"]
        raw_norm = raw_flux / continuum
        fit_norm = profile["fit_norm"]

        ax_flux.plot(wave, raw_flux, color="0.72", lw=0.7, label="raw flux")
        ax_flux.plot(wave, smooth, color="black", lw=0.9, label="smoothed flux")
        ax_flux.plot(wave, continuum, color="#d99032", lw=1.1, label="local linear continuum")
        ax_flux.fill_between(wave, smooth, continuum, where=continuum > smooth, color="#7b3294", alpha=0.10)
        ax_flux.axvline(result["rest_wave"], color="red", ls="--", lw=0.9, label="rest line")
        legacy_wave = result.get("extrema_wave_A", np.nan)
        if np.isfinite(legacy_wave):
            ax_flux.axvline(legacy_wave, color="0.6", ls=":", lw=1.0, label="legacy minimum reference")
        ax_flux.axvline(result["abs_wave"], color="green", ls=":", lw=1.2, label="Gaussian center")
        title = f"{row['target']} {row['line']}\n{Path(row['file']).name}"
        ax_flux.set_title(title, fontsize=8, pad=3)
        ax_flux.set_ylabel("Flux")
        ax_flux.grid(alpha=0.18)
        ax_flux.tick_params(labelbottom=False)

        ax_norm.plot(wave, raw_norm, color="0.72", lw=0.7, label="raw / continuum")
        ax_norm.plot(wave, norm, color="black", lw=1.0, label="smoothed / continuum")
        if profile["fit_norm"] is not None:
            ax_norm.plot(wave, fit_norm, color="#7b3294", lw=1.0, label="Gaussian fit used for measurement")
        ax_norm.axvline(result["rest_wave"], color="red", ls="--", lw=0.9)
        if np.isfinite(legacy_wave):
            ax_norm.axvline(legacy_wave, color="0.6", ls=":", lw=1.0)
        ax_norm.axvline(result["abs_wave"], color="green", ls=":", lw=1.2)
        ax_norm.fill_between(
            wave,
            norm,
            1.0,
            where=norm < 1.0,
            color="#7b3294",
            alpha=0.15,
            label="pEW integration area",
        )
        if panel_row == nrows - 1:
            ax_norm.set_xlabel("Rest wavelength (Angstrom)")
        else:
            ax_norm.set_xlabel("")
        ax_norm.set_ylabel("Normalized flux")
        ax_norm.grid(alpha=0.2)
        chi2 = result.get("fit_chi2_red", np.nan)
        chi2_text = f"\nchi2r={chi2:.2f}" if np.isfinite(chi2) else ""
        ax_norm.text(
            0.02,
            0.05,
            f"v={result['velocity_kms']:.0f} km/s\npEW={result['pEW_A']:.1f} A, FWHM={result['FWHM_A']:.1f} A{chi2_text}",
            transform=ax_norm.transAxes,
            fontsize=8,
            bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "0.85"},
        )
    for panel_i in range(n, nrows * ncols):
        panel_row = panel_i // ncols
        panel_col = panel_i % ncols
        ax_flux = fig.add_subplot(grid[panel_row * 2, panel_col])
        ax_norm = fig.add_subplot(grid[panel_row * 2 + 1, panel_col])
        ax_flux.axis("off")
        ax_norm.axis("off")
    if used_axes:
        used_axes[0].legend(fontsize=7, loc="best")
    if len(used_axes) > 1:
        used_axes[1].legend(fontsize=7, loc="best")
    save_figure(fig, fig_dir, tagged_filename("line_diagnostics_grid.png", filename_tag), enabled=save_figures)
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
    legacy_wave = result.get("extrema_wave_A", np.nan)

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    axes[0].plot(wave, raw_flux, color="0.72", lw=0.7, label="raw local spectrum")
    axes[0].plot(wave, smooth, color="black", lw=1.0, label="smoothed observed profile")
    axes[0].plot(wave, continuum, color="#d99032", lw=1.2, label="local linear continuum")
    if fit_norm is not None:
        axes[0].plot(wave, fit_norm * continuum, color="#7b3294", lw=1.2, label="Gaussian fit used for measurement")
    axes[0].fill_between(wave, smooth, continuum, where=continuum > smooth, color="#7b3294", alpha=0.12)
    axes[0].axvline(rest, color="red", ls="--", lw=1.0, label="rest wavelength")
    if np.isfinite(legacy_wave):
        axes[0].axvline(legacy_wave, color="0.6", ls=":", lw=1.0, label="legacy minimum reference")
    axes[0].axvline(abs_wave, color="green", ls=":", lw=1.3, label="Gaussian center")
    axes[0].set_ylabel(spec.get("bunit", "Flux"))
    axes[0].set_title(f"{spec['target']} {Path(spec['file']).name} {line_key}")
    axes[0].grid(alpha=0.2)
    axes[0].legend(fontsize=8)

    raw_norm = raw_flux / continuum
    axes[1].plot(wave, raw_norm, color="0.72", lw=0.7, label="raw / continuum")
    axes[1].plot(wave, norm, color="black", lw=1.0, label="smoothed / continuum")
    if fit_norm is not None:
        axes[1].plot(wave, fit_norm, color="#7b3294", lw=1.2, label="Gaussian fit used for measurement")
    axes[1].fill_between(wave, norm, 1.0, where=norm < 1.0, color="#7b3294", alpha=0.18, label="pEW area")
    axes[1].axhline(1.0, color="#d99032", lw=1.0)
    axes[1].axvline(rest, color="red", ls="--", lw=1.0)
    if np.isfinite(legacy_wave):
        axes[1].axvline(legacy_wave, color="0.6", ls=":", lw=1.0)
    axes[1].axvline(abs_wave, color="green", ls=":", lw=1.3)
    axes[1].set_xlabel("Rest wavelength (Angstrom)")
    axes[1].set_ylabel("Normalized flux")
    axes[1].grid(alpha=0.2)
    axes[1].legend(fontsize=8)

    text = (
        f"v={result['velocity_kms']:.0f} km/s, "
        f"pEW={result['pEW_A']:.1f} A, "
        f"FWHM={result['FWHM_A']:.1f} A, "
        f"depth={result['depth']:.2f}, "
        f"chi2r={result.get('fit_chi2_red', np.nan):.2f}"
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


def plot_blackbody_fit_grid(
    spectra: list[dict],
    *,
    target: str | None,
    wave_range: tuple[float, float],
    fig_dir: Path,
    save_figures: bool,
    filename_tag: str | None = None,
):
    items = [spec for spec in spectra if target is None or spec["target"] == target_key(target)]
    if not items:
        print("No spectra to plot.")
        return None
    ncols = 2
    nrows = int(np.ceil(len(items) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 4.0 * nrows), squeeze=False)
    for panel_i, (ax, spec) in enumerate(zip(axes.ravel(), items)):
        panel_row = panel_i // ncols
        prof = blackbody_profile(rest_frame_wave(spec), spec["flux"], wave_range)
        if prof.get("status") != "ok":
            ax.set_title(f"{spec['target']}: {prof.get('status')}\n{Path(spec['file']).name}", fontsize=8, pad=3)
            ax.axis("off")
            continue
        ax.plot(prof["wave"], prof["flux_norm"], color="black", lw=0.9, label="continuum proxy")
        ax.plot(prof["wave"], prof["model"], color="#d95f02", lw=1.2, label="blackbody fit")
        ax.set_title(f"{spec['target']}: T={prof['T_bb_K']:.0f} K\n{Path(spec['file']).name}", fontsize=8, pad=3)
        if panel_row == nrows - 1:
            ax.set_xlabel("Rest wavelength (Angstrom)")
        else:
            ax.set_xlabel("")
        ax.set_ylabel("Scaled flux")
        ax.grid(alpha=0.2)
    for ax in axes.ravel()[len(items):]:
        ax.axis("off")
    axes.ravel()[0].legend(fontsize=8)
    save_figure(fig, fig_dir, tagged_filename("blackbody_fit_grid.png", filename_tag), enabled=save_figures)
    return fig


def plot_host_line_grid(host_lines: pd.DataFrame, *, target: str | None, fig_dir: Path, save_figures: bool, filename_tag: str | None = None):
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
    save_figure(fig, fig_dir, tagged_filename("host_line_detections.png", filename_tag), enabled=save_figures)
    return fig
