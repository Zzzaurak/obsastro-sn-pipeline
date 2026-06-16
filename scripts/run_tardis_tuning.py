#!/usr/bin/env python
"""Run bounded TARDIS parameter searches for the local supernova spectra."""

from __future__ import annotations

import argparse
import math
import sys
import traceback
from pathlib import Path
from typing import Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import spectral_notebook_tools as snt
from src import tardis_tuning as tt
from src.acceleration_config import apply_runtime_environment, load_acceleration_config, resolve_tardis_threads


def parse_float_list(value: str) -> list[float]:
    try:
        return [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="project root directory")
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="target to run; repeat for multiple targets; default runs the four configured targets",
    )
    parser.add_argument("--spectrum-index", type=int, default=0, help="observed spectrum index selected per target")
    parser.add_argument("--max-candidates", type=int, default=12, help="maximum candidates per target")
    parser.add_argument("--packet-scale", choices=["quick", "final"], default="quick", help="Monte Carlo packet profile")
    parser.add_argument("--reuse-existing", action="store_true", help="reuse candidate spectra already on disk")
    parser.add_argument("--adopt-best", action="store_true", help="copy each target's best result into configs/tardis and output/<target>/tardis")
    parser.add_argument(
        "--run-label",
        default="",
        help="optional label appended to output/tardis_tuning/<target> to keep exploratory runs separate",
    )
    parser.add_argument(
        "--include-model-resources",
        action="store_true",
        help="include CSVY model resources from data/tardis_models for Type Ia targets",
    )
    parser.add_argument(
        "--model-resource-only",
        action="store_true",
        help="run only CSVY model-resource candidates; implies --include-model-resources",
    )
    parser.add_argument(
        "--luminosity-offsets",
        type=parse_float_list,
        default=[0.0, -0.35, 0.35],
        help="comma-separated log_lsun offsets around the seed value",
    )
    parser.add_argument(
        "--epoch-offsets",
        type=parse_float_list,
        default=[0.0, -6.0, 6.0],
        help="comma-separated day offsets around the seed time_explosion",
    )
    parser.add_argument(
        "--velocity-scales",
        type=parse_float_list,
        default=[1.0, 0.85, 1.15],
        help="comma-separated multiplicative velocity-boundary scales",
    )
    return parser.parse_args(argv)


def safe_label(value: str) -> str:
    text = str(value or "").strip()
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text).strip("_")


def tuning_target_dir(project_root: Path, target: str, run_label: str = "") -> Path:
    suffix = safe_label(run_label)
    name = target if not suffix else f"{target}__{suffix}"
    return project_root / "output" / "tardis_tuning" / name


def selected_epoch_days(context: dict[str, object]) -> float:
    family = str(context.get("sn_family", "Ia"))
    rise_default = {"Ia": 18.0, "II": 15.0, "Ibc": 15.0}.get(family, 15.0)
    spectrum = context.get("spectrum", {})
    phase = np.nan
    if isinstance(spectrum, dict):
        try:
            phase = float(spectrum.get("phase_days", np.nan))
        except (TypeError, ValueError):
            phase = np.nan
    if np.isfinite(phase):
        return max(5.0, float(phase) + rise_default)
    try:
        return max(5.0, float(context.get("epoch_days", rise_default)))
    except (TypeError, ValueError):
        return rise_default


def seed_from_context(context: dict[str, object]) -> tt.TargetSeed:
    spectrum = context.get("spectrum", {})
    if not isinstance(spectrum, dict):
        raise ValueError("context does not contain a selected spectrum")
    return tt.TargetSeed(
        target=tt.canonical_target(context.get("target")),
        sn_type=str(context.get("sn_type", "")),
        sn_family=str(context.get("sn_family", "Ia")),
        z=float(context.get("z", np.nan)),
        spectrum_file=str(spectrum.get("file", "")),
        log_lsun=float(context.get("log_lsun", np.nan)),
        time_explosion_days=selected_epoch_days(context),
        v_start_kms=float(context.get("v_start_kms", np.nan)),
        v_stop_kms=float(context.get("v_stop_kms", np.nan)),
    )


def observed_rest_spectrum(context: dict[str, object]) -> tuple[np.ndarray, np.ndarray]:
    spectrum = context.get("spectrum", {})
    if not isinstance(spectrum, dict):
        raise ValueError("context does not contain a selected spectrum")
    wave = np.asarray(spectrum["wave"], dtype=float)
    flux = np.asarray(spectrum["flux"], dtype=float)
    z = float(context.get("z", np.nan))
    if np.isfinite(z):
        wave = wave / (1.0 + z)
    return wave, flux


def extract_tardis_arrays(sim) -> tuple[np.ndarray, np.ndarray]:
    for attr in ("spectrum_integrated", "spectrum_virtual_packets", "spectrum_real_packets"):
        spectrum = getattr(sim.spectrum_solver, attr, None)
        if spectrum is None:
            continue
        wave = np.asarray(spectrum.wavelength.value, dtype=float)
        flux = np.asarray(spectrum.luminosity_density_lambda.value, dtype=float)
        finite = np.isfinite(wave) & np.isfinite(flux)
        if finite.sum() < 2:
            continue
        wave = wave[finite]
        flux = flux[finite]
        order = np.argsort(wave)
        return wave[order], flux[order]
    raise ValueError("simulation does not expose a finite extractable TARDIS spectrum")


def run_tardis_config(config_path: Path) -> tuple[np.ndarray, np.ndarray]:
    from tardis import run_tardis

    try:
        sim = run_tardis(
            str(config_path),
            show_convergence_plots=False,
            log_level="WARNING",
            show_progress_bars=False,
        )
    except TypeError:
        sim = run_tardis(str(config_path), show_convergence_plots=False, log_level="WARNING")
    return extract_tardis_arrays(sim)


def candidate_paths(target_dir: Path, candidate: tt.TardisCandidate) -> tuple[Path, Path, Path]:
    config_path = target_dir / "candidates" / f"{candidate.candidate_id}.yml"
    spectrum_path = target_dir / "candidates" / f"{candidate.candidate_id}.dat"
    plot_path = target_dir / "figures" / f"{candidate.candidate_id}_comparison.png"
    return config_path, spectrum_path, plot_path


def score_and_plot_candidate(
    *,
    target: str,
    candidate: tt.TardisCandidate,
    obs_wave: np.ndarray,
    obs_flux: np.ndarray,
    sim_wave: np.ndarray,
    sim_flux: np.ndarray,
    line_windows: Iterable[tt.LineWindow],
    plot_path: Path,
) -> tt.ScoreResult:
    score = tt.score_spectra(obs_wave, obs_flux, sim_wave, sim_flux, line_windows=line_windows)
    tt.plot_comparison(
        target=target,
        candidate=candidate,
        obs_wave=obs_wave,
        obs_flux=obs_flux,
        sim_wave=sim_wave,
        sim_flux=sim_flux,
        line_windows=line_windows,
        score=score,
        output_path=plot_path,
    )
    return score


def row_for_candidate(
    *,
    seed: tt.TargetSeed,
    candidate: tt.TardisCandidate,
    status: str,
    score: tt.ScoreResult | None,
    config_path: Path,
    spectrum_path: Path,
    plot_path: Path,
    error: str = "",
) -> dict[str, object]:
    score_row = score.as_row() if score is not None else {}
    return {
        "target": seed.target,
        "sn_type": seed.sn_type,
        "sn_family": seed.sn_family,
        "z": seed.z,
        "spectrum_file": seed.spectrum_file,
        "candidate_id": candidate.candidate_id,
        "status": status,
        "total_score": score_row.get("total_score", math.inf),
        "broad_rmse": score_row.get("broad_rmse", math.inf),
        "line_rmse": score_row.get("line_rmse", math.inf),
        "corr_penalty": score_row.get("corr_penalty", math.inf),
        "min_offset_A": score_row.get("min_offset_A", math.inf),
        "n_points": score_row.get("n_points", 0),
        "n_line_points": score_row.get("n_line_points", 0),
        "log_lsun": candidate.log_lsun,
        "time_explosion_days": candidate.time_explosion_days,
        "v_start_kms": candidate.v_start_kms,
        "v_stop_kms": candidate.v_stop_kms,
        "density_profile": candidate.density_profile,
        "abundance_preset": candidate.abundance_preset,
        "model_resource": candidate.model_resource or "",
        "config_path": str(config_path),
        "spectrum_path": str(spectrum_path),
        "plot_path": str(plot_path),
        "error": error,
    }


def run_target(
    *,
    project_root: Path,
    target: str,
    spectrum_index: int,
    max_candidates: int,
    packet_scale: str,
    reuse_existing: bool,
    adopt_best: bool,
    nthreads: int,
    luminosity_offsets: list[float],
    epoch_offsets: list[float],
    velocity_scales: list[float],
    include_model_resources: bool,
    model_resource_only: bool,
    run_label: str,
) -> dict[str, object]:
    context = snt.estimate_tardis_context(project_root, target, spectrum_index=spectrum_index)
    seed = seed_from_context(context)
    obs_wave, obs_flux = observed_rest_spectrum(context)
    line_windows = tt.line_windows_for_family(seed.sn_family)
    target_dir = tuning_target_dir(project_root, seed.target, run_label)
    scores_path = target_dir / "scores.csv"
    use_model_resources = include_model_resources or model_resource_only
    model_resources = tt.available_model_resources(project_root, seed.sn_family) if use_model_resources else []
    if model_resource_only and not model_resources:
        raise RuntimeError(f"no model resources available for {seed.target} family={seed.sn_family}")
    candidates = tt.generate_candidates(
        seed,
        luminosity_offsets=luminosity_offsets,
        epoch_offsets=epoch_offsets,
        velocity_scales=velocity_scales,
        abundance_presets=[] if model_resource_only else None,
        density_profiles=[] if model_resource_only else None,
        model_resources=model_resources,
        max_candidates=max_candidates,
    )
    rows: list[dict[str, object]] = []
    print(f"\n[{seed.target}] selected spectrum: {seed.spectrum_file}")
    print(
        f"[{seed.target}] seed: family={seed.sn_family} z={seed.z:.6g} "
        f"L={seed.log_lsun:.2f} t={seed.time_explosion_days:.1f} "
        f"v={seed.v_start_kms:.0f}-{seed.v_stop_kms:.0f} km/s"
    )
    if model_resources:
        print(f"[{seed.target}] model resources: {', '.join(model_resources)}")
    for candidate in candidates:
        config_path, spectrum_path, plot_path = candidate_paths(target_dir, candidate)
        try:
            config = tt.build_tardis_config(candidate, project_root=project_root, packet_scale=packet_scale, nthreads=nthreads)
            tt.write_yaml(config_path, config)
            if reuse_existing and spectrum_path.exists():
                sim_wave, sim_flux = tt.read_spectrum(spectrum_path)
            else:
                print(f"[{seed.target}] running {candidate.candidate_id}")
                sim_wave, sim_flux = run_tardis_config(config_path)
                tt.save_spectrum(spectrum_path, sim_wave, sim_flux)
            score = score_and_plot_candidate(
                target=seed.target,
                candidate=candidate,
                obs_wave=obs_wave,
                obs_flux=obs_flux,
                sim_wave=sim_wave,
                sim_flux=sim_flux,
                line_windows=line_windows,
                plot_path=plot_path,
            )
            row = row_for_candidate(
                seed=seed,
                candidate=candidate,
                status="ok",
                score=score,
                config_path=config_path,
                spectrum_path=spectrum_path,
                plot_path=plot_path,
            )
            print(f"[{seed.target}] {candidate.candidate_id} score={score.total_score:.3f}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            print(f"[{seed.target}] {candidate.candidate_id} failed: {error}", file=sys.stderr)
            traceback.print_exc()
            config_path, spectrum_path, plot_path = candidate_paths(target_dir, candidate)
            row = row_for_candidate(
                seed=seed,
                candidate=candidate,
                status="failed",
                score=None,
                config_path=config_path,
                spectrum_path=spectrum_path,
                plot_path=plot_path,
                error=error,
            )
        rows.append(row)
        tt.append_scores(scores_path, rows)

    ok_rows = [row for row in rows if row.get("status") == "ok" and np.isfinite(float(row.get("total_score", math.inf)))]
    if not ok_rows:
        raise RuntimeError(f"all candidates failed for {seed.target}")
    best = min(ok_rows, key=lambda row: float(row["total_score"]))
    best_config = Path(str(best["config_path"]))
    best_spectrum = Path(str(best["spectrum_path"]))
    best_plot = Path(str(best["plot_path"]))
    shutil_paths = {
        "best_config": target_dir / "best_config.yml",
        "best_spectrum": target_dir / "best_spectrum.dat",
        "best_plot": target_dir / "best_comparison.png",
    }
    for src, dst in [(best_config, shutil_paths["best_config"]), (best_spectrum, shutil_paths["best_spectrum"]), (best_plot, shutil_paths["best_plot"])]:
        dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(src, dst)
    summary_path = target_dir / "best_summary.json"
    summary = dict(best)
    summary.update({key: str(value) for key, value in shutil_paths.items()})
    tt.write_best_summary(summary_path, summary)
    print(f"[{seed.target}] best={best['candidate_id']} score={float(best['total_score']):.3f}")

    if adopt_best:
        adopted = tt.copy_best_outputs(
            target=seed.target,
            project_root=project_root,
            best_config=shutil_paths["best_config"],
            best_spectrum=shutil_paths["best_spectrum"],
            best_plot=shutil_paths["best_plot"],
        )
        print(f"[{seed.target}] adopted config: {adopted['config']}")

    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root).resolve()
    acceleration = load_acceleration_config(project_root)
    apply_runtime_environment(acceleration)
    nthreads = resolve_tardis_threads(acceleration.get("tardis", {}).get("nthreads", "auto"))
    targets = [tt.canonical_target(target) for target in args.target] if args.target else list(tt.DEFAULT_TARGETS)
    summaries = []
    for target in targets:
        summaries.append(
            run_target(
                project_root=project_root,
                target=target,
                spectrum_index=args.spectrum_index,
                max_candidates=args.max_candidates,
                packet_scale=args.packet_scale,
                reuse_existing=args.reuse_existing,
                adopt_best=args.adopt_best,
                nthreads=nthreads,
                luminosity_offsets=args.luminosity_offsets,
                epoch_offsets=args.epoch_offsets,
                velocity_scales=args.velocity_scales,
                include_model_resources=args.include_model_resources,
                model_resource_only=args.model_resource_only,
                run_label=args.run_label,
            )
        )
    print("\nBest candidates:")
    for summary in summaries:
        print(
            f"- {summary['target']}: {summary['candidate_id']} "
            f"score={float(summary['total_score']):.3f} "
            f"L={float(summary['log_lsun']):.2f} "
            f"t={float(summary['time_explosion_days']):.1f} "
            f"v={float(summary['v_start_kms']):.0f}-{float(summary['v_stop_kms']):.0f} "
            f"resource={summary.get('model_resource', '') or 'analytic'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
