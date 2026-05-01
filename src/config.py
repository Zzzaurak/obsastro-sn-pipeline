from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import warn

DEFAULT_CONFIG_PATH = Path("config/download_sn_config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "date": "2026-05-08",
    "out_dir": "",
    "mag_limit": 19.0,
    "min_mag": -99.0,
    "min_dec": -25.0,
    "site_lat": 40.0,
    "site_lon": 116.3,
    "site_elevation_m": 50.0,
    "tz_offset": 8.0,
    "min_alt": 30.0,
    "min_visible_hours": 0.5,
    "limit_targets": 0,
    "rank_by": "mag",
    "sun_alt_limit": -12.0,
    "time_step_minutes": 10,
    "recent_days": 45,
    "ztf_subsample": "cantrans",
    "classstring": "",
    "classexclude": "",
    "start_peak_date": "",
    "end_peak_date": "",
    "skip_ztf": False,
    "tns_enabled": True,
    "use_staged_catalog": True,
    "download_tns_object_details": True,
    "download_tns_photometry": True,
    "download_tns_spectra_metadata": True,
    "download_tns_spectra_files": False,
    "max_tns_object_requests_per_run": 25,
    "max_tns_files_per_target": 2,
    "tns_pause_seconds": 6.5,
    "respect_rate_limit_headers": True,
    "no_download_assets": False,
    "download_lc_png": True,
    "download_lasair_object": True,
    "download_lasair_lc": True,
    "download_finder": True,
    "download_spectra": True,
    "spectra_files": "ascii",
    "max_spectra_files": 8,
    "pause": 0.5,
    "overwrite": False,
}

CONFIG_KEY_ALIASES = {
    "max_targets": "limit_targets",
    "target_count": "limit_targets",
    "number": "limit_targets",
    "count": "limit_targets",
    "magnitude_limit": "mag_limit",
    "max_mag": "mag_limit",
    "brightness_limit": "mag_limit",
    "min_declination": "min_dec",
    "output_dir": "out_dir",
    "sort_by": "rank_by",
    "rank": "rank_by",
    "ztf_recent_days": "recent_days",
}


def flatten_config(data: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        normalized = key.replace("-", "_")
        if normalized.startswith("_"):
            continue
        if isinstance(value, dict):
            flat.update(flatten_config(value))
        else:
            flat[CONFIG_KEY_ALIASES.get(normalized, normalized)] = value
    return flat


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"cannot parse boolean value {value!r}")


def coerce_config_value(key: str, value: Any, defaults: dict[str, Any]) -> Any:
    if key not in defaults:
        return value
    default = defaults[key]
    if isinstance(default, bool):
        return parse_bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(value)
    if isinstance(default, float):
        return float(value)
    if isinstance(default, str):
        return "" if value is None else str(value)
    return value


def load_config(path: Path, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    if defaults is None:
        defaults = DEFAULT_CONFIG
    if not path.exists():
        warn(f"Config file not found: {path}; using built-in defaults.")
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        warn(f"Config file is empty: {path}; using built-in defaults.")
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("top-level JSON value must be an object")
    flat = flatten_config(data)
    known: dict[str, Any] = {}
    for key, value in flat.items():
        if key not in defaults:
            warn(f"Ignoring unknown config key: {key}")
            continue
        known[key] = coerce_config_value(key, value, defaults)
    return known
