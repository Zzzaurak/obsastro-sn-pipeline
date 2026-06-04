"""Acceleration settings shared by notebook helper entry points."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, MutableMapping


DEFAULT_ACCELERATION_CONFIG: dict[str, Any] = {
    "profile": "balanced",
    "runtime": {
        "gpu": "auto",
        "cuda_visible_devices": "0",
        "max_workers": "auto",
        "blas_threads_per_worker": 1,
    },
    "superfit": {
        "workers": "auto",
        "rerun_existing": False,
        "z_range": [0.0, 0.08],
        "z_step": 0.005,
        "resolution": 30,
        "how_many_plots": 5,
        "prefer_known_redshift": True,
    },
    "dash": {
        "gpu": "auto",
        "known_z": "auto",
        "rlap_scores": False,
        "top_n": 5,
        "batch_size": "all",
    },
    "tardis": {
        "nthreads": "auto",
        "numba_num_threads": "auto",
        "spectrum_source": "real",
        "montecarlo": {
            "no_of_packets": 50000,
            "iterations": 10,
            "last_no_of_packets": 100000,
            "no_of_virtual_packets": 3,
        },
        "spectrum": {
            "num": 10000,
            "integrated_compute": "Automatic",
            "integrated_points": 1000,
        },
    },
}


def default_acceleration_config() -> dict[str, Any]:
    """Return a mutable copy of the built-in acceleration defaults."""
    return copy.deepcopy(DEFAULT_ACCELERATION_CONFIG)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge nested dictionaries without mutating either input."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_acceleration_config(
    project_root: Path | str | None = None,
    path: Path | str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load ``configs/acceleration.json`` and merge it over defaults."""
    if isinstance(path, dict):
        return deep_merge(DEFAULT_ACCELERATION_CONFIG, path)

    root = Path(project_root or ".")
    config_path = Path(path) if path is not None else root / "configs" / "acceleration.json"
    if not config_path.exists():
        return default_acceleration_config()

    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    return deep_merge(DEFAULT_ACCELERATION_CONFIG, data)


def _is_auto(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() == "auto"


def _optional_int(value: Any) -> int | None:
    if value is None or _is_auto(value):
        return None
    return int(value)


def resolve_worker_count(
    value: Any,
    *,
    total_items: int,
    cpu_count: int | None = None,
    max_workers: int | None = None,
) -> int:
    """Resolve an integer worker count from an explicit value or ``auto``."""
    total = max(1, int(total_items))
    cpu = max(1, int(cpu_count or os.cpu_count() or 1))
    if _is_auto(value):
        workers = max(1, cpu - 2)
    else:
        workers = max(1, int(value))
    if max_workers is not None:
        workers = min(workers, max(1, int(max_workers)))
    return max(1, min(total, workers))


def resolve_runtime_worker_cap(config: dict[str, Any], *, total_items: int) -> int | None:
    runtime = config.get("runtime", {})
    cap = _optional_int(runtime.get("max_workers"))
    if cap is None:
        return None
    return max(1, min(int(total_items), cap))


def resolve_tardis_threads(value: Any, *, cpu_count: int | None = None) -> int:
    """Resolve TARDIS/Numba thread count with a laptop-friendly auto cap."""
    cpu = max(1, int(cpu_count or os.cpu_count() or 1))
    if _is_auto(value):
        return max(1, min(cpu - 2 if cpu > 2 else 1, 8))
    return max(1, int(value))


def normalize_tardis_integrated_compute(value: Any) -> str:
    """Normalize shorthand values to TARDIS' accepted compute enum."""
    text = str(value).strip().lower()
    if text in {"auto", "automatic"}:
        return "Automatic"
    if text == "gpu":
        return "GPU"
    if text == "cpu":
        return "CPU"
    raise ValueError("tardis.spectrum.integrated_compute must be one of Automatic, GPU, or CPU")


def apply_runtime_environment(
    config: dict[str, Any],
    *,
    environ: MutableMapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    """Apply thread/GPU environment variables before heavy imports."""
    env = environ if environ is not None else os.environ
    runtime = config.get("runtime", {})

    gpu = runtime.get("gpu", "auto")
    if gpu is False or (isinstance(gpu, str) and gpu.strip().lower() in {"false", "off", "cpu", "none"}):
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    elif runtime.get("cuda_visible_devices") not in {None, ""}:
        env["CUDA_VISIBLE_DEVICES"] = str(runtime["cuda_visible_devices"])

    blas_threads = str(max(1, int(runtime.get("blas_threads_per_worker", 1))))
    env["OMP_NUM_THREADS"] = blas_threads
    env["OPENBLAS_NUM_THREADS"] = blas_threads
    env["MKL_NUM_THREADS"] = blas_threads

    tardis = config.get("tardis", {})
    env["NUMBA_NUM_THREADS"] = str(resolve_tardis_threads(tardis.get("numba_num_threads", "auto")))
    return env


def apply_tardis_config_overrides(tardis_config: dict[str, Any], acceleration_config: dict[str, Any]) -> dict[str, Any]:
    """Overlay TARDIS runtime knobs onto a generated TARDIS YAML dictionary."""
    settings = acceleration_config.get("tardis", {})
    montecarlo = tardis_config.setdefault("montecarlo", {})
    montecarlo["nthreads"] = resolve_tardis_threads(settings.get("nthreads", "auto"))
    for key in ("no_of_packets", "iterations", "last_no_of_packets", "no_of_virtual_packets"):
        if key in settings.get("montecarlo", {}):
            montecarlo[key] = settings["montecarlo"][key]

    spectrum = tardis_config.setdefault("spectrum", {})
    source = str(settings.get("spectrum_source", "")).strip().lower()
    if source in {"real", "virtual", "integrated"}:
        spectrum["method"] = source
    spectrum_settings = settings.get("spectrum", {})
    if "num" in spectrum_settings:
        spectrum["num"] = int(spectrum_settings["num"])
    integrated = spectrum.setdefault("integrated", {})
    if "integrated_compute" in spectrum_settings:
        integrated["compute"] = normalize_tardis_integrated_compute(spectrum_settings["integrated_compute"])
    if "integrated_points" in spectrum_settings:
        integrated["points"] = int(spectrum_settings["integrated_points"])
    return tardis_config
