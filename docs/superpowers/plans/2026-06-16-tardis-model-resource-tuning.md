# TARDIS Model Resource Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use the newly prepared `data/tardis_models/` resources to improve TARDIS tuning, then update project docs and reports with reproducible results.

**Architecture:** Keep atom-data/model-resource preparation separate from simulation. Extend the existing tuning candidate/config builder so some Ia candidates can use `csvy_model` files while existing uniform-abundance/specific-density candidates keep working unchanged. Preserve final adopted outputs under `output/<TARGET>/tardis/` and report-local copies under `report/assets/tardis/`.

**Tech Stack:** Python 3.10 `astro_env` for tests/docs/data handling; Python 3.13 `tardis` env for TARDIS configuration/simulation; TARDIS v2026.5.31 config v1.0; matplotlib PNG comparison plots.

---

### Task 1: Validate Downloaded Resource State

**Files:**
- Read: `data/tardis_models/model_resources_index.csv`
- Read: `configs/tardis/model_resources.yml`

- [x] **Step 1: Check resource files exist**

Run: `find data/tardis_models -maxdepth 4 -type f -print | sort`
Expected: 7 resource files plus `model_resources_index.csv`.

- [x] **Step 2: Check TARDIS can use Ia CSVY model resources through candidate configs**

Run a temporary `Configuration.from_yaml(...)` check for generated candidate YAML files that reference `data/tardis_models/ia/*.csvy` through `csvy_model`.
Expected: representative CSVY-backed candidate configs load without parser errors; the CSVY files themselves are model resources, not standalone run configs.

### Task 2: Add CSVY Model Candidate Support

**Files:**
- Modify: `src/tardis_tuning.py`
- Modify: `scripts/run_tardis_tuning.py`
- Test: `tests/test_tardis_tuning.py`

- [x] **Step 1: Write failing tests**

Add tests proving `TardisCandidate` can carry `model_resource`, `build_tardis_config()` emits `csvy_model` instead of `model.structure/model.abundances`, and ordinary uniform candidates still emit the old config shape.

- [x] **Step 2: Run tests and see failure**

Run: `conda run -n astro_env python -m unittest tests.test_tardis_tuning`
Expected: fail because `model_resource` is not supported yet.

- [x] **Step 3: Implement minimal support**

Add optional `model_resource` field, helper functions to find Ia CSVY resources under `data/tardis_models/ia`, and config generation that uses absolute `csvy_model` paths for resource-backed candidates.

- [x] **Step 4: Run tests and verify pass**

Run: `conda run -n astro_env python -m unittest tests.test_tardis_tuning`
Expected: all tests pass.

### Task 3: Run Bounded New-Resource Tuning

**Files:**
- Write runtime outputs under: `output/tardis_tuning/`
- Update adopted outputs under: `configs/tardis/` and `output/<TARGET>/tardis/` only when the new best score is better.

- [x] **Step 1: Run Ia model-resource search**

Run TARDIS quick searches for `SN2026FVX` and `SN2026JLM` with `--include-model-resources`, moderate candidate limits, and `--adopt-best`.
Expected: new scores/plots are produced and adopted only if score improves.

- [x] **Step 2: Run non-Ia refinement**

Run bounded quick searches for `SN2026KID` and `SN2026KIE` using current analytic density/abundance candidates.
Expected: no CSVY Ia resources are applied to non-Ia targets.

- [x] **Step 3: Inspect figures**

Open the final comparison PNGs for each target and compare visually with previous final results.
Expected: identify which targets improved and where remaining mismatches persist.

### Task 4: Update Documentation and Report

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `report/tardis_report.md`
- Copy runtime artifacts into: `report/assets/tardis/`

- [x] **Step 1: Document model-resource workflow**

Add how to run `scripts/download_tardis_model_resources.py`, what it installs, and when to use it.

- [x] **Step 2: Update final TARDIS result summary**

Refresh report tables/figures/data copies so they match the latest adopted outputs.

### Task 5: Final Verification

**Files:**
- Read/check all changed docs and generated summaries.

- [x] **Step 1: Run unit tests**

Run: `conda run -n astro_env python -m unittest discover -s tests -p 'test*.py'`
Expected: all tests pass.

- [x] **Step 2: Verify TARDIS outputs**

Check every adopted target has config, spectrum, comparison PNG, and summary data; check report image links point to existing files.

- [x] **Step 3: Summarize results**

Report changed files, best scores, visual assessment, and remaining limitations.
