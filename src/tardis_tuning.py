"""Batch helpers for qualitative TARDIS tuning against local spectra."""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from scipy.ndimage import median_filter
from scipy.signal import savgol_filter


ATOM_DATA_FILE = "kurucz_cd23_chianti_H_He_latest.h5"
DEFAULT_TARGETS = ("SN2026FVX", "SN2026JLM", "SN2026KID", "SN2026KIE")


@dataclass(frozen=True)
class TargetSeed:
    target: str
    sn_type: str
    sn_family: str
    z: float
    spectrum_file: str
    log_lsun: float
    time_explosion_days: float
    v_start_kms: float
    v_stop_kms: float


@dataclass(frozen=True)
class TardisCandidate:
    target: str
    candidate_id: str
    sn_family: str
    log_lsun: float
    time_explosion_days: float
    v_start_kms: float
    v_stop_kms: float
    density_profile: str
    abundance_preset: str
    model_resource: str | None = None


@dataclass(frozen=True)
class LineWindow:
    name: str
    start_A: float
    stop_A: float


@dataclass(frozen=True)
class ScoreResult:
    total_score: float
    broad_rmse: float
    line_rmse: float
    corr_penalty: float
    min_offset_A: float
    n_points: int
    n_line_points: int

    def as_row(self) -> dict[str, float | int]:
        return asdict(self)


ABUNDANCE_PRESETS: dict[str, dict[str, float | str]] = {
    "ia_standard": {"type": "uniform", "O": 0.19, "Mg": 0.03, "Si": 0.52, "S": 0.19, "Ar": 0.04, "Ca": 0.03},
    "ia_ca_rich": {"type": "uniform", "O": 0.18, "Mg": 0.03, "Si": 0.44, "S": 0.18, "Ar": 0.04, "Ca": 0.13},
    "ia_si_rich": {"type": "uniform", "O": 0.12, "Mg": 0.03, "Si": 0.62, "S": 0.16, "Ar": 0.03, "Ca": 0.04},
    "ii_h_rich": {"type": "uniform", "H": 0.70, "He": 0.28, "O": 0.01, "Si": 0.005, "S": 0.005},
    "ii_balmer_strong": {"type": "uniform", "H": 0.78, "He": 0.20, "O": 0.012, "Si": 0.004, "S": 0.004},
    "ib_he_rich": {"type": "uniform", "He": 0.62, "O": 0.22, "C": 0.10, "Si": 0.035, "S": 0.015, "Ca": 0.01},
    "ic_oxygen_rich": {"type": "uniform", "O": 0.55, "C": 0.22, "Mg": 0.05, "Si": 0.10, "S": 0.04, "Ca": 0.04},
    "ic_ca_rich": {"type": "uniform", "O": 0.48, "C": 0.18, "Mg": 0.04, "Si": 0.11, "S": 0.04, "Ca": 0.15},
}


LINE_WINDOWS_BY_FAMILY: dict[str, tuple[LineWindow, ...]] = {
    "Ia": (
        LineWindow("CaIIHK", 3600.0, 3950.0),
        LineWindow("SiII5972", 5600.0, 6000.0),
        LineWindow("SiII6355", 5900.0, 6400.0),
        LineWindow("CaIINIR", 7800.0, 8700.0),
    ),
    "II": (
        LineWindow("Hbeta", 4550.0, 5000.0),
        LineWindow("FeII5169", 4900.0, 5350.0),
        LineWindow("Halpha", 6100.0, 6750.0),
    ),
    "Ibc": (
        LineWindow("CaIIHK", 3600.0, 3950.0),
        LineWindow("FeII5169", 4900.0, 5350.0),
        LineWindow("OI7774", 7200.0, 8000.0),
        LineWindow("CaIINIR", 7800.0, 8700.0),
    ),
}


def canonical_target(value: object) -> str:
    text = str(value or "").strip().replace(" ", "")
    if not text:
        return ""
    upper = text.upper()
    if upper.startswith(("SN", "AT")):
        return upper
    if upper[:4].isdigit():
        return f"SN{upper}"
    return upper


def _odd_window(window_pixels: int, n: int) -> int:
    if n <= 2:
        return max(1, n)
    window = max(3, int(window_pixels))
    if window % 2 == 0:
        window += 1
    if window > n:
        window = n if n % 2 == 1 else n - 1
    return max(3, window)


def _as_clean_arrays(wave: np.ndarray, flux: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    wave = np.asarray(wave, dtype=float)
    flux = np.asarray(flux, dtype=float)
    mask = np.isfinite(wave) & np.isfinite(flux)
    wave = wave[mask]
    flux = flux[mask]
    if len(wave) == 0:
        return wave, flux
    order = np.argsort(wave)
    wave = wave[order]
    flux = flux[order]
    unique = np.concatenate([[True], np.diff(wave) > 0])
    return wave[unique], flux[unique]


def _fill_bad_flux(flux: np.ndarray) -> np.ndarray:
    flux = np.asarray(flux, dtype=float)
    good = np.isfinite(flux)
    if good.all():
        return flux.copy()
    if not good.any():
        return np.zeros_like(flux)
    x = np.arange(len(flux))
    filled = flux.copy()
    filled[~good] = np.interp(x[~good], x[good], flux[good])
    return filled


def smooth_flux(flux: np.ndarray, *, window_pixels: int = 11) -> np.ndarray:
    flux = _fill_bad_flux(np.asarray(flux, dtype=float))
    if len(flux) < 5:
        return flux
    window = _odd_window(window_pixels, len(flux))
    if window <= 3:
        return flux
    return savgol_filter(flux, window_length=window, polyorder=2, mode="interp")


def continuum_normalize(wave: np.ndarray, flux: np.ndarray, *, window_pixels: int = 151) -> np.ndarray:
    wave, flux = _as_clean_arrays(wave, flux)
    if len(flux) == 0:
        return flux
    flux = _fill_bad_flux(flux)
    if np.nanmedian(flux) < 0:
        flux = -flux
    window = _odd_window(max(window_pixels, 91), len(flux))
    continuum = median_filter(flux, size=window, mode="nearest")
    finite_cont = np.isfinite(continuum) & (np.abs(continuum) > 0)
    if not finite_cont.any():
        scale = np.nanmedian(np.abs(flux))
        scale = scale if np.isfinite(scale) and scale > 0 else 1.0
        return flux / scale
    fallback = np.nanmedian(continuum[finite_cont])
    bad = ~finite_cont | (np.abs(continuum) < max(abs(fallback) * 1e-6, 1e-30))
    continuum = continuum.copy()
    continuum[bad] = fallback
    normalized = flux / continuum
    median = np.nanmedian(normalized[np.isfinite(normalized)])
    if np.isfinite(median) and median != 0:
        normalized = normalized / median
    return normalized


def density_config(profile: str) -> dict[str, object]:
    profile = str(profile or "branch85_w7").strip().lower()
    if profile == "branch85_w7":
        return {"type": "branch85_w7"}
    if profile == "power_law":
        return {"type": "power_law", "time_0": "1 day", "rho_0": "5e-10 g/cm^3", "v_0": "10000 km/s", "exponent": -7}
    if profile == "exponential":
        return {"type": "exponential", "time_0": "1 day", "rho_0": "5e-10 g/cm^3", "v_0": "3000 km/s"}
    if profile == "uniform":
        return {"type": "uniform", "time_0": "1 day", "value": "5e-12 g/cm^3"}
    raise ValueError(f"unsupported density profile: {profile}")


def abundance_config(preset: str) -> dict[str, object]:
    key = str(preset or "").strip()
    if key not in ABUNDANCE_PRESETS:
        raise ValueError(f"unsupported abundance preset: {preset}")
    return dict(ABUNDANCE_PRESETS[key])


def abundance_presets_for_family(family: str) -> list[str]:
    family = str(family or "").strip()
    if family == "II":
        return ["ii_h_rich", "ii_balmer_strong"]
    if family == "Ibc":
        return ["ic_oxygen_rich", "ic_ca_rich", "ib_he_rich"]
    return ["ia_standard", "ia_si_rich", "ia_ca_rich"]


def density_profiles_for_family(family: str) -> list[str]:
    family = str(family or "").strip()
    if family == "Ia":
        return ["branch85_w7"]
    return ["power_law", "exponential"]


def line_windows_for_family(family: str) -> tuple[LineWindow, ...]:
    return LINE_WINDOWS_BY_FAMILY.get(str(family or "").strip(), LINE_WINDOWS_BY_FAMILY["Ia"])


def available_model_resources(project_root: Path | str, family: str) -> list[str]:
    if str(family or "").strip() != "Ia":
        return []
    root = Path(project_root).resolve()
    model_dir = root / "data" / "tardis_models" / "ia"
    if not model_dir.exists():
        return []
    return [str(path.relative_to(root / "data" / "tardis_models")) for path in sorted(model_dir.glob("*.csvy"))]


def generate_candidates(
    seed: TargetSeed,
    *,
    luminosity_offsets: Sequence[float] = (-0.35, 0.0, 0.35),
    epoch_offsets: Sequence[float] = (-6.0, 0.0, 6.0),
    velocity_scales: Sequence[float] = (0.85, 1.0, 1.15),
    abundance_presets: Sequence[str] | None = None,
    density_profiles: Sequence[str] | None = None,
    model_resources: Sequence[str] | None = None,
    max_candidates: int | None = None,
) -> list[TardisCandidate]:
    target = canonical_target(seed.target)
    abundance_presets = list(abundance_presets_for_family(seed.sn_family) if abundance_presets is None else abundance_presets)
    density_profiles = list(density_profiles_for_family(seed.sn_family) if density_profiles is None else density_profiles)
    candidates: list[TardisCandidate] = []
    limit = math.inf if max_candidates is None else max(0, int(max_candidates))
    for lum_offset in luminosity_offsets:
        for velocity_scale in velocity_scales:
            for epoch_offset in epoch_offsets:
                for density_profile in density_profiles:
                    for abundance_preset in abundance_presets:
                        if len(candidates) >= limit:
                            return candidates
                        v_start = max(2500.0, float(seed.v_start_kms) * float(velocity_scale))
                        v_stop = max(v_start + 1500.0, float(seed.v_stop_kms) * float(velocity_scale))
                        candidates.append(
                            TardisCandidate(
                                target=target,
                                candidate_id=f"{target}_c{len(candidates):03d}",
                                sn_family=seed.sn_family,
                                log_lsun=round(float(seed.log_lsun) + float(lum_offset), 4),
                                time_explosion_days=max(3.0, round(float(seed.time_explosion_days) + float(epoch_offset), 4)),
                                v_start_kms=round(v_start, 4),
                                v_stop_kms=round(v_stop, 4),
                                density_profile=str(density_profile),
                                abundance_preset=str(abundance_preset),
                            )
                        )
    for lum_offset in luminosity_offsets:
        for epoch_offset in epoch_offsets:
            for model_resource in model_resources or ():
                if len(candidates) >= limit:
                    return candidates
                resource = str(model_resource)
                model_index = sum(1 for candidate in candidates if candidate.model_resource)
                candidates.append(
                    TardisCandidate(
                        target=target,
                        candidate_id=f"{target}_m{model_index:03d}",
                        sn_family=seed.sn_family,
                        log_lsun=round(float(seed.log_lsun) + float(lum_offset), 4),
                        time_explosion_days=max(3.0, round(float(seed.time_explosion_days) + float(epoch_offset), 4)),
                        v_start_kms=round(float(seed.v_start_kms), 4),
                        v_stop_kms=round(float(seed.v_stop_kms), 4),
                        density_profile="csvy_model",
                        abundance_preset=resource,
                        model_resource=resource,
                    )
                )
    return candidates


def montecarlo_config(packet_scale: str = "quick", *, nthreads: int | None = None) -> dict[str, object]:
    scale = str(packet_scale or "quick").strip().lower()
    threads = int(nthreads or 1)
    if scale == "final":
        no_packets, iterations, last_packets, virtual_packets = 50000, 10, 100000, 3
    elif scale == "quick":
        no_packets, iterations, last_packets, virtual_packets = 12000, 3, 25000, 1
    else:
        raise ValueError("packet_scale must be 'quick' or 'final'")
    return {
        "seed": 23111963,
        "no_of_packets": no_packets,
        "iterations": iterations,
        "last_no_of_packets": last_packets,
        "no_of_virtual_packets": virtual_packets,
        "nthreads": max(1, threads),
        "convergence_strategy": {
            "type": "damped",
            "damping_constant": 0.5,
            "threshold": 0.05,
            "lock_t_inner_cycles": 1,
            "t_inner_update_exponent": -0.5,
        },
    }


def build_tardis_config(
    candidate: TardisCandidate,
    *,
    project_root: Path | str,
    packet_scale: str = "quick",
    nthreads: int | None = None,
) -> dict[str, object]:
    root = Path(project_root).resolve()
    config: dict[str, object] = {
        "tardis_config_version": "v1.0",
        "supernova": {
            "luminosity_requested": f"{candidate.log_lsun:.2f} log_lsun",
            "time_explosion": f"{candidate.time_explosion_days:.1f} day",
        },
        "atom_data": str((root / "data" / ATOM_DATA_FILE).resolve()),
        "plasma": {
            "ionization": "lte",
            "excitation": "lte",
            "radiative_rates_type": "dilute-blackbody",
            "line_interaction_type": "macroatom",
        },
        "montecarlo": montecarlo_config(packet_scale, nthreads=nthreads),
        "spectrum": {
            "start": "500 angstrom",
            "stop": "20000 angstrom",
            "num": 10000,
            "method": "integrated",
            "integrated": {"compute": "Automatic", "points": 1000},
        },
    }
    if candidate.model_resource:
        resource = Path(candidate.model_resource)
        if resource.is_absolute():
            model_path = resource.resolve()
        else:
            model_path = (root / "data" / "tardis_models" / resource).resolve()
            try:
                model_path.relative_to((root / "data" / "tardis_models").resolve())
            except ValueError as exc:
                raise ValueError(f"model resource escapes data/tardis_models: {candidate.model_resource}") from exc
        if not model_path.exists():
            raise FileNotFoundError(f"TARDIS model resource not found: {model_path}")
        config["csvy_model"] = str(model_path)
        config["plasma"] = {
            "ionization": "nebular",
            "excitation": "dilute-lte",
            "radiative_rates_type": "dilute-blackbody",
            "line_interaction_type": "scatter",
        }
        return config

    config["model"] = {
        "structure": {
            "type": "specific",
            "velocity": {
                "start": f"{candidate.v_start_kms:.1f} km/s",
                "stop": f"{candidate.v_stop_kms:.1f} km/s",
                "num": 20,
            },
            "density": density_config(candidate.density_profile),
        },
        "abundances": abundance_config(candidate.abundance_preset),
    }
    return config


def score_spectra(
    obs_wave: np.ndarray,
    obs_flux: np.ndarray,
    sim_wave: np.ndarray,
    sim_flux: np.ndarray,
    *,
    line_windows: Iterable[LineWindow],
    smooth_window: int = 11,
    continuum_window: int = 151,
) -> ScoreResult:
    obs_wave, obs_flux = _as_clean_arrays(obs_wave, obs_flux)
    sim_wave, sim_flux = _as_clean_arrays(sim_wave, sim_flux)
    if len(obs_wave) < 5 or len(sim_wave) < 5:
        return ScoreResult(math.inf, math.inf, math.inf, math.inf, math.inf, 0, 0)

    obs_norm = continuum_normalize(obs_wave, smooth_flux(obs_flux, window_pixels=smooth_window), window_pixels=continuum_window)
    sim_norm = continuum_normalize(sim_wave, smooth_flux(sim_flux, window_pixels=smooth_window), window_pixels=continuum_window)

    lo = max(float(np.nanmin(obs_wave)), float(np.nanmin(sim_wave)), 3600.0)
    hi = min(float(np.nanmax(obs_wave)), float(np.nanmax(sim_wave)), 8800.0)
    common = np.isfinite(obs_wave) & np.isfinite(obs_norm) & (obs_wave >= lo) & (obs_wave <= hi)
    if common.sum() < 10:
        return ScoreResult(math.inf, math.inf, math.inf, math.inf, math.inf, int(common.sum()), 0)

    sim_interp = np.interp(obs_wave[common], sim_wave, sim_norm)
    obs_common = obs_norm[common]
    wave_common = obs_wave[common]
    finite = np.isfinite(obs_common) & np.isfinite(sim_interp)
    if finite.sum() < 10:
        return ScoreResult(math.inf, math.inf, math.inf, math.inf, math.inf, int(finite.sum()), 0)
    obs_common = obs_common[finite]
    sim_interp = sim_interp[finite]
    wave_common = wave_common[finite]
    broad_rmse = float(np.sqrt(np.nanmean((obs_common - sim_interp) ** 2)))

    line_rmses: list[float] = []
    corrs: list[float] = []
    offsets: list[float] = []
    line_points = 0
    for window in line_windows:
        mask = (wave_common >= window.start_A) & (wave_common <= window.stop_A)
        if mask.sum() < 8:
            continue
        ow = wave_common[mask]
        of = obs_common[mask]
        sf = sim_interp[mask]
        line_points += int(mask.sum())
        line_rmses.append(float(np.sqrt(np.nanmean((of - sf) ** 2))))
        if np.nanstd(of) > 0 and np.nanstd(sf) > 0:
            corr = float(np.corrcoef(of, sf)[0, 1])
            if np.isfinite(corr):
                corrs.append(corr)
        obs_min = float(ow[int(np.nanargmin(of))])
        sim_min = float(ow[int(np.nanargmin(sf))])
        offsets.append(abs(obs_min - sim_min))

    line_rmse = float(np.nanmean(line_rmses)) if line_rmses else broad_rmse
    corr_penalty = float(1.0 - np.nanmean(corrs)) if corrs else 1.0
    corr_penalty = max(0.0, min(2.0, corr_penalty)) if np.isfinite(corr_penalty) else 1.0
    min_offset = float(np.nanmean(offsets)) if offsets else 300.0
    total = broad_rmse + 1.5 * line_rmse + 0.75 * corr_penalty + min_offset / 300.0
    return ScoreResult(float(total), broad_rmse, line_rmse, corr_penalty, min_offset, int(finite.sum()), line_points)


def write_yaml(path: Path | str, config: dict[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def save_spectrum(path: Path | str, wave: np.ndarray, flux: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.column_stack([np.asarray(wave, dtype=float), np.asarray(flux, dtype=float)])
    np.savetxt(path, data, header="wavelength_A luminosity_density_lambda_erg_s_A")


def read_spectrum(path: Path | str) -> tuple[np.ndarray, np.ndarray]:
    data = np.loadtxt(path)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError(f"{path} is not a two-column spectrum")
    return np.asarray(data[:, 0], dtype=float), np.asarray(data[:, 1], dtype=float)


def plot_comparison(
    *,
    target: str,
    candidate: TardisCandidate,
    obs_wave: np.ndarray,
    obs_flux: np.ndarray,
    sim_wave: np.ndarray,
    sim_flux: np.ndarray,
    line_windows: Iterable[LineWindow],
    score: ScoreResult,
    output_path: Path | str,
) -> None:
    obs_wave, obs_flux = _as_clean_arrays(obs_wave, obs_flux)
    sim_wave, sim_flux = _as_clean_arrays(sim_wave, sim_flux)
    obs_norm = continuum_normalize(obs_wave, smooth_flux(obs_flux, window_pixels=11), window_pixels=151)
    sim_norm = continuum_normalize(sim_wave, smooth_flux(sim_flux, window_pixels=11), window_pixels=151)

    lo = max(float(np.nanmin(obs_wave)), float(np.nanmin(sim_wave)), 3500.0)
    hi = min(float(np.nanmax(obs_wave)), float(np.nanmax(sim_wave)), 9000.0)
    obs_mask = (obs_wave >= lo) & (obs_wave <= hi) & np.isfinite(obs_norm)
    sim_mask = (sim_wave >= lo) & (sim_wave <= hi) & np.isfinite(sim_norm)
    sim_interp = np.interp(obs_wave[obs_mask], sim_wave, sim_norm) if sim_mask.sum() > 1 else np.array([])

    fig, axes = plt.subplots(2, 1, figsize=(11.0, 6.4), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(obs_wave[obs_mask], obs_norm[obs_mask], color="black", lw=0.9, label="Observed")
    axes[0].plot(sim_wave[sim_mask], sim_norm[sim_mask], color="#d95f02", lw=0.9, alpha=0.9, label="TARDIS")
    for window in line_windows:
        axes[0].axvspan(window.start_A, window.stop_A, color="#4c78a8", alpha=0.10)
        axes[0].text((window.start_A + window.stop_A) / 2.0, 1.72, window.name, ha="center", va="top", fontsize=7, color="#2f4f6f")
    axes[0].set_ylabel("Pseudo-continuum normalized flux")
    axes[0].set_title(
        f"{target} {candidate.candidate_id}: score={score.total_score:.3f}, "
        f"L={candidate.log_lsun:.2f}, t={candidate.time_explosion_days:.1f} d, "
        f"v={candidate.v_start_kms:.0f}-{candidate.v_stop_kms:.0f} km/s"
    )
    axes[0].legend(fontsize=8, loc="upper right")
    axes[0].grid(alpha=0.25)
    axes[0].set_ylim(0.0, 1.8)

    if len(sim_interp) == obs_mask.sum() and len(sim_interp) > 0:
        residual = obs_norm[obs_mask] - sim_interp
        axes[1].plot(obs_wave[obs_mask], residual, color="0.25", lw=0.7)
        axes[1].axhline(0.0, color="0.55", ls="--", lw=0.8)
        axes[1].set_ylim(-0.8, 0.8)
    axes[1].set_xlabel("Rest wavelength (Angstrom)")
    axes[1].set_ylabel("Residual")
    axes[1].grid(alpha=0.25)
    axes[1].set_xlim(lo, hi)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def write_best_summary(path: Path | str, row: dict[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")


def append_scores(path: Path | str, rows: list[dict[str, object]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def copy_best_outputs(
    *,
    target: str,
    project_root: Path | str,
    best_config: Path | str,
    best_spectrum: Path | str,
    best_plot: Path | str,
) -> dict[str, Path]:
    root = Path(project_root).resolve()
    target = canonical_target(target)
    config_target = root / "configs" / "tardis" / f"{target}.yml"
    output_dir = root / "output" / target / "tardis"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_config = output_dir / f"tardis_config_{target}.yml"
    output_spectrum = output_dir / f"tardis_spectrum_{target}.dat"
    output_plot = output_dir / f"tardis_comparison_{target}.png"
    for src, dst in [
        (best_config, config_target),
        (best_config, output_config),
        (best_spectrum, output_spectrum),
        (best_plot, output_plot),
    ]:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return {
        "config": config_target,
        "output_config": output_config,
        "output_spectrum": output_spectrum,
        "output_plot": output_plot,
    }
