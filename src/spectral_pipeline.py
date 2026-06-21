"""Reusable spectral-analysis pipeline for the supernova project.

This module collects the mature analysis logic that used to live in several
notebooks: FITS ingestion, sparse spectral diagnostics, basic host-line checks,
quality flags, and presentation-ready figures.  It intentionally keeps the
physics modest: the project has sparse spectra, so the robust products are
classification context, line velocities/pEW/FWHM, and comparison plots.
"""

from __future__ import annotations

import csv
import math
import os
import tempfile
from pathlib import Path
from typing import Iterable

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib"))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from astropy.io import fits
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter

C_KMS = 299792.458

LINE_LIBRARY = {
    "SiII6355": {"rest": 6355.0, "label": "Si II 6355", "blue_only": True},
    "SiII5972": {"rest": 5972.0, "label": "Si II 5972", "blue_only": True},
    "CII6580": {"rest": 6580.0, "label": "C II 6580", "blue_only": True},
    "CII7234": {"rest": 7234.0, "label": "C II 7234", "blue_only": True},
    "CaIIHK": {
        "rest": 3933.7,
        "label": "Ca II H&K / K",
        "blue_only": True,
        "rest_wave_choice": "blend_proxy",
        "line_blend_note": "Ca II H&K blend proxy using Ca II K 3933.7 A; compare with literature as a blended feature.",
    },
    "SII5640": {"rest": 5640.0, "label": "S II W", "blue_only": False},
    "Halpha": {"rest": 6562.8, "label": "H alpha", "blue_only": True},
    "Hbeta": {"rest": 4861.3, "label": "H beta", "blue_only": True},
    "Hgamma": {"rest": 4340.5, "label": "H gamma", "blue_only": True},
    "FeII4924": {"rest": 4924.0, "label": "Fe II 4924", "blue_only": True},
    "FeII5018": {"rest": 5018.0, "label": "Fe II 5018", "blue_only": True},
    "FeII5169": {"rest": 5169.0, "label": "Fe II 5169", "blue_only": True},
    "ScII5527": {"rest": 5527.0, "label": "Sc II 5527", "blue_only": True},
    "HeI5876": {"rest": 5875.6, "label": "He I 5876", "blue_only": True},
    "HeI6678": {"rest": 6678.2, "label": "He I 6678", "blue_only": True},
    "HeI7065": {"rest": 7065.2, "label": "He I 7065", "blue_only": True},
    "OI7774": {"rest": 7774.0, "label": "O I 7774", "blue_only": True},
    "CaIINIR": {
        "rest": 8579.0,
        "label": "Ca II NIR triplet",
        "blue_only": True,
        "rest_wave_choice": "blend_proxy",
        "line_blend_note": "Ca II NIR triplet blend proxy using 8579 A effective wavelength; compare with literature as a blended feature.",
    },
}

HOST_LINES = {
    "OII3727": 3727.0,
    "Hbeta": 4861.3,
    "OIII4959": 4958.9,
    "OIII5007": 5006.8,
    "NaID5892": 5892.0,
    "Halpha": 6562.8,
    "NII6583": 6583.4,
    "SII6716": 6716.4,
    "SII6731": 6730.8,
}

PRIMARY_LINES_BY_TYPE = {
    "ia": {"SiII6355", "CaIIHK"},
    "ii": {"FeII5169"},
    "iin": {"Halpha", "Hbeta"},
    "iib": {"FeII5169"},
    "ib": {"HeI5876", "HeI6678", "HeI7065"},
    "ic": {"OI7774", "CaIIHK", "CaIINIR"},
    "icbl": {"OI7774", "CaIIHK", "CaIINIR", "FeII5169"},
}

LINES_BY_TYPE = {
    "ia": ["SiII6355", "SiII5972", "SII5640", "CaIIHK", "CaIINIR", "CII6580"],
    "ii": ["Halpha", "Hbeta", "Hgamma", "FeII5169", "FeII5018", "FeII4924", "ScII5527", "CaIIHK", "CaIINIR"],
    "iin": ["Halpha", "Hbeta", "Hgamma", "FeII5169", "CaIIHK"],
    "iib": ["Halpha", "Hbeta", "HeI5876", "HeI6678", "HeI7065", "FeII5169", "CaIIHK", "CaIINIR"],
    "ib": ["HeI5876", "HeI6678", "HeI7065", "CaIIHK", "CaIINIR", "OI7774"],
    "ic": ["OI7774", "CaIIHK", "CaIINIR", "FeII5169", "CII6580"],
    "icbl": ["OI7774", "CaIIHK", "CaIINIR", "FeII5169", "CII6580"],
    "unknown": ["Halpha", "Hbeta", "SiII6355", "HeI5876", "OI7774", "CaIIHK", "CaIINIR"],
}


def normalize_target_name(value: object) -> str:
    value = str(value or "").strip().replace(" ", "")
    if not value:
        return ""
    upper = value.upper()
    if upper.startswith(("SN", "AT")):
        return upper
    if value[:4].isdigit():
        return "SN" + upper
    return upper


def parse_float(value: object) -> float:
    try:
        text = str(value).strip()
        if text in {"", "None", "nan", "---", "null"}:
            return np.nan
        return float(text)
    except Exception:
        return np.nan


def parse_datetime(value: object) -> pd.Timestamp:
    if value is None or str(value).strip() == "":
        return pd.NaT
    return pd.to_datetime(str(value).replace("T", " "), errors="coerce", utc=False)


def canonical_sn_type(sn_type: object) -> str:
    text = str(sn_type or "").lower().replace("-", " ").replace("_", " ")
    compact = text.replace(" ", "")
    if "ia" in compact:
        return "ia"
    if "iib" in compact:
        return "iib"
    if "iin" in compact:
        return "iin"
    if "icbl" in compact or "ic-b l" in text or "ic bl" in text:
        return "icbl"
    if "ib" in compact:
        return "ib"
    if "ic" in compact:
        return "ic"
    if compact.startswith("snii") or "snii" in compact or compact == "ii" or text.endswith(" ii") or " type ii" in text:
        return "ii"
    return "unknown"


def load_tns_metadata(csv_path: Path) -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    if not csv_path.exists():
        return metadata
    lines = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = 1 if lines and not lines[0].startswith('"') else 0
    reader = csv.DictReader(lines[start:])
    for row in reader:
        key = normalize_target_name(f"{row.get('name_prefix', '')}{row.get('name', '')}")
        if not key:
            continue
        metadata[key] = {
            "z": parse_float(row.get("redshift")),
            "type": row.get("type", ""),
            "discoverydate": row.get("discoverydate", ""),
            "ra": parse_float(row.get("ra")),
            "dec": parse_float(row.get("declination")),
            "host": row.get("hostname", "") or row.get("host", ""),
            "internal_names": row.get("internal_names", ""),
        }
    return metadata


def wavelength_axis_from_header(header: fits.Header, n_pix: int) -> np.ndarray | None:
    crval = header.get("CRVAL1")
    crpix = header.get("CRPIX1", 1.0)
    cdelt = header.get("CDELT1", header.get("CD1_1"))
    if crval is None or cdelt is None:
        return None
    pix = np.arange(n_pix, dtype=float) + 1.0
    return float(crval) + (pix - float(crpix)) * float(cdelt)


def odd_window(n: int, preferred: int) -> int | None:
    if n < 5:
        return None
    window = min(int(preferred), n if n % 2 == 1 else n - 1)
    if window < 5:
        window = 5
    if window % 2 == 0:
        window -= 1
    return window if window >= 5 else None


def smooth_flux(flux: np.ndarray, preferred_window: int = 41) -> np.ndarray:
    flux = np.asarray(flux, dtype=float)
    good = np.isfinite(flux)
    if good.sum() < 7:
        return flux
    filled = flux.copy()
    if not good.all():
        x = np.arange(len(flux))
        filled[~good] = np.interp(x[~good], x[good], flux[good])
    window = odd_window(len(filled), preferred_window)
    if window is None:
        return filled
    return savgol_filter(filled, window_length=window, polyorder=min(3, window - 2))


def default_lines_for_type(sn_type: object) -> list[str]:
    return LINES_BY_TYPE.get(canonical_sn_type(sn_type), LINES_BY_TYPE["unknown"])


def primary_lines_for_type(sn_type: object) -> set[str]:
    return PRIMARY_LINES_BY_TYPE.get(canonical_sn_type(sn_type), set())


def local_linear_continuum(wave: np.ndarray, flux: np.ndarray, edge_fraction: float = 0.18) -> np.ndarray:
    n = len(wave)
    edge = max(4, int(edge_fraction * n))
    left_x = np.nanmedian(wave[:edge])
    right_x = np.nanmedian(wave[-edge:])
    left_y = np.nanmedian(flux[:edge])
    right_y = np.nanmedian(flux[-edge:])
    if not np.isfinite(left_y) or not np.isfinite(right_y) or right_x == left_x:
        return np.full_like(flux, np.nanmedian(flux))
    slope = (right_y - left_y) / (right_x - left_x)
    return left_y + slope * (wave - left_x)


def _robust_scale(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 5:
        return np.nan
    median = np.nanmedian(values)
    scale = 1.4826 * np.nanmedian(np.abs(values - median))
    if not np.isfinite(scale) or scale <= 0:
        scale = np.nanstd(values)
    return float(scale)


def estimate_pew_uncertainty(
    wave: np.ndarray,
    norm: np.ndarray,
    *,
    noise_proxy: np.ndarray | None = None,
    integration_mask: np.ndarray | None = None,
) -> float:
    """Estimate pEW uncertainty from local continuum-normalized noise."""
    wave = np.asarray(wave, dtype=float)
    norm = np.asarray(norm, dtype=float)
    valid = np.isfinite(wave) & np.isfinite(norm)
    if valid.sum() < 8:
        return np.nan

    if noise_proxy is not None:
        proxy = np.asarray(noise_proxy, dtype=float)
        sigma = _robust_scale(proxy[np.isfinite(proxy)])
    else:
        sigma = _robust_scale(np.diff(norm[valid], prepend=norm[valid][0]))
    if not np.isfinite(sigma) or sigma <= 0:
        return np.nan

    if integration_mask is None:
        active = norm < 1.0
    else:
        active = np.asarray(integration_mask, dtype=bool)
    mask = valid & active
    if mask.sum() < 2:
        return np.nan

    order = np.argsort(wave[mask])
    wave_sel = wave[mask][order]
    delta = np.gradient(wave_sel)
    err = sigma * np.sqrt(np.nansum(delta**2))
    return float(err) if np.isfinite(err) and err > 0 else np.nan


def _median_wave_spacing(wave: np.ndarray) -> float:
    values = np.sort(np.asarray(wave, dtype=float)[np.isfinite(wave)])
    if values.size < 2:
        return np.nan
    diffs = np.diff(values)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return np.nan
    return float(np.nanmedian(diffs))


def _linear_crossing(x1: float, y1: float, x2: float, y2: float, level: float) -> float:
    if not all(np.isfinite(v) for v in [x1, y1, x2, y2, level]) or y1 == y2:
        return float(x2)
    frac = (level - y1) / (y2 - y1)
    frac = float(np.clip(frac, 0.0, 1.0))
    return float(x1 + frac * (x2 - x1))


def estimate_minimum_wavelength_uncertainty(
    wave: np.ndarray,
    norm: np.ndarray,
    min_index: int,
    *,
    noise_sigma: float = np.nan,
) -> float:
    """Conservative uncertainty for a trough minimum selected from sampled data."""
    spacing = _median_wave_spacing(wave)
    floor = 0.5 * spacing if np.isfinite(spacing) and spacing > 0 else np.nan
    if not np.isfinite(noise_sigma) or noise_sigma <= 0:
        return float(floor) if np.isfinite(floor) and floor > 0 else np.nan

    wave = np.asarray(wave, dtype=float)
    norm = np.asarray(norm, dtype=float)
    if min_index < 0 or min_index >= wave.size or not np.isfinite(norm[min_index]):
        return float(floor) if np.isfinite(floor) and floor > 0 else np.nan

    threshold = norm[min_index] + noise_sigma
    active = np.isfinite(norm) & (norm <= threshold)
    if not active[min_index]:
        return float(floor) if np.isfinite(floor) and floor > 0 else np.nan

    left = int(min_index)
    while left > 0 and active[left - 1]:
        left -= 1
    right = int(min_index)
    while right < active.size - 1 and active[right + 1]:
        right += 1

    half_span = 0.5 * abs(float(wave[right]) - float(wave[left]))
    candidates = [value for value in [floor, half_span] if np.isfinite(value) and value > 0]
    return float(max(candidates)) if candidates else np.nan


def estimate_half_depth_width(
    wave: np.ndarray,
    norm: np.ndarray,
    min_index: int,
    depth: float,
) -> tuple[float, float]:
    """Return non-parametric FWHM and a sampling uncertainty estimate."""
    wave = np.asarray(wave, dtype=float)
    norm = np.asarray(norm, dtype=float)
    spacing = _median_wave_spacing(wave)
    width_err = 2.0 * spacing if np.isfinite(spacing) and spacing > 0 else np.nan
    if min_index < 0 or min_index >= wave.size or not np.isfinite(depth) or depth <= 0:
        return np.nan, width_err

    half_level = 1.0 - 0.5 * depth
    if not np.isfinite(half_level) or norm[min_index] > half_level:
        return np.nan, width_err

    left = int(min_index)
    while left > 0 and np.isfinite(norm[left - 1]) and norm[left - 1] <= half_level:
        left -= 1
    if left == 0:
        left_cross = float(wave[left])
    else:
        left_cross = _linear_crossing(wave[left - 1], norm[left - 1], wave[left], norm[left], half_level)

    right = int(min_index)
    while right < norm.size - 1 and np.isfinite(norm[right + 1]) and norm[right + 1] <= half_level:
        right += 1
    if right == norm.size - 1:
        right_cross = float(wave[right])
    else:
        right_cross = _linear_crossing(wave[right], norm[right], wave[right + 1], norm[right + 1], half_level)

    width = right_cross - left_cross
    if not np.isfinite(width) or width <= 0:
        return np.nan, width_err
    return float(width), float(width_err) if np.isfinite(width_err) and width_err > 0 else np.nan


def measure_normalized_absorption_minimum(
    wave: np.ndarray,
    norm: np.ndarray,
    rest: float,
    half_width: float,
    *,
    blue_only: bool = True,
    noise_proxy: np.ndarray | None = None,
) -> dict[str, object]:
    """Measure an absorption trough from the minimum of the normalized profile."""
    base = {
        "fit_method": "minimum_absorption",
        "status": "minimum failed: insufficient valid points",
        "fit_norm": None,
        "fit_params": None,
        "fit_errors": None,
        "fit_center_A": np.nan,
        "fit_center_err_A": np.nan,
        "fit_sigma_A": np.nan,
        "fit_sigma_err_A": np.nan,
        "fit_depth": np.nan,
        "fit_depth_err": np.nan,
        "fit_baseline": np.nan,
        "fit_slope": np.nan,
        "fwhm_A": np.nan,
        "fwhm_err_A": np.nan,
        "extrema_wave_A": np.nan,
        "extrema_depth": np.nan,
    }

    wave = np.asarray(wave, dtype=float)
    norm = np.asarray(norm, dtype=float)
    valid = np.isfinite(wave) & np.isfinite(norm)
    if valid.sum() < 5:
        return base

    wave = wave[valid]
    norm = norm[valid]
    order = np.argsort(wave)
    wave = wave[order]
    norm = norm[order]
    if noise_proxy is not None:
        proxy = np.asarray(noise_proxy, dtype=float)
        proxy = proxy[valid][order] if proxy.shape == valid.shape else proxy
        noise_sigma = _robust_scale(proxy[np.isfinite(proxy)])
    else:
        noise_sigma = _robust_scale(np.diff(norm, prepend=norm[0]))

    if not np.isfinite(half_width) or half_width <= 5.0:
        base["status"] = "minimum failed: invalid half_width"
        return base

    search = wave < rest if blue_only else np.isfinite(wave)
    if search.sum() < 5:
        search = np.isfinite(wave)
    candidates = np.where(search)[0]
    if candidates.size == 0:
        base["status"] = "minimum failed: no candidate absorption trough"
        return base

    min_i = int(candidates[np.nanargmin(norm[candidates])])
    minimum_wave = float(wave[min_i])
    depth = max(0.0, 1.0 - float(norm[min_i]))
    base["extrema_wave_A"] = minimum_wave
    base["extrema_depth"] = depth
    if depth < 0.01:
        base["status"] = "minimum failed: no absorption trough below continuum"
        return base

    center_err = estimate_minimum_wavelength_uncertainty(wave, norm, min_i, noise_sigma=noise_sigma)
    fwhm, fwhm_err = estimate_half_depth_width(wave, norm, min_i, depth)
    depth_err = float(noise_sigma) if np.isfinite(noise_sigma) and noise_sigma > 0 else np.nan
    base.update(
        {
            "status": "ok",
            "fit_center_A": minimum_wave,
            "fit_center_err_A": center_err,
            "fit_depth": depth,
            "fit_depth_err": depth_err,
            "fwhm_A": fwhm,
            "fwhm_err_A": fwhm_err,
        }
    )
    return base


def fit_normalized_absorption_line(
    wave: np.ndarray,
    norm: np.ndarray,
    rest: float,
    half_width: float,
    *,
    blue_only: bool = True,
    noise_proxy: np.ndarray | None = None,
) -> dict[str, object]:
    return measure_normalized_absorption_minimum(
        wave,
        norm,
        rest,
        half_width,
        blue_only=blue_only,
        noise_proxy=noise_proxy,
    )


def estimate_reduced_chi2(
    observed: np.ndarray,
    model: np.ndarray,
    *,
    noise_proxy: np.ndarray | None = None,
    n_params: int = 5,
) -> float:
    if observed is None or model is None:
        return np.nan
    observed = np.asarray(observed, dtype=float)
    model = np.asarray(model, dtype=float)
    mask = np.isfinite(observed) & np.isfinite(model)
    if mask.sum() <= n_params:
        return np.nan

    resid = observed[mask] - model[mask]
    sigma = np.nan
    if noise_proxy is not None:
        proxy = np.asarray(noise_proxy, dtype=float)
        if proxy.shape == observed.shape:
            sigma = _robust_scale(proxy[mask])
        else:
            sigma = _robust_scale(proxy)
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = _robust_scale(resid)
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = np.nanstd(resid)
    if not np.isfinite(sigma) or sigma <= 0:
        return np.nan

    dof = max(int(mask.sum()) - int(n_params), 1)
    return float(np.nansum((resid / sigma) ** 2) / dof)


def format_absorption_line_result(
    line_key: str,
    line: dict[str, object],
    fit: dict[str, object],
    *,
    pEW_A: float,
    pEW_err_A: float = np.nan,
    fit_chi2_red: float = np.nan,
    velocity_sys_kms: float = np.nan,
    pEW_sys_A: float = np.nan,
    FWHM_sys_A: float = np.nan,
    n_systematic_variants: int = 0,
) -> dict[str, object]:
    status = str(fit.get("status", "fit failed: unknown"))
    fit_method = str(fit.get("fit_method", "minimum_absorption"))
    center = parse_float(fit.get("fit_center_A"))
    center_err = parse_float(fit.get("fit_center_err_A"))
    sigma = parse_float(fit.get("fit_sigma_A"))
    sigma_err = parse_float(fit.get("fit_sigma_err_A"))
    depth = parse_float(fit.get("fit_depth", fit.get("fit_depth_A")))
    depth_err = parse_float(fit.get("fit_depth_err"))
    fwhm_direct = parse_float(fit.get("fwhm_A"))
    fwhm_direct_err = parse_float(fit.get("fwhm_err_A"))
    extrema_wave = parse_float(fit.get("extrema_wave_A"))
    extrema_depth = parse_float(fit.get("extrema_depth"))

    if status != "ok" or not np.isfinite(center):
        abs_wave = np.nan
        velocity = np.nan
        velocity_err = np.nan
        fwhm = np.nan
        fwhm_err = np.nan
        depth = np.nan
        depth_err = np.nan
        sigma = np.nan
        sigma_err = np.nan
        fit_chi2_red = np.nan if not np.isfinite(fit_chi2_red) else float(fit_chi2_red)
    else:
        abs_wave = float(center)
        velocity = C_KMS * (line["rest"] - abs_wave) / line["rest"]
        velocity_err = C_KMS * center_err / line["rest"] if np.isfinite(center_err) else np.nan
        fwhm = fwhm_direct if np.isfinite(fwhm_direct) else (2.35482 * sigma if np.isfinite(sigma) else np.nan)
        fwhm_err = fwhm_direct_err if np.isfinite(fwhm_direct_err) else (2.35482 * sigma_err if np.isfinite(sigma_err) else np.nan)

    return {
        "line": line_key,
        "line_label": line["label"],
        "rest_wave": line["rest"],
        "rest_wave_choice": str(line.get("rest_wave_choice", "single_line")),
        "line_blend_note": str(line.get("line_blend_note", "")),
        "fit_method": fit_method,
        "abs_wave": abs_wave,
        "velocity_kms": float(velocity) if np.isfinite(velocity) else np.nan,
        "velocity_err_kms": float(velocity_err) if np.isfinite(velocity_err) else np.nan,
        "velocity_sys_kms": float(velocity_sys_kms) if np.isfinite(velocity_sys_kms) else np.nan,
        "pEW_A": float(pEW_A),
        "pEW_err_A": float(pEW_err_A) if np.isfinite(pEW_err_A) else np.nan,
        "pEW_sys_A": float(pEW_sys_A) if np.isfinite(pEW_sys_A) else np.nan,
        "FWHM_A": float(fwhm) if np.isfinite(fwhm) else np.nan,
        "FWHM_err_A": float(fwhm_err) if np.isfinite(fwhm_err) else np.nan,
        "FWHM_sys_A": float(FWHM_sys_A) if np.isfinite(FWHM_sys_A) else np.nan,
        "n_systematic_variants": int(n_systematic_variants),
        "depth": float(depth) if np.isfinite(depth) else np.nan,
        "fit_center_err_A": float(center_err) if np.isfinite(center_err) else np.nan,
        "fit_sigma_A": float(sigma) if np.isfinite(sigma) else np.nan,
        "fit_sigma_err_A": float(sigma_err) if np.isfinite(sigma_err) else np.nan,
        "fit_depth_err": float(depth_err) if np.isfinite(depth_err) else np.nan,
        "fit_chi2_red": float(fit_chi2_red) if np.isfinite(fit_chi2_red) else np.nan,
        "extrema_wave_A": float(extrema_wave) if np.isfinite(extrema_wave) else np.nan,
        "extrema_depth": float(extrema_depth) if np.isfinite(extrema_depth) else np.nan,
        "status": status,
    }


def _systematic_spread(base_value: object, variant_values: Iterable[object]) -> float:
    values = [parse_float(base_value)]
    values.extend(parse_float(value) for value in variant_values)
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if finite.size < 2:
        return np.nan
    spread = float(np.nanstd(finite, ddof=1)) if finite.size > 2 else float(0.5 * abs(finite[1] - finite[0]))
    return spread if np.isfinite(spread) else np.nan


def measure_absorption_line(
    wave_rest: np.ndarray,
    flux: np.ndarray,
    line_key: str,
    half_width: float = 420.0,
    *,
    smooth_window: int = 21,
    edge_fraction: float = 0.18,
    include_systematics: bool = False,
) -> dict[str, object]:
    line = LINE_LIBRARY[line_key]
    rest = line["rest"]
    mask = (wave_rest > rest - half_width) & (wave_rest < rest + half_width)
    if mask.sum() < 12:
        return format_absorption_line_result(
            line_key,
            line,
            {"status": "outside wavelength range", "fit_method": "minimum_absorption"},
            pEW_A=np.nan,
        )

    wave = np.asarray(wave_rest[mask], dtype=float)
    raw_flux = np.asarray(flux[mask], dtype=float)
    smooth_flux_local = smooth_flux(raw_flux, preferred_window=smooth_window)
    continuum = local_linear_continuum(wave, smooth_flux_local, edge_fraction=edge_fraction)
    valid = np.isfinite(wave) & np.isfinite(raw_flux) & np.isfinite(smooth_flux_local) & np.isfinite(continuum) & (np.abs(continuum) > 0)
    if valid.sum() < 12:
        return format_absorption_line_result(
            line_key,
            line,
            {"status": "bad local continuum", "fit_method": "minimum_absorption"},
            pEW_A=np.nan,
        )

    wave = wave[valid]
    raw_norm = raw_flux[valid] / continuum[valid]
    norm = smooth_flux_local[valid] / continuum[valid]

    absorption = np.clip(1.0 - norm, 0.0, None)
    pew = float(np.trapz(absorption, wave))
    pew_err = estimate_pew_uncertainty(wave, norm, noise_proxy=raw_norm - norm, integration_mask=absorption > 0)
    fit = fit_normalized_absorption_line(
        wave,
        norm,
        rest,
        half_width,
        blue_only=line.get("blue_only", True),
        noise_proxy=raw_norm - norm,
    )
    result = format_absorption_line_result(line_key, line, fit, pEW_A=pew, pEW_err_A=pew_err)
    if include_systematics and result.get("status") == "ok":
        variants = []
        for variant_smooth, variant_edge in ((15, edge_fraction), (29, edge_fraction), (smooth_window, 0.12), (smooth_window, 0.24)):
            if int(variant_smooth) == int(smooth_window) and float(variant_edge) == float(edge_fraction):
                continue
            variant = measure_absorption_line(
                wave_rest,
                flux,
                line_key,
                half_width=half_width,
                smooth_window=variant_smooth,
                edge_fraction=variant_edge,
                include_systematics=False,
            )
            if variant.get("status") == "ok":
                variants.append(variant)
        result["velocity_sys_kms"] = _systematic_spread(result.get("velocity_kms"), [row.get("velocity_kms") for row in variants])
        result["pEW_sys_A"] = _systematic_spread(result.get("pEW_A"), [row.get("pEW_A") for row in variants])
        result["FWHM_sys_A"] = _systematic_spread(result.get("FWHM_A"), [row.get("FWHM_A") for row in variants])
        result["n_systematic_variants"] = len(variants)
    return result


def planck_lambda_angstrom(wave_a: np.ndarray, temperature: float, amplitude: float) -> np.ndarray:
    wave_m = np.asarray(wave_a, dtype=float) * 1e-10
    h = 6.62607015e-34
    c = 2.99792458e8
    k = 1.380649e-23
    exponent = np.clip(h * c / (wave_m * k * temperature), 1e-6, 700)
    b_lambda = (2.0 * h * c**2) / (wave_m**5 * (np.exp(exponent) - 1.0))
    return amplitude * b_lambda


def estimate_blackbody_temperature_error(
    wave: np.ndarray,
    y: np.ndarray,
    params: np.ndarray,
    *,
    n_bootstrap: int = 80,
    seed: int = 2026,
) -> tuple[float, int]:
    """Estimate color-temperature uncertainty with residual bootstrap."""
    wave = np.asarray(wave, dtype=float)
    y = np.asarray(y, dtype=float)
    params = np.asarray(params, dtype=float)
    model = planck_lambda_angstrom(wave, *params)
    valid = np.isfinite(wave) & np.isfinite(y) & np.isfinite(model)
    if valid.sum() < 30:
        return np.nan, 0

    wave = wave[valid]
    y = y[valid]
    model = model[valid]
    residual = y - model
    residual = residual[np.isfinite(residual)]
    if residual.size < 10:
        return np.nan, 0
    residual = residual - np.nanmedian(residual)

    rng = np.random.default_rng(seed)
    values = []
    for _ in range(max(int(n_bootstrap), 20)):
        sample = model + rng.choice(residual, size=model.size, replace=True)
        try:
            boot_params, _ = curve_fit(
                planck_lambda_angstrom,
                wave,
                sample,
                p0=params,
                bounds=([2500.0, 0.0], [25000.0, np.inf]),
                maxfev=10000,
            )
        except Exception:
            continue
        temp = float(boot_params[0])
        if np.isfinite(temp) and 2500.0 < temp < 25000.0:
            values.append(temp)

    if len(values) < 10:
        return np.nan, len(values)
    p16, p84 = np.nanpercentile(values, [16, 84])
    err = 0.5 * (p84 - p16)
    return (float(err) if np.isfinite(err) and err > 0 else np.nan), len(values)


def _blackbody_result(
    *,
    temperature: float = np.nan,
    error: float = np.nan,
    status: str,
    qc_flag: str = "",
    qc_note: str = "",
    n_bootstrap: int = 0,
) -> dict[str, object]:
    return {
        "T_bb_K": float(temperature) if np.isfinite(temperature) else np.nan,
        "T_err_K": float(error) if np.isfinite(error) else np.nan,
        "T_qc_flag": qc_flag,
        "T_qc_note": qc_note,
        "T_err_method": "residual_bootstrap" if n_bootstrap else "",
        "T_err_n_bootstrap": int(n_bootstrap),
        "status": status,
    }


def fit_blackbody_temperature(
    wave_rest: np.ndarray,
    flux: np.ndarray,
    wave_range: tuple[float, float] = (4200.0, 7600.0),
) -> dict[str, object]:
    mask = (
        np.isfinite(wave_rest)
        & np.isfinite(flux)
        & (wave_rest >= wave_range[0])
        & (wave_rest <= wave_range[1])
    )
    if mask.sum() < 30:
        return _blackbody_result(status="insufficient wavelength range")

    wave = np.asarray(wave_rest[mask], dtype=float)
    local_flux = smooth_flux(np.asarray(flux[mask], dtype=float), preferred_window=51)
    if np.nanmedian(local_flux) < 0:
        local_flux = -local_flux
    finite = np.isfinite(local_flux)
    if finite.sum() < 30:
        return _blackbody_result(status="bad flux")

    wave = wave[finite]
    local_flux = local_flux[finite]
    local_flux = local_flux - np.nanpercentile(local_flux, 2)
    scale = np.nanmax(np.abs(local_flux))
    if not np.isfinite(scale) or scale <= 0:
        return _blackbody_result(status="bad flux scale")
    y = local_flux / scale
    try:
        params, cov = curve_fit(
            planck_lambda_angstrom,
            wave,
            y,
            p0=(7000.0, 1e-13),
            bounds=([2500.0, 0.0], [25000.0, np.inf]),
            maxfev=10000,
        )
        t_bb = float(params[0])
        t_err, n_boot = estimate_blackbody_temperature_error(wave, y, params)
        qc_flag = "adopt"
        qc_note = "residual bootstrap uncertainty"
        if t_bb <= 2501.0 or t_bb >= 24999.0:
            qc_flag = "check"
            qc_note = "temperature hit fit boundary"
            t_err = np.nan
        elif not np.isfinite(t_err) or t_err <= 0:
            qc_flag = "check"
            qc_note = "bootstrap uncertainty unavailable"
        return _blackbody_result(
            temperature=t_bb,
            error=t_err,
            status="ok",
            qc_flag=qc_flag,
            qc_note=qc_note,
            n_bootstrap=n_boot,
        )
    except Exception as exc:
        return _blackbody_result(status=f"fit failed: {exc}")


def apply_temperature_context_qc(result: dict[str, object], *, sn_type: object, z: object) -> dict[str, object]:
    """Demote color-temperature proxy rows when context makes physical use unsafe."""
    out = dict(result)
    if out.get("status", "ok") != "ok":
        return out
    notes = [str(out.get("T_qc_note", "")).strip()]
    z_value = parse_float(z)
    family = canonical_sn_type(sn_type)
    if not np.isfinite(z_value):
        out["T_qc_flag"] = "check"
        notes.append("missing redshift; color temperature proxy only")
    if family != "ia":
        out["T_qc_flag"] = "check"
        notes.append("non-Ia continuum proxy; verify calibration before physical use")
    out["T_qc_note"] = "; ".join(note for note in notes if note)
    return out


def load_spectra(project_root: Path, target_overrides: dict[str, dict[str, object]] | None = None) -> tuple[list[dict], pd.DataFrame]:
    data_dir = project_root / "data"
    metadata = load_tns_metadata(data_dir / "tns_public_objects.csv")
    for target, override in (target_overrides or {}).items():
        key = normalize_target_name(target)
        base = metadata.get(key, {})
        base.update(override)
        metadata[key] = base

    fits_paths = sorted(
        p
        for p in data_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {".fits", ".fit", ".fts"}
    )

    spectra: list[dict] = []
    skipped = []
    for path in fits_paths:
        try:
            with fits.open(path, memmap=False) as hdul:
                hdu = hdul[0]
                data = hdu.data
                if data is None or np.asarray(data).ndim != 1:
                    skipped.append({"file": str(path.relative_to(project_root)), "reason": "not 1D spectrum"})
                    continue
                flux = np.asarray(data, dtype=float)
                wave = wavelength_axis_from_header(hdu.header, len(flux))
                if wave is None:
                    skipped.append({"file": str(path.relative_to(project_root)), "reason": "no wavelength WCS"})
                    continue
                target = normalize_target_name(hdu.header.get("OBJECT") or path.parent.name or path.stem.split("_")[0])
                meta = metadata.get(target, {})
                date_obs = parse_datetime(hdu.header.get("DATE-OBS", ""))
                discovery = parse_datetime(meta.get("discoverydate", ""))
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
                        "z": parse_float(meta.get("z")),
                        "type": meta.get("type", ""),
                        "discoverydate": meta.get("discoverydate", ""),
                        "host": meta.get("host", ""),
                        "exptime": parse_float(hdu.header.get("EXPTIME", hdu.header.get("EXPOSURE"))),
                        "telescope": hdu.header.get("TELESCOP", ""),
                        "instrument": hdu.header.get("INSTRUME", ""),
                        "setup": hdu.header.get("FILTER", hdu.header.get("GRISM", "")),
                        "bunit": hdu.header.get("BUNIT", ""),
                    }
                )
        except Exception as exc:
            skipped.append({"file": str(path.relative_to(project_root)), "reason": repr(exc)})

    skipped_df = pd.DataFrame(skipped)
    return spectra, skipped_df


def build_summary(spectra: Iterable[dict]) -> pd.DataFrame:
    rows = []
    for spec in spectra:
        flux = np.asarray(spec["flux"], dtype=float)
        wave = np.asarray(spec["wave"], dtype=float)
        finite = np.isfinite(flux)
        rows.append(
            {
                "target": spec["target"],
                "file": spec["file"],
                "date_obs": spec["date_obs"],
                "phase_days": spec["phase_days"],
                "type": spec["type"],
                "z": spec["z"],
                "host": spec.get("host", ""),
                "n_pix": len(flux),
                "wave_min": np.nanmin(wave),
                "wave_max": np.nanmax(wave),
                "flux_median": np.nanmedian(flux[finite]) if finite.any() else np.nan,
                "exptime": spec["exptime"],
                "instrument": spec["instrument"],
                "setup": spec["setup"],
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["target", "date_obs", "file"]).reset_index(drop=True)


def measure_spectral_features(spectra: Iterable[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    line_rows = []
    bb_rows = []
    for spec in spectra:
        z = spec["z"]
        wave_rest = spec["wave"] / (1.0 + z) if np.isfinite(z) else spec["wave"].copy()
        bb = apply_temperature_context_qc(fit_blackbody_temperature(wave_rest, spec["flux"]), sn_type=spec["type"], z=z)
        base = {
            "target": spec["target"],
            "file": spec["file"],
            "date_obs": spec["date_obs"],
            "phase_days": spec["phase_days"],
            "type": spec["type"],
            "z": z,
        }
        bb_rows.append({**base, **bb})
        for line_key in default_lines_for_type(spec["type"]):
            if line_key not in LINE_LIBRARY:
                continue
            line_rows.append({**base, **measure_absorption_line(wave_rest, spec["flux"], line_key, include_systematics=True)})

    line_df = pd.DataFrame(line_rows)
    bb_df = pd.DataFrame(bb_rows)
    if not line_df.empty:
        line_df = line_df.sort_values(["target", "line", "date_obs", "file"]).reset_index(drop=True)
    if not bb_df.empty:
        bb_df = bb_df.sort_values(["target", "date_obs", "file"]).reset_index(drop=True)
    return line_df, bb_df


def quality_flag_lines(line_df: pd.DataFrame) -> pd.DataFrame:
    if line_df.empty:
        return line_df.copy()
    rows = []
    for _, row in line_df.iterrows():
        flag = "reject"
        notes = []
        if row.get("status") != "ok":
            notes.append(str(row.get("status")))
        else:
            velocity = parse_float(row.get("velocity_kms"))
            fwhm = parse_float(row.get("FWHM_A"))
            depth = parse_float(row.get("depth"))
            pew = parse_float(row.get("pEW_A"))
            z = parse_float(row.get("z"))
            primary = row.get("line") in primary_lines_for_type(row.get("type"))
            if not np.isfinite(z):
                notes.append("missing TNS redshift; quantitative line velocity is not adopted")
            if not primary:
                notes.append("secondary line; use only after visual inspection")
            if not np.isfinite(velocity) or velocity < 1000 or velocity > 26000:
                notes.append("velocity outside conservative sparse-spectrum range")
            if np.isfinite(fwhm) and (fwhm < 20 or fwhm > 520):
                notes.append("FWHM is suspicious for minimum-trough width")
            if not np.isfinite(depth) or depth < 0.05:
                notes.append("line depth is weak")
            if not np.isfinite(pew) or pew <= 0:
                notes.append("pEW is not positive")
            if primary and not notes:
                flag = "adopt"
                notes.append("primary line with conservative automatic checks passed")
            elif row.get("status") == "ok":
                flag = "check"
            else:
                flag = "reject"
        out = row.to_dict()
        out["qc_flag"] = flag
        out["qc_note"] = "; ".join(notes)
        rows.append(out)
    return pd.DataFrame(rows)


def measure_host_lines(spectra: Iterable[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for spec in spectra:
        z = spec["z"]
        for line_name, rest_wave in HOST_LINES.items():
            base = {
                "target": spec["target"],
                "file": spec["file"],
                "date_obs": spec["date_obs"],
                "phase_days": spec["phase_days"],
                "type": spec["type"],
                "z": z,
                "line": line_name,
                "rest_wave": rest_wave,
            }
            if not np.isfinite(z):
                rows.append({**base, "status": "no_redshift", "snr": np.nan, "flux_index": np.nan, "pEW_A": np.nan})
                continue
            wave_rest = spec["wave"] / (1.0 + z)
            flux = smooth_flux(spec["flux"], preferred_window=11)
            if line_name.startswith("NaID"):
                signal_mask = (wave_rest > rest_wave - 8) & (wave_rest < rest_wave + 8)
                side_mask = ((wave_rest > rest_wave - 55) & (wave_rest < rest_wave - 20)) | (
                    (wave_rest > rest_wave + 20) & (wave_rest < rest_wave + 55)
                )
            else:
                signal_mask = (wave_rest > rest_wave - 7) & (wave_rest < rest_wave + 7)
                side_mask = ((wave_rest > rest_wave - 60) & (wave_rest < rest_wave - 18)) | (
                    (wave_rest > rest_wave + 18) & (wave_rest < rest_wave + 60)
                )
            if signal_mask.sum() < 3 or side_mask.sum() < 8:
                rows.append({**base, "status": "outside wavelength range", "snr": np.nan, "flux_index": np.nan, "pEW_A": np.nan})
                continue
            continuum = np.nanmedian(flux[side_mask])
            noise = 1.4826 * np.nanmedian(np.abs(flux[side_mask] - continuum))
            if not np.isfinite(noise) or noise <= 0:
                noise = np.nanstd(flux[side_mask])
            local_wave = wave_rest[signal_mask]
            local_flux = flux[signal_mask] - continuum
            flux_index = float(np.trapz(local_flux, local_wave))
            peak = float(np.nanmax(local_flux)) if not line_name.startswith("NaID") else float(-np.nanmin(local_flux))
            snr = peak / noise if np.isfinite(noise) and noise > 0 else np.nan
            pew = np.nan
            if np.isfinite(continuum) and continuum != 0:
                if line_name.startswith("NaID"):
                    pew = float(np.trapz(np.clip(1.0 - flux[signal_mask] / continuum, 0, None), local_wave))
                else:
                    pew = float(np.trapz(np.clip(flux[signal_mask] / continuum - 1.0, 0, None), local_wave))
            status = "detected" if np.isfinite(snr) and snr >= 3 else "weak/non-detection"
            rows.append({**base, "status": status, "snr": snr, "flux_index": flux_index, "pEW_A": pew})

    line_df = pd.DataFrame(rows)
    return line_df, summarize_host_line_indices(line_df)


def summarize_host_line_indices(line_df: pd.DataFrame) -> pd.DataFrame:
    summary_rows = []
    if not line_df.empty:
        for target, group in line_df.groupby("target"):
            detections = group[group["status"].eq("detected")]
            unique_lines = sorted(detections["line"].dropna().unique())
            ebv = np.nan
            balmer = np.nan
            for _, same_file in detections.groupby("file"):
                halpha = same_file[same_file["line"].eq("Halpha")]["flux_index"]
                hbeta = same_file[same_file["line"].eq("Hbeta")]["flux_index"]
                if not halpha.empty and not hbeta.empty and float(hbeta.iloc[0]) > 0:
                    balmer = float(halpha.iloc[0]) / float(hbeta.iloc[0])
                    if balmer > 2.86:
                        ebv = 2.5 / (3.61 - 2.53) * math.log10(balmer / 2.86)
                    break
            summary_rows.append(
                {
                    "target": target,
                    "n_detected_host_lines": len(detections),
                    "n_detected_host_line_instances": len(detections),
                    "unique_detected_host_lines": len(unique_lines),
                    "detected_lines": ", ".join(unique_lines),
                    "balmer_decrement_Ha_Hb": balmer,
                    "rough_EBV_host_mag": ebv,
                    "host_note": "rough index from SN spectra; verify before physical use",
                }
            )
    return pd.DataFrame(summary_rows).sort_values("target").reset_index(drop=True) if summary_rows else pd.DataFrame()


def build_target_status(summary: pd.DataFrame, line_qc: pd.DataFrame, host_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if summary.empty:
        return pd.DataFrame()
    host_summary = host_summary.set_index("target") if not host_summary.empty else pd.DataFrame()
    for target, group in summary.groupby("target"):
        types = [str(v) for v in group["type"].dropna().unique() if str(v)]
        redshifts = [float(v) for v in group["z"].dropna().unique()]
        adopted = line_qc[(line_qc["target"].eq(target)) & (line_qc["qc_flag"].eq("adopt"))] if not line_qc.empty else pd.DataFrame()
        checked = line_qc[(line_qc["target"].eq(target)) & (line_qc["qc_flag"].eq("check"))] if not line_qc.empty else pd.DataFrame()
        dates = pd.to_datetime(group["date_obs"], errors="coerce")
        phases = pd.to_numeric(group["phase_days"], errors="coerce")
        sn_type = types[0] if types else "Unclassified"
        text = sn_type.lower()
        if "ia" in text:
            analysis = "Ia: compare Si II/Ca II velocity and pEW with BSNIP/CSP."
        elif "ii" in text:
            analysis = "Type II: use Fe II velocity scale; keep Balmer troughs as visual checks before literature comparison."
        elif "ib" in text or "ic" in text:
            analysis = "SE-SN: verify He/O/Ca lines; compare with Modjaz/Liu/Xiang."
        else:
            analysis = "First confirm type/redshift with SNID/DASH/Superfit before science claims."
        hrow = host_summary.loc[target] if target in host_summary.index else {}
        rows.append(
            {
                "target": target,
                "type": sn_type,
                "z": redshifts[0] if redshifts else np.nan,
                "n_spectra": len(group),
                "date_start": dates.min(),
                "date_end": dates.max(),
                "phase_min_days": float(np.nanmin(phases)) if np.isfinite(phases).any() else np.nan,
                "phase_max_days": float(np.nanmax(phases)) if np.isfinite(phases).any() else np.nan,
                "adopted_line_measurements": len(adopted),
                "needs_visual_checks": len(checked),
                "adopted_lines": ", ".join(sorted(adopted["line"].unique())) if not adopted.empty else "",
                "host_lines": hrow.get("detected_lines", "") if isinstance(hrow, pd.Series) else "",
                "rough_EBV_host_mag": hrow.get("rough_EBV_host_mag", np.nan) if isinstance(hrow, pd.Series) else np.nan,
                "recommended_analysis": analysis,
            }
        )
    return pd.DataFrame(rows).sort_values("target").reset_index(drop=True)


def _savefig(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=180, bbox_inches="tight")
    plt.close()
    return path


def _clean_positive_yerr(values: object) -> pd.Series:
    yerr = pd.to_numeric(values, errors="coerce")
    return yerr.where(np.isfinite(yerr) & (yerr > 0))


def _plot_with_optional_errorbar(ax, x, y, *, yerr=None, marker="o", lw=1.2, alpha=1.0, label=""):
    line, = ax.plot(x, y, marker=marker, lw=lw, alpha=alpha, label=label)
    if yerr is not None:
        clean = _clean_positive_yerr(yerr)
        finite = pd.to_numeric(y, errors="coerce").notna() & clean.notna()
        if finite.any():
            ax.errorbar(
                x[finite],
                pd.to_numeric(y, errors="coerce")[finite],
                yerr=clean[finite],
                fmt="none",
                ecolor=line.get_color(),
                elinewidth=1.0,
                capsize=2,
                alpha=alpha,
            )
    return line


def plot_spectral_sequences(spectra: Iterable[dict], fig_dir: Path) -> list[Path]:
    paths = []
    spectra_list = list(spectra)
    for target in sorted({spec["target"] for spec in spectra_list}):
        items = sorted(
            [spec for spec in spectra_list if spec["target"] == target],
            key=lambda item: pd.Timestamp.max if pd.isna(item["date_obs"]) else item["date_obs"],
        )
        plt.figure(figsize=(10, max(3.5, 1.5 + 0.9 * len(items))))
        for i, spec in enumerate(items):
            wave = spec["wave"] / (1.0 + spec["z"]) if np.isfinite(spec["z"]) else spec["wave"]
            flux = smooth_flux(spec["flux"], preferred_window=11)
            finite = np.isfinite(flux)
            scale = np.nanmedian(np.abs(flux[finite])) if finite.any() else 1.0
            if not np.isfinite(scale) or scale == 0:
                scale = 1.0
            phase = spec["phase_days"]
            phase_label = "" if not np.isfinite(phase) else f", +{phase:.1f} d"
            date_label = "" if pd.isna(spec["date_obs"]) else spec["date_obs"].strftime("%Y-%m-%d")
            plt.plot(wave, flux / scale + i * 1.4, lw=0.8, label=f"{date_label}{phase_label}")
        plt.title(f"{target}: rest-frame spectral sequence")
        plt.xlabel("Rest wavelength (Angstrom)")
        plt.ylabel("Scaled flux + offset")
        plt.grid(alpha=0.2)
        plt.legend(fontsize=8)
        paths.append(_savefig(fig_dir / f"spectral_sequence_{target}.png"))
    return paths


def plot_velocity_panel(line_qc: pd.DataFrame, fig_dir: Path) -> Path | None:
    if line_qc.empty:
        return None
    selected = line_qc[line_qc["qc_flag"].isin(["adopt", "check"])].copy()
    selected = selected[np.isfinite(pd.to_numeric(selected["velocity_kms"], errors="coerce"))]
    if selected.empty:
        return None
    targets = sorted(selected["target"].unique())
    fig, axes = plt.subplots(len(targets), 1, figsize=(9, 2.4 * len(targets)), sharex=False)
    if len(targets) == 1:
        axes = [axes]
    for ax, target in zip(axes, targets):
        sub = selected[selected["target"].eq(target)]
        for line, group in sub.groupby("line"):
            group = group.sort_values("phase_days")
            marker = "o" if (group["qc_flag"].eq("adopt")).any() else "s"
            alpha = 1.0 if (group["qc_flag"].eq("adopt")).any() else 0.45
            x = group["phase_days"] if group["phase_days"].notna().any() else pd.to_datetime(group["date_obs"])
            _plot_with_optional_errorbar(
                ax,
                x,
                pd.to_numeric(group["velocity_kms"], errors="coerce"),
                yerr=group.get("velocity_err_kms"),
                marker=marker,
                alpha=alpha,
                label=line,
            )
        ax.set_title(target)
        ax.set_ylabel("Velocity (km/s)")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, ncol=3)
    axes[-1].set_xlabel("Days since discovery")
    return _savefig(fig_dir / "line_velocity_evolution.png")


def plot_pew_panel(line_qc: pd.DataFrame, fig_dir: Path) -> Path | None:
    if line_qc.empty:
        return None
    selected = line_qc[line_qc["qc_flag"].isin(["adopt", "check"])].copy()
    selected = selected[np.isfinite(pd.to_numeric(selected["pEW_A"], errors="coerce"))]
    if selected.empty:
        return None
    plt.figure(figsize=(10, 5))
    for (target, line), group in selected.groupby(["target", "line"]):
        group = group.sort_values("phase_days")
        x = group["phase_days"] if group["phase_days"].notna().any() else pd.to_datetime(group["date_obs"])
        alpha = 1.0 if (group["qc_flag"].eq("adopt")).any() else 0.45
        _plot_with_optional_errorbar(
            plt.gca(),
            x,
            pd.to_numeric(group["pEW_A"], errors="coerce"),
            yerr=group.get("pEW_err_A"),
            marker="o",
            alpha=alpha,
            label=f"{target} {line}",
        )
    plt.title("Pseudo-equivalent width checks")
    plt.xlabel("Days since discovery")
    plt.ylabel("pEW (Angstrom)")
    plt.grid(alpha=0.25)
    plt.legend(fontsize=7, ncol=2)
    return _savefig(fig_dir / "pew_evolution.png")


def plot_blackbody(bb_df: pd.DataFrame, fig_dir: Path) -> Path | None:
    ok = bb_df[bb_df["status"].eq("ok")].copy() if not bb_df.empty else pd.DataFrame()
    if ok.empty:
        return None
    ok["phase_days"] = pd.to_numeric(ok.get("phase_days", pd.Series(dtype=float)), errors="coerce")
    phased = ok[ok["phase_days"].notna()].copy()
    use_phase_axis = not phased.empty
    plot_table = phased if use_phase_axis else ok
    if not use_phase_axis:
        plot_table["date_obs"] = pd.to_datetime(plot_table.get("date_obs", pd.Series(dtype=object)), errors="coerce")
        plot_table = plot_table[plot_table["date_obs"].notna()].copy()
    if plot_table.empty:
        return None
    plt.figure(figsize=(9, 5))
    for target, group in plot_table.groupby("target"):
        group = group.sort_values("phase_days" if use_phase_axis else "date_obs")
        x = group["phase_days"] if use_phase_axis else group["date_obs"]
        _plot_with_optional_errorbar(
            plt.gca(),
            x,
            pd.to_numeric(group["T_bb_K"], errors="coerce"),
            yerr=group.get("T_err_K"),
            marker="o",
            label=target,
        )
    plt.title("Continuum color-temperature estimate")
    plt.xlabel("Days since discovery" if use_phase_axis else "Observation date")
    plt.ylabel("Blackbody temperature (K)")
    plt.grid(alpha=0.25)
    plt.legend(fontsize=8)
    return _savefig(fig_dir / "blackbody_temperature.png")


def plot_target_status(target_status: pd.DataFrame, fig_dir: Path) -> Path | None:
    if target_status.empty:
        return None
    table_cols = ["target", "type", "n_spectra", "phase_min_days", "phase_max_days", "adopted_lines"]
    table = target_status[table_cols].copy()
    for col in ["phase_min_days", "phase_max_days"]:
        table[col] = table[col].map(lambda v: "" if not np.isfinite(v) else f"{v:.1f}")
    fig, ax = plt.subplots(figsize=(11, 0.8 + 0.45 * len(table)))
    ax.axis("off")
    mpl_table = ax.table(cellText=table.values, colLabels=table.columns, loc="center", cellLoc="left")
    mpl_table.auto_set_font_size(False)
    mpl_table.set_fontsize(8)
    mpl_table.scale(1, 1.35)
    ax.set_title("Target status and adopted diagnostics", pad=16)
    return _savefig(fig_dir / "target_status_table.png")


def plot_host_summary(host_summary: pd.DataFrame, fig_dir: Path) -> Path | None:
    if host_summary.empty:
        return None
    count_col = "unique_detected_host_lines" if "unique_detected_host_lines" in host_summary.columns else "n_detected_host_lines"
    counts = host_summary.set_index("target")[count_col].sort_index()
    plt.figure(figsize=(8, 4.5))
    plt.bar(counts.index, counts.values, color="#5b7c99")
    plt.title("Host/environment line detections")
    plt.ylabel("Unique detected narrow-line indices" if count_col == "unique_detected_host_lines" else "Detected narrow-line indices")
    plt.xlabel("Target")
    plt.grid(axis="y", alpha=0.25)
    return _savefig(fig_dir / "host_line_detections.png")


def write_markdown_summary(target_status: pd.DataFrame, output_dir: Path) -> Path:
    lines = [
        "# Analysis Pipeline Summary",
        "",
        "This directory is generated by `scripts/build_analysis_products.py`.",
        "",
        "## Scientific scope",
        "",
        "The literature review in `paper/sparse-multi-epoch-sn-spectra/` supports a sparse-spectra strategy: classify each SN, report discovery-date phase unless a reliable peak date is available, measure conservative velocities/pEW/FWHM, compare with public samples, and avoid over-interpreting progenitor physics from 1-3 spectra.",
        "",
        "## Target status",
        "",
    ]
    if target_status.empty:
        lines.append("No spectra were loaded.")
    else:
        cols = ["target", "type", "z", "n_spectra", "adopted_lines", "recommended_analysis"]
        compact = target_status[cols].fillna("")
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for _, row in compact.iterrows():
            lines.append("| " + " | ".join(str(row[col]).replace("\n", " ") for col in cols) + " |")
    path = output_dir / "analysis_summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_all(project_root: Path | str = ".", output_dir: Path | str | None = None) -> dict[str, Path | list[Path]]:
    root = Path(project_root).resolve()
    out_dir = Path(output_dir).resolve() if output_dir is not None else root / "output" / "analysis_pipeline"
    fig_dir = out_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    spectra, skipped = load_spectra(root)
    summary = build_summary(spectra)
    line_df, bb_df = measure_spectral_features(spectra)
    line_qc = quality_flag_lines(line_df)
    host_lines, host_summary = measure_host_lines(spectra)
    target_status = build_target_status(summary, line_qc, host_summary)

    paths: dict[str, Path | list[Path]] = {}
    paths["spectra_summary"] = out_dir / "spectra_summary.csv"
    paths["line_diagnostics_raw"] = out_dir / "line_diagnostics_raw.csv"
    paths["line_diagnostics_qc"] = out_dir / "line_diagnostics_qc.csv"
    paths["blackbody_temperature"] = out_dir / "blackbody_temperature.csv"
    paths["host_environment_lines"] = out_dir / "host_environment_lines.csv"
    paths["host_environment_summary"] = out_dir / "host_environment_summary.csv"
    paths["target_status"] = out_dir / "target_status.csv"
    paths["skipped_fits"] = out_dir / "skipped_fits.csv"

    summary.to_csv(paths["spectra_summary"], index=False)
    line_df.to_csv(paths["line_diagnostics_raw"], index=False)
    line_qc.to_csv(paths["line_diagnostics_qc"], index=False)
    bb_df.to_csv(paths["blackbody_temperature"], index=False)
    host_lines.to_csv(paths["host_environment_lines"], index=False)
    host_summary.to_csv(paths["host_environment_summary"], index=False)
    target_status.to_csv(paths["target_status"], index=False)
    skipped.to_csv(paths["skipped_fits"], index=False)

    figure_paths: list[Path] = []
    figure_paths.extend(plot_spectral_sequences(spectra, fig_dir))
    for figure in [
        plot_velocity_panel(line_qc, fig_dir),
        plot_pew_panel(line_qc, fig_dir),
        plot_blackbody(bb_df, fig_dir),
        plot_target_status(target_status, fig_dir),
        plot_host_summary(host_summary, fig_dir),
    ]:
        if figure is not None:
            figure_paths.append(figure)
    paths["figures"] = figure_paths
    paths["summary_md"] = write_markdown_summary(target_status, out_dir)
    return paths
