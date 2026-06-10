# TARDIS Tuning Runner Design

## Goal

Build a reproducible command-line workflow that tunes one qualitative TARDIS model for each of the four configured targets:

- `SN2026FVX`
- `SN2026JLM`
- `SN2026KID`
- `SN2026KIE`

The workflow must produce target-specific YAML configs, synthetic spectra, comparison plots, and score tables that make it clear which model is currently preferred. The result is a qualitative spectral-shape and line-identification aid, not a physical ejecta-mass or abundance inference.

## Context

The current notebook, `notebooks/03_tardis_modeling_optional.ipynb`, can run one target at a time but has three practical problems:

1. Existing comparison plots use a global normalization that can make either the observed spectrum or the TARDIS spectrum nearly invisible.
2. Two configs use stale absolute `atom_data` paths from another machine.
3. The workflow has no batch loop, no candidate score table, and no clear stopping condition for parameter iteration.

TARDIS official docs show that every run needs atomic data and a YAML configuration, and the quickstart exposes the same `run_tardis(...)` and `sim.spectrum_solver.spectrum_real_packets` API used locally. The model configuration docs also confirm the built-in `specific` velocity structure plus `branch85_w7`, `exponential`, `power_law`, and `uniform` density profiles.

## Approach Options

### Option A: Notebook-only manual tuning

Run the existing notebook repeatedly and edit YAML values by hand. This is easy to start but hard to reproduce, and it does not solve batch scoring or consistent normalization.

### Option B: Scripted grid tuning with visual review

Create a script that builds a finite grid around each target's starting parameters, runs TARDIS for each candidate, scores the output against the selected observed spectrum, writes plots, then lets us inspect the best images and widen the grid if needed. This is the recommended approach because it is reproducible, bounded, and still keeps the final visual judgment in the loop.

### Option C: Optimizer-driven fitting

Use a Bayesian optimizer or evolutionary search over luminosity, epoch, velocity, density, and abundances. This is not appropriate for the current sparse spectra because the model is qualitative, each run is expensive, and the fitted numbers would be easier to over-interpret.

## Selected Design

Use Option B.

The first implementation will add a small library module plus a CLI script:

- `src/tardis_tuning.py`: reusable functions for target metadata loading, candidate generation, YAML writing, spectrum preprocessing, scoring, and plotting.
- `scripts/run_tardis_tuning.py`: command-line entry point. Run this with `conda run -n tardis python scripts/run_tardis_tuning.py ...`.
- `tests/test_tardis_tuning.py`: fast unit tests for candidate generation, config patching, pseudo-continuum normalization, and scoring. These tests do not import or run TARDIS.

## Reference Spectra

Each target will initially tune to one representative observed spectrum:

- Default selector: earliest local FITS spectrum for that target.
- Override: `--spectrum-index N` for one target or `--target TARGET --spectrum-index N`.

This keeps the scope to four models. Multi-epoch fitting is explicitly out of scope for this pass.

## Candidate Parameters

The grid will include:

- `log_lsun`: requested luminosity in `log_lsun`.
- `time_explosion_days`: time since explosion.
- `v_start_kms`: inner velocity boundary.
- `v_stop_kms`: outer velocity boundary.
- `density_profile`: `branch85_w7` for Ia by default; `power_law` alternatives for II and Ibc.
- `abundance_preset`: target-family presets plus a small set of targeted variants.

Initial values come from the current analysis tables and existing configs when available. Candidate ranges are deliberately narrow for the first pass:

- luminosity offsets: `[-0.35, 0.0, +0.35]`
- epoch offsets: `[-6, 0, +6]` days
- velocity scale: `[0.85, 1.0, 1.15]`
- optional family-specific abundance variants

The CLI will support `--max-candidates` so we can run a small first round and expand if the plots are still poor.

## Spectrum Preprocessing

The comparison should not use raw global 95-percentile scaling. Instead:

1. Convert observed wavelengths to rest frame using the adopted redshift.
2. Smooth both observed and synthetic spectra to comparable resolution.
3. Crop to the useful observed range, normally 3600 to 8800 Angstrom.
4. Estimate a robust pseudo-continuum with a broad median filter.
5. Compare continuum-normalized flux within target-specific line windows.

This makes the score sensitive to line positions and broad features rather than packet noise or absolute flux scale.

## Scoring

The score is lower-is-better and combines:

- broad-spectrum normalized RMSE over the overlap region,
- line-window RMSE for the target's diagnostic lines,
- correlation penalty over the same windows,
- absorption-minimum wavelength penalty where both spectra show a local trough.

Diagnostic windows come from the same line families already used by `src.spectral_pipeline`:

- Ia: Ca II H&K, Si II 5972, Si II 6355, Ca II NIR.
- II: Halpha, Hbeta, Fe II 5169.
- Ic: O I 7774, Ca II NIR, Ca II H&K, Fe II 5169.

The output score table records each component, not just the combined score.

## Outputs

Write all tuning products under:

`output/tardis_tuning/<TARGET>/`

For each candidate:

- `candidates/<candidate_id>.yml`
- `candidates/<candidate_id>.dat`
- `figures/<candidate_id>_comparison.png`

For each target:

- `scores.csv`
- `best_config.yml`
- `best_spectrum.dat`
- `best_comparison.png`
- `best_summary.json`

When a target's best candidate is selected for project use, copy the config to `configs/tardis/<TARGET>.yml` and copy the spectrum/config/plot to `output/<TARGET>/tardis/`.

## Visual Review Loop

After each batch, inspect each target's `best_comparison.png` with the image viewer. If the visual result is poor, widen the parameter range based on the visible failure:

- Line troughs too blue or too red: adjust velocity boundaries.
- Continuum too hot or too cool: adjust `log_lsun` and `time_explosion_days`.
- Missing H/He/O/Ca/Si features: adjust abundance preset.
- Excessively spiky synthetic spectrum: increase packet count for finalists and use smoothed comparison for scoring.

The iteration stops when all four best plots show the main diagnostic features at approximately the right rest wavelengths and the score table no longer improves materially after one widened search.

## Error Handling

The runner should continue past failed candidates. For each failure it writes:

- target,
- candidate id,
- config path,
- exception summary,
- return code or Python exception type.

Failed candidates get `status=failed` in `scores.csv` and are excluded from best selection.

## Testing

Unit tests run in `astro_env`:

```bash
conda run -n astro_env python -m unittest tests/test_tardis_tuning.py
```

Integration runs use `tardis`:

```bash
conda run -n tardis python scripts/run_tardis_tuning.py --target SN2026FVX --max-candidates 1 --packet-scale quick
```

The integration check proves the generated YAML is valid for the installed TARDIS version and that spectrum extraction works.
