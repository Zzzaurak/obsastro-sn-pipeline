"""Create the compact project notebooks used for analysis and reporting.

The repository originally had many exploratory notebooks.  This script writes
four curated notebooks that act as stable entry points while preserving the
legacy notebooks under `notebooks/legacy/`.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = PROJECT_ROOT / "notebooks"


def md(source: str) -> dict:
    cleaned = textwrap.dedent(source).strip()
    return {"cell_type": "markdown", "metadata": {}, "source": cleaned.splitlines(True)}


def code(source: str) -> dict:
    cleaned = textwrap.dedent(source).strip("\n")
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": cleaned.splitlines(True),
    }


def notebook(cells: list[dict]) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python (astro_env)", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def write_notebook(name: str, cells: list[dict]) -> Path:
    NOTEBOOK_DIR.mkdir(parents=True, exist_ok=True)
    path = NOTEBOOK_DIR / name
    path.write_text(json.dumps(notebook(cells), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


OBSERVING_NOTEBOOK = [
    md(
        """
        # 01 Data Collection and Observing Preparation

        This notebook is the stable entry point for target acquisition and observing preparation.  It summarizes the TNS/Lasair/WISeREP workflow from `README.md` and keeps remote downloads opt-in so the notebook can be opened safely during reporting.

        Scientific role: collect candidate metadata, observing windows, finder charts, public spectra, and light curves before the spectral-analysis notebooks interpret the data.
        """
    ),
    code(
        """
        from pathlib import Path
        import json
        import subprocess
        import sys

        import pandas as pd
        from IPython.display import display, Markdown, Image

        PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
        OUTPUT_DIR = PROJECT_ROOT / "output"
        ANALYSIS_DIR = OUTPUT_DIR / "analysis_pipeline"
        CONFIG_PATH = PROJECT_ROOT / "configs" / "sn_parameter.json"
        """
    ),
    md(
        """
        ## Configuration snapshot

        The main observing pipeline uses `configs/sn_parameter.json`.  TNS and Lasair credentials are read from `.env`, which is intentionally not committed.
        """
    ),
    code(
        """
        config = json.loads(CONFIG_PATH.read_text())
        display(config)
        """
    ),
    md(
        """
        ## Optional remote-data refresh

        Keep `RUN_REMOTE_FETCH = False` for normal report work.  Set it to `True` only when you want to refresh TNS, finder charts, Lasair light curves, and WISeREP spectra.
        """
    ),
    code(
        """
        RUN_REMOTE_FETCH = False

        if RUN_REMOTE_FETCH:
            subprocess.run([sys.executable, "scripts/fetch_target_params.py"], cwd=PROJECT_ROOT, check=True)
            subprocess.run([sys.executable, "scripts/fetch_aux_data.py"], cwd=PROJECT_ROOT, check=True)
        else:
            print("Remote refresh skipped. Existing output/ and data/ products are used.")
        """
    ),
    md(
        """
        ## Available target products

        This inventories the generated observing reports, finder charts, light curves, spectra, and model outputs.
        """
    ),
    code(
        """
        products = []
        for path in sorted(OUTPUT_DIR.glob("*")):
            if not path.is_dir() or path.name == "analysis_pipeline":
                continue
            products.append({
                "target": path.name,
                "reports": len(list(path.glob("sn_report_*.txt"))),
                "finder_charts": len(list(path.glob("finder_*"))),
                "lightcurve_files": len(list((path / "lightcurve").glob("*"))) if (path / "lightcurve").exists() else 0,
                "spectra_files": len(list((path / "spectrum").glob("*"))) if (path / "spectrum").exists() else 0,
                "superfit_files": len(list((path / "superfit").glob("*"))) if (path / "superfit").exists() else 0,
                "tardis_files": len(list((path / "tardis").glob("*"))) if (path / "tardis").exists() else 0,
            })
        products_df = pd.DataFrame(products)
        display(products_df)
        """
    ),
    md(
        """
        ## Target status from analysis pipeline

        Run `02_spectral_analysis_pipeline.ipynb` or `scripts/build_analysis_products.py` to update this table.
        """
    ),
    code(
        """
        status_path = ANALYSIS_DIR / "target_status.csv"
        if status_path.exists():
            display(pd.read_csv(status_path))
        else:
            print(f"Missing {status_path}. Run the spectral analysis pipeline first.")
        """
    ),
]


SPECTRAL_NOTEBOOK = [
    md(
        """
        # 02 Spectral Analysis Pipeline

        This notebook replaces the exploratory spectral notebooks with one reproducible pipeline.  It reads calibrated 1-D FITS spectra from `data/`, measures conservative sparse-spectrum diagnostics, writes CSV tables to `output/analysis_pipeline/`, and creates report-ready figures.

        Literature grounding from `paper/sparse-multi-epoch-sn-spectra/`: with 1-3 spectra per object, robust claims should focus on type/subtype checks, spectral phase, velocities, pEW/FWHM, host contamination, and comparison to public samples.  TARDIS remains an interpretive aid, not the primary evidence.
        """
    ),
    code(
        """
        from pathlib import Path
        import sys

        import pandas as pd
        from IPython.display import display, Image, Markdown

        PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
        sys.path.insert(0, str(PROJECT_ROOT))

        from src.spectral_pipeline import build_all

        ANALYSIS_DIR = PROJECT_ROOT / "output" / "analysis_pipeline"
        FIG_DIR = ANALYSIS_DIR / "figures"
        """
    ),
    md("## Run or refresh the analysis products"),
    code(
        """
        RUN_PIPELINE = True

        if RUN_PIPELINE:
            paths = build_all(PROJECT_ROOT)
            print(f"Updated {ANALYSIS_DIR}")
            for item in paths.get("figures", []):
                print(item)
        else:
            print("Using existing output/analysis_pipeline products.")
        """
    ),
    md("## Target-level science status"),
    code(
        """
        target_status = pd.read_csv(ANALYSIS_DIR / "target_status.csv")
        display(target_status)
        """
    ),
    md(
        """
        ## Line diagnostics with quality flags

        `qc_flag=adopt` means the automatic measurement passed conservative checks and is suitable for first-pass plots.  `qc_flag=check` should be inspected visually before any scientific claim.  This prevents over-interpreting noisy minima, broad blends, or secondary lines.
        """
    ),
    code(
        """
        line_qc = pd.read_csv(ANALYSIS_DIR / "line_diagnostics_qc.csv")
        display(line_qc[["target", "date_obs", "phase_days", "type", "line", "velocity_kms", "pEW_A", "FWHM_A", "qc_flag", "qc_note"]])
        """
    ),
    md("## Host/environment diagnostics"),
    code(
        """
        host_summary = pd.read_csv(ANALYSIS_DIR / "host_environment_summary.csv")
        host_lines = pd.read_csv(ANALYSIS_DIR / "host_environment_lines.csv")
        display(host_summary)
        display(host_lines[host_lines["status"].eq("detected")].head(30))
        """
    ),
    md("## Report-ready figures"),
    code(
        """
        for fig in [
            "target_status_table.png",
            "line_velocity_evolution.png",
            "pew_evolution.png",
            "blackbody_temperature.png",
            "host_line_detections.png",
        ]:
            path = FIG_DIR / fig
            if path.exists():
                display(Markdown(f"### {fig}"))
                display(Image(filename=str(path)))
        """
    ),
    md("## Spectral sequences"),
    code(
        """
        for path in sorted(FIG_DIR.glob("spectral_sequence_*.png")):
            display(Markdown(f"### {path.stem.replace('_', ' ')}"))
            display(Image(filename=str(path)))
        """
    ),
]


TARDIS_NOTEBOOK = [
    md(
        """
        # 03 Optional TARDIS Modeling

        This notebook is intentionally narrow.  The literature review says sparse spectra should not be over-modeled; TARDIS is useful here as a line-identification and qualitative shape-comparison tool after classification, phase, and velocity have been checked.

        Run this in the `tardis` environment only when the target has a usable observed spectrum and a generated TARDIS output under `output/<target>/tardis/`.
        """
    ),
    code(
        """
        from pathlib import Path
        import numpy as np
        import matplotlib.pyplot as plt
        from IPython.display import display

        PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
        TARGET = "SN2026jlm"
        OUTPUT_DIR = PROJECT_ROOT / "output" / TARGET
        SPECTRUM_DIR = OUTPUT_DIR / "spectrum"
        TARDIS_DIR = OUTPUT_DIR / "tardis"
        """
    ),
    md("## Load observed and simulated spectra"),
    code(
        """
        observed_files = sorted(SPECTRUM_DIR.glob("*.dat"))
        simulated_files = sorted(TARDIS_DIR.glob("tardis_spectrum_*.dat"))

        if not observed_files:
            raise FileNotFoundError(f"No observed *.dat spectra in {SPECTRUM_DIR}")
        if not simulated_files:
            raise FileNotFoundError(f"No TARDIS spectra in {TARDIS_DIR}")

        observed_path = observed_files[0]
        simulated_path = simulated_files[0]
        obs = np.loadtxt(observed_path)
        sim = np.loadtxt(simulated_path)

        wave_obs, flux_obs = obs[:, 0], obs[:, 1]
        wave_sim, flux_sim = sim[:, 0], sim[:, 1]

        print(f"Observed:  {observed_path}")
        print(f"Simulated: {simulated_path}")
        """
    ),
    md("## Normalize and compare shapes"),
    code(
        """
        def normalize(flux):
            finite = np.isfinite(flux)
            scale = np.nanpercentile(np.abs(flux[finite]), 95) if finite.any() else 1.0
            return flux / scale if scale else flux

        plt.figure(figsize=(10, 5))
        plt.plot(wave_obs, normalize(flux_obs), lw=0.9, label="Observed WISeREP/BFOSC spectrum")
        plt.plot(wave_sim, normalize(flux_sim), lw=0.9, label="TARDIS synthetic spectrum")
        plt.xlim(3500, 9000)
        plt.xlabel("Rest wavelength (Angstrom)")
        plt.ylabel("Normalized flux / luminosity density")
        plt.title(f"{TARGET}: qualitative TARDIS comparison")
        plt.grid(alpha=0.25)
        plt.legend()
        plt.show()
        """
    ),
    md(
        """
        ## Interpretation boundary

        Use this comparison to discuss whether the model broadly matches line locations or continuum shape.  Do not claim strong ejecta mass, explosion energy, or abundance constraints from one sparse spectrum without additional modeling and uncertainties.
        """
    ),
]


REPORT_NOTEBOOK = [
    md(
        """
        # 04 Project Report Notebook

        This notebook is a compact P2Rp2-style report and a source for final-presentation figures.  It follows the course prompts: scientific question, data collected, reduction/analysis, modeling/interpretation, conclusions, and contribution notes.
        """
    ),
    code(
        """
        from pathlib import Path
        import pandas as pd
        from IPython.display import display, Image, Markdown

        PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
        ANALYSIS_DIR = PROJECT_ROOT / "output" / "analysis_pipeline"
        FIG_DIR = ANALYSIS_DIR / "figures"

        target_status = pd.read_csv(ANALYSIS_DIR / "target_status.csv")
        line_qc = pd.read_csv(ANALYSIS_DIR / "line_diagnostics_qc.csv")
        host_summary = pd.read_csv(ANALYSIS_DIR / "host_environment_summary.csv")
        bb = pd.read_csv(ANALYSIS_DIR / "blackbody_temperature.csv")
        """
    ),
    md(
        """
        ## Scientific question

        With a small sample of newly observed supernovae and only one to four optical spectra per target, what reliable spectroscopic information can we extract?  The defensible goals are to verify type/subtype, estimate phase, measure key line velocities and pEW/FWHM where robust, identify host contamination or narrow host lines, and place each object in the context of public SN spectroscopy samples.
        """
    ),
    md(
        """
        ## Data collected

        The project combines TNS metadata and finder charts, Lasair/ZTF light curves when available, WISeREP public spectra, and local BFOSC one-dimensional spectra under `data/SN*/`.  The analysis products below are generated by `scripts/build_analysis_products.py`.
        """
    ),
    code("display(target_status)"),
    md(
        """
        ## Reduction and analysis

        The compact pipeline reads calibrated one-dimensional FITS spectra, applies rest-frame correction using TNS redshift when available, measures sparse-spectrum diagnostics for type-appropriate lines, and assigns conservative quality flags.  Automatic measurements flagged `check` are kept for transparency but should not be used as final numbers before visual inspection.
        """
    ),
    code(
        """
        adopted = line_qc[line_qc["qc_flag"].eq("adopt")].copy()
        display(adopted[["target", "date_obs", "phase_days", "type", "line", "velocity_kms", "pEW_A", "FWHM_A"]])
        """
    ),
    md("## Key figures"),
    code(
        """
        for fig in [
            "target_status_table.png",
            "line_velocity_evolution.png",
            "pew_evolution.png",
            "blackbody_temperature.png",
            "host_line_detections.png",
        ]:
            path = FIG_DIR / fig
            display(Markdown(f"### {fig}"))
            display(Image(filename=str(path)))
        """
    ),
    md(
        """
        ## Modeling and interpretation

        The literature review supports a conservative interpretation.  Type Ia targets should be discussed through Si II/Ca II velocities and pEW compared with BSNIP/CSP/Branch-like samples.  Type II targets should emphasize Fe II and Balmer velocities in the Gutiérrez/Tsinghua context.  Stripped-envelope candidates should first verify He/O/Ca line IDs before subtype claims.  TARDIS can illustrate line IDs or broad spectral shape, but it is not the primary evidence for progenitor or explosion-parameter claims.
        """
    ),
    code("display(host_summary)"),
    md(
        """
        ## Current conclusions

        - `SN2026FVX` and `SN2026JLM` have Ia-like sparse spectral sequences; Si II 6355 provides the cleanest first-pass velocity measurements.
        - `SN2026KID` is the strongest Type II case; Fe II/H lines and host-line indices should be checked visually before final values are quoted.
        - `SN2026KIE` should be treated as a stripped-envelope target; the subtype should be verified against He/O/Ca diagnostics and template fits.
        - `SN2026LMP` remains unclassified in the current metadata and should not enter strong science conclusions until redshift/type are confirmed.

        These results are presentation-ready as first-pass products, but final report numbers should be based on the adopted measurements plus visual checks.
        """
    ),
    md(
        """
        ## Contribution slide/report placeholder

        Replace this section with group member names before submission.  A clean split is:

        - Target selection and observing preparation.
        - Spectral reduction and FITS inspection.
        - Spectral diagnostics, quality control, and host-environment checks.
        - Literature comparison, report writing, and final presentation.
        """
    ),
]


def main() -> None:
    written = [
        write_notebook("01_data_collection_and_observing.ipynb", OBSERVING_NOTEBOOK),
        write_notebook("02_spectral_analysis_pipeline.ipynb", SPECTRAL_NOTEBOOK),
        write_notebook("03_tardis_modeling_optional.ipynb", TARDIS_NOTEBOOK),
        write_notebook("04_project_report.ipynb", REPORT_NOTEBOOK),
    ]
    print("Wrote notebooks:")
    for path in written:
        print(f"- {path}")


if __name__ == "__main__":
    main()
