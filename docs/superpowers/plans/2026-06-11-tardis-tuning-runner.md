# TARDIS Tuning Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a reproducible TARDIS tuning CLI that searches bounded parameter grids for `SN2026FVX`, `SN2026JLM`, `SN2026KID`, and `SN2026KIE`, then writes best configs, spectra, plots, and score tables.

**Architecture:** Put deterministic, testable logic in `src/tardis_tuning.py`; keep the command-line and expensive `run_tardis` calls in `scripts/run_tardis_tuning.py`. Scoring uses smoothed, pseudo-continuum-normalized rest-frame spectra and target-family line windows.

**Tech Stack:** Python 3.10 for tests in `astro_env`; Python 3.13 plus installed TARDIS 2026.5.31 for simulation runs in `tardis`; numpy, pandas, scipy, matplotlib, astropy, PyYAML.

---

## File Structure

- Create `src/tardis_tuning.py`: dataclasses, candidate grid generation, YAML building, spectrum preprocessing, scoring, plotting, and result persistence.
- Create `scripts/run_tardis_tuning.py`: argparse entry point, target loop, TARDIS import/run, and best-candidate copying.
- Create `tests/test_tardis_tuning.py`: unit tests for pure helpers. No TARDIS import.
- Modify `configs/tardis/*.yml`: only after a candidate is selected by the runner.

## Task 1: Unit Tests for Deterministic Helpers

**Files:**
- Create: `tests/test_tardis_tuning.py`

- [ ] **Step 1: Write failing tests**

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from src import tardis_tuning as tt


class TardisTuningTests(unittest.TestCase):
    def test_candidate_grid_applies_offsets_and_limits_count(self) -> None:
        base = tt.TargetSeed(
            target="SNTEST",
            sn_type="SN Ia",
            sn_family="Ia",
            z=0.01,
            spectrum_file="data/SNTEST/spec.fits",
            log_lsun=9.2,
            time_explosion_days=18.0,
            v_start_kms=7000.0,
            v_stop_kms=16000.0,
        )

        candidates = tt.generate_candidates(
            base,
            luminosity_offsets=[0.0, 0.2],
            epoch_offsets=[0.0],
            velocity_scales=[1.0, 1.1],
            abundance_presets=["ia_standard"],
            density_profiles=["branch85_w7"],
            max_candidates=3,
        )

        self.assertEqual([c.candidate_id for c in candidates], ["SNTEST_c000", "SNTEST_c001", "SNTEST_c002"])
        self.assertEqual(candidates[1].log_lsun, 9.2)
        self.assertAlmostEqual(candidates[1].v_start_kms, 7700.0)
        self.assertEqual(candidates[2].log_lsun, 9.4)

    def test_continuum_normalize_recovers_absorption_trough(self) -> None:
        wave = np.linspace(5000.0, 7000.0, 401)
        continuum = 2.0 + 0.0002 * (wave - 6000.0)
        trough = 1.0 - 0.35 * np.exp(-0.5 * ((wave - 6100.0) / 80.0) ** 2)
        normalized = tt.continuum_normalize(wave, continuum * trough, window_pixels=61)

        idx = int(np.argmin(np.abs(wave - 6100.0)))
        self.assertLess(normalized[idx], 0.8)
        self.assertGreater(np.nanmedian(normalized), 0.9)

    def test_score_prefers_matching_trough_position(self) -> None:
        wave = np.linspace(5600.0, 6600.0, 501)
        obs_flux = 1.0 - 0.4 * np.exp(-0.5 * ((wave - 6100.0) / 60.0) ** 2)
        good_flux = 1.0 - 0.35 * np.exp(-0.5 * ((wave - 6110.0) / 65.0) ** 2)
        bad_flux = 1.0 - 0.35 * np.exp(-0.5 * ((wave - 6350.0) / 65.0) ** 2)

        good = tt.score_spectra(
            wave,
            obs_flux,
            wave,
            good_flux,
            line_windows=[tt.LineWindow("SiII6355", 5900.0, 6300.0)],
        )
        bad = tt.score_spectra(
            wave,
            obs_flux,
            wave,
            bad_flux,
            line_windows=[tt.LineWindow("SiII6355", 5900.0, 6300.0)],
        )

        self.assertLess(good.total_score, bad.total_score)
        self.assertLess(good.min_offset_A, bad.min_offset_A)

    def test_build_config_uses_project_atom_data_and_family_preset(self) -> None:
        candidate = tt.TardisCandidate(
            target="SN2026KIE",
            candidate_id="SN2026KIE_c000",
            sn_family="Ibc",
            log_lsun=8.9,
            time_explosion_days=24.0,
            v_start_kms=6000.0,
            v_stop_kms=18000.0,
            density_profile="power_law",
            abundance_preset="ic_oxygen_rich",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            config = tt.build_tardis_config(candidate, project_root=root, packet_scale="quick")

        self.assertEqual(config["atom_data"], str((root / "data" / "kurucz_cd23_chianti_H_He_latest.h5").resolve()))
        self.assertEqual(config["model"]["structure"]["density"]["type"], "power_law")
        self.assertEqual(config["model"]["abundances"]["type"], "uniform")
        self.assertIn("O", config["model"]["abundances"])
        self.assertEqual(config["montecarlo"]["iterations"], 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail because the module does not exist**

Run:

```bash
conda run -n astro_env python -m unittest tests/test_tardis_tuning.py
```

Expected: FAIL or ERROR with `ImportError` for `src.tardis_tuning`.

## Task 2: Core Tuning Module

**Files:**
- Create: `src/tardis_tuning.py`

- [ ] **Step 1: Implement dataclasses and candidate generation**

Add dataclasses:

```python
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
```

Implement `generate_candidates(...)` as a deterministic nested product over luminosity, velocity scale, epoch, density profile, and abundance preset. Clamp `v_start_kms >= 2500`, `v_stop_kms > v_start_kms + 1500`, and assign IDs as `<TARGET>_cNNN`.

- [ ] **Step 2: Implement TARDIS config building**

Implement `build_tardis_config(candidate, project_root, packet_scale)` using the existing base shape:

```python
{
    "tardis_config_version": "v1.0",
    "supernova": {
        "luminosity_requested": f"{candidate.log_lsun:.2f} log_lsun",
        "time_explosion": f"{candidate.time_explosion_days:.1f} day",
    },
    "atom_data": str((project_root / "data" / "kurucz_cd23_chianti_H_He_latest.h5").resolve()),
    "model": {
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
    },
    "plasma": {
        "ionization": "lte",
        "excitation": "lte",
        "radiative_rates_type": "dilute-blackbody",
        "line_interaction_type": "macroatom",
    },
    "montecarlo": montecarlo_config(packet_scale),
    "spectrum": {"start": "500 angstrom", "stop": "20000 angstrom", "num": 10000, "method": "real"},
}
```

`packet_scale="quick"` uses 12000 packets, 3 iterations, 25000 final packets. `packet_scale="final"` uses 50000 packets, 10 iterations, 100000 final packets.

- [ ] **Step 3: Implement preprocessing and scoring**

Implement:

```python
def continuum_normalize(wave: np.ndarray, flux: np.ndarray, *, window_pixels: int = 151) -> np.ndarray
def smooth_flux(flux: np.ndarray, *, window_pixels: int = 11) -> np.ndarray
def score_spectra(obs_wave, obs_flux, sim_wave, sim_flux, *, line_windows) -> ScoreResult
```

Use `scipy.ndimage.median_filter` for broad pseudo-continuum and `scipy.signal.savgol_filter` for smoothing. Interpolate simulation flux onto observed wavelength points, compute broad RMSE and line-window RMSE, compute correlation penalty as `1 - corr`, and measure absorption-minimum offsets inside each window.

- [ ] **Step 4: Implement plotting and persistence helpers**

Implement:

```python
def plot_comparison(...)
def write_yaml(path: Path, config: dict) -> None
def save_best_outputs(...)
```

The plot must show normalized observed and TARDIS spectra in the top panel, residual in the lower panel, and translucent spans for scored line windows.

- [ ] **Step 5: Run unit tests**

Run:

```bash
conda run -n astro_env python -m unittest tests/test_tardis_tuning.py
```

Expected: all tests pass.

## Task 3: CLI Runner

**Files:**
- Create: `scripts/run_tardis_tuning.py`

- [ ] **Step 1: Implement argparse and target loading**

CLI arguments:

```text
--project-root .
--target TARGET        repeatable, default all four configured targets
--spectrum-index N     default 0
--max-candidates N     default 12
--packet-scale quick   choices quick, final
--reuse-existing
--adopt-best
```

Load seeds with `src.spectral_notebook_tools.estimate_tardis_context(...)`, using the selected spectrum index. Normalize `SN2026jlm` and `SN2026kie` display names to uppercase targets for output directories and config names.

- [ ] **Step 2: Implement TARDIS run loop**

Inside the CLI, import TARDIS only after argparse and environment setup:

```python
from tardis import run_tardis

sim = run_tardis(
    str(config_path),
    show_convergence_plots=False,
    log_level="WARNING",
    show_progress_bars=False,
)
```

Extract arrays with the local helper logic: `sim.spectrum_solver.spectrum_real_packets`, sorted by wavelength, using `.luminosity_density_lambda.value`.

- [ ] **Step 3: Implement candidate result table**

For each candidate append one row with:

```text
target,candidate_id,status,total_score,broad_rmse,line_rmse,corr_penalty,min_offset_A,
log_lsun,time_explosion_days,v_start_kms,v_stop_kms,density_profile,abundance_preset,
config_path,spectrum_path,plot_path,error
```

Write `scores.csv` after every candidate so interrupted runs keep partial results.

- [ ] **Step 4: Implement `--adopt-best`**

When enabled, copy:

- best YAML to `configs/tardis/<TARGET>.yml`
- best YAML to `output/<TARGET>/tardis/tardis_config_<TARGET>.yml`
- best spectrum to `output/<TARGET>/tardis/tardis_spectrum_<TARGET>.dat`
- best plot to `output/<TARGET>/tardis/tardis_comparison_<TARGET>.png`

- [ ] **Step 5: CLI help smoke test**

Run:

```bash
conda run -n astro_env python scripts/run_tardis_tuning.py --help
```

Expected: help text prints without importing TARDIS.

## Task 4: Integration and First Tuning Batch

**Files:**
- Generate under: `output/tardis_tuning/`
- Adopt into: `configs/tardis/` and `output/<TARGET>/tardis/` only when `--adopt-best` is used.

- [ ] **Step 1: Single-candidate integration test**

Run:

```bash
conda run -n tardis python scripts/run_tardis_tuning.py --target SN2026FVX --max-candidates 1 --packet-scale quick
```

Expected: one candidate row in `output/tardis_tuning/SN2026FVX/scores.csv`, one spectrum `.dat`, one comparison `.png`, exit code 0.

- [ ] **Step 2: Batch quick search**

Run:

```bash
conda run -n tardis python scripts/run_tardis_tuning.py --packet-scale quick --max-candidates 12 --adopt-best
```

Expected: all four targets have `best_summary.json`, `best_comparison.png`, adopted configs, and adopted output spectra.

- [ ] **Step 3: Visual review**

Open each adopted comparison image with the image viewer:

```text
output/SN2026FVX/tardis/tardis_comparison_SN2026FVX.png
output/SN2026JLM/tardis/tardis_comparison_SN2026JLM.png
output/SN2026KID/tardis/tardis_comparison_SN2026KID.png
output/SN2026KIE/tardis/tardis_comparison_SN2026KIE.png
```

Record whether each target is acceptable, velocity-shifted, continuum-mismatched, or missing key features.

## Task 5: Iterate and Finalize

**Files:**
- Modify: `configs/tardis/*.yml` via `--adopt-best`
- Generate: `output/tardis_tuning/*`

- [ ] **Step 1: Expand ranges if visual review fails**

If line positions are wrong, rerun the affected target with a larger candidate count:

```bash
conda run -n tardis python scripts/run_tardis_tuning.py --target TARGET --packet-scale quick --max-candidates 24 --adopt-best
```

If packet noise dominates, rerun the best adopted target in final scale:

```bash
conda run -n tardis python scripts/run_tardis_tuning.py --target TARGET --packet-scale final --max-candidates 1 --reuse-existing --adopt-best
```

- [ ] **Step 2: Run regression tests after code changes**

Run:

```bash
conda run -n astro_env python -m unittest tests/test_tardis_tuning.py tests/test_tardis_acceleration_overlay.py tests/test_acceleration_config.py
```

Expected: all tests pass.

- [ ] **Step 3: Inspect final git diff**

Run:

```bash
git status --short
git diff -- src/tardis_tuning.py scripts/run_tardis_tuning.py tests/test_tardis_tuning.py configs/tardis
```

Expected: code, tests, and adopted YAML changes only. `output/` and `data/` remain gitignored.
