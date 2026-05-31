"""Create slide-specific figures under ppt/figures."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib"))

import matplotlib

matplotlib.use("Agg")

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = PROJECT_ROOT / "output" / "analysis_pipeline"
ANALYSIS_FIG_DIR = ANALYSIS_DIR / "figures"
PPT_DIR = PROJECT_ROOT / "ppt"
FIG_DIR = PPT_DIR / "figures"


def normalize_flux(flux: np.ndarray) -> np.ndarray:
    finite = np.isfinite(flux)
    if not finite.any():
        return flux
    scale = np.nanpercentile(np.abs(flux[finite]), 95)
    return flux / scale if np.isfinite(scale) and scale else flux


def savefig(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=180, bbox_inches="tight")
    plt.close()
    return path


def copy_pipeline_figures() -> list[Path]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in ANALYSIS_FIG_DIR.glob("*.png"):
        dest = FIG_DIR / source.name
        shutil.copyfile(source, dest)
        copied.append(dest)
    return copied


def build_analysis_flow() -> Path:
    steps = [
        ("TNS + finder charts", "Target metadata\\nobservability windows"),
        ("BFOSC / WISeREP spectra", "Calibrated 1-D spectra\\npublic comparison spectra"),
        ("Sparse-spectrum pipeline", "Type-aware line velocities\\npEW / FWHM / color T"),
        ("Quality control", "Adopt / check / reject\\nhost-line flags"),
        ("Report + slides", "Scientific claims\\nwith literature limits"),
    ]
    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.axis("off")
    x_positions = np.linspace(0.08, 0.92, len(steps))
    for i, ((title, body), x) in enumerate(zip(steps, x_positions)):
        rect = plt.Rectangle((x - 0.085, 0.38), 0.17, 0.36, fc="#eef3f7", ec="#2b4c63", lw=1.2)
        ax.add_patch(rect)
        ax.text(x, 0.63, title, ha="center", va="center", fontsize=10, fontweight="bold")
        ax.text(x, 0.49, body, ha="center", va="center", fontsize=8)
        if i < len(steps) - 1:
            ax.annotate(
                "",
                xy=(x_positions[i + 1] - 0.095, 0.56),
                xytext=(x + 0.095, 0.56),
                arrowprops=dict(arrowstyle="->", lw=1.5, color="#2b4c63"),
            )
    ax.set_title("Analysis workflow for sparse multi-epoch supernova spectra", fontsize=13, pad=12)
    return savefig(FIG_DIR / "analysis_flow.png")


def build_target_table_figure() -> Path:
    status = pd.read_csv(ANALYSIS_DIR / "target_status.csv")
    cols = ["target", "type", "z", "n_spectra", "phase_min_days", "phase_max_days", "adopted_lines"]
    table = status[cols].copy()
    for col in ["z", "phase_min_days", "phase_max_days"]:
        table[col] = table[col].map(lambda x: "" if pd.isna(x) else f"{x:.4g}")
    fig, ax = plt.subplots(figsize=(11, 2.8))
    ax.axis("off")
    mpl_table = ax.table(cellText=table.values, colLabels=table.columns, cellLoc="left", loc="center")
    mpl_table.auto_set_font_size(False)
    mpl_table.set_fontsize(8)
    mpl_table.scale(1.0, 1.4)
    ax.set_title("Observed targets and first-pass spectral status", pad=14)
    return savefig(FIG_DIR / "slide_target_status.png")


def build_spectral_montage() -> Path:
    sequence_paths = sorted(ANALYSIS_FIG_DIR.glob("spectral_sequence_*.png"))
    if not sequence_paths:
        raise FileNotFoundError("No spectral sequence figures found. Run scripts/build_analysis_products.py first.")
    n = len(sequence_paths)
    ncols = 2
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(11, 3.2 * nrows))
    axes = np.atleast_1d(axes).ravel()
    for ax, path in zip(axes, sequence_paths):
        ax.imshow(mpimg.imread(path))
        ax.set_title(path.stem.replace("spectral_sequence_", ""), fontsize=10)
        ax.axis("off")
    for ax in axes[len(sequence_paths) :]:
        ax.axis("off")
    fig.suptitle("Rest-frame spectral sequences (credit: group pipeline output)", fontsize=13)
    return savefig(FIG_DIR / "spectral_sequence_montage.png")


def build_tardis_comparison() -> Path | None:
    for target in ["SN2026jlm", "SN2026kie"]:
        spectrum_dir = PROJECT_ROOT / "output" / target / "spectrum"
        tardis_dir = PROJECT_ROOT / "output" / target / "tardis"
        observed_files = sorted(spectrum_dir.glob("*.dat"))
        tardis_files = sorted(tardis_dir.glob("tardis_spectrum_*.dat"))
        if not observed_files or not tardis_files:
            continue
        observed = np.loadtxt(observed_files[0])
        simulated = np.loadtxt(tardis_files[0])
        wave_obs, flux_obs = observed[:, 0], normalize_flux(observed[:, 1])
        wave_sim, flux_sim = simulated[:, 0], normalize_flux(simulated[:, 1])
        plt.figure(figsize=(9.5, 4.8))
        plt.plot(wave_obs, flux_obs, lw=0.9, label="Observed spectrum")
        plt.plot(wave_sim, flux_sim, lw=0.9, label="TARDIS synthetic spectrum")
        plt.xlim(3500, 9000)
        plt.xlabel("Rest wavelength (Angstrom)")
        plt.ylabel("Normalized flux / luminosity density")
        plt.title(f"{target.upper()}: qualitative TARDIS comparison")
        plt.grid(alpha=0.25)
        plt.legend()
        return savefig(FIG_DIR / f"tardis_comparison_{target.upper()}.png")
    return None


def main() -> None:
    copied = copy_pipeline_figures()
    made = [
        build_analysis_flow(),
        build_target_table_figure(),
        build_spectral_montage(),
    ]
    tardis = build_tardis_comparison()
    if tardis is not None:
        made.append(tardis)
    print("Presentation figures:")
    for path in copied + made:
        print(f"- {path}")


if __name__ == "__main__":
    main()
