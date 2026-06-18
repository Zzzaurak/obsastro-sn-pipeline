# AGENTS.md — AI Agent Instructions

## Project Overview

Supernova observing and sparse-spectrum analysis pipeline. The project queries TNS (Transient Name Server), computes nightly observability windows, downloads/organizes Lasair and WISeREP auxiliary data, runs a reproducible spectral-diagnostics pipeline, and generates Chinese report notebooks plus English final-presentation slides.

## 语言约定

- `ppt/` 下的最终展示材料按课程要求使用英文。
- `README.md`、`notebooks/`、报告 notebook 的说明文字可以使用中文；这也是当前仓库采用的默认写法。
- 代码变量、函数名、CSV 字段名和命令行参数保持英文，便于维护和复用。
- 文献原文、图表坐标轴或外部软件输出可保留英文；正式口头展示时再翻译成英文 slides。

## Current Deliverable Workflow

Use these as the current stable entry points:

```bash
conda activate astro_env
python scripts/fetch_target_params.py
python scripts/fetch_aux_data.py
python scripts/build_analysis_products.py
python scripts/build_presentation_figures.py
```

- Main scientific tables are under `output/analysis_pipeline/*.csv`. Batch script outputs are unprefixed; interactive `02` runs can write `<RUN_TAG>_*.csv` to avoid overwriting other targets.
- Main scientific figures are under `output/analysis_pipeline/figures/*.png`. Interactive `02` shared science figures can write `<RUN_TAG>_*.png`.
- Slide-specific copies/composites are under `ppt/figures/`.
- Final slides under `ppt/` must stay English.
- README and top-level notebooks can use Chinese explanatory text.
- Top-level notebooks are edited directly; treat `notebooks/02_spectral_analysis_pipeline.ipynb` as the canonical source for the spectral-analysis workflow and keep README/notebook README text in sync when you change it.
- In `notebooks/02_spectral_analysis_pipeline.ipynb`, keep the single-line local-check output concise. Show the candidate-line table, the selected `CHECK_LINE_INDEX` when `CHECK_LINE_KEY=None`, and the preview-only overrides (`CHECK_HALF_WIDTH`, `CHECK_SMOOTH_WINDOW`, `CHECK_EDGE_FRACTION`). Do not reintroduce a separate redshift-check section unless the user explicitly asks.
- Absorption-line measurements use the smoothed, locally normalized trough minimum for `abs_wave`/velocity/depth, and a non-parametric half-depth width for FWHM. Do not reintroduce a Gaussian absorption fit or purple model curve unless the user explicitly asks for a comparison-only diagnostic.
- Current TNS public catalog fields do not include maximum-light or peak-date metadata. Keep `phase_days` defined as days since TNS discovery date. Do not add or reinterpret maximum-light phase columns unless reliable peak dates/light-curve constraints are explicitly added later; Superfit phase output is not reliable enough for this project.
- Conservative line adoption policy: Ia automatically adopts only `SiII6355` and Ca II blend proxies after QC; keep `SiII5972` as visual/check context. Type II/IIb automatically adopts `FeII5169` after QC; keep Balmer trough velocities as visual/check context unless manually validated. Ca II H&K and Ca II NIR are blend-proxy measurements, so keep `rest_wave_choice` and `line_blend_note` columns when editing exports.

## Module Map

| File | Role | Entry Points |
|------|------|-------------|
| `src/pipeline.py` | **Core orchestrator**: config loading, TNS data acquisition (catalog + page scraping), observability calculation, finder chart download, report generation | `run_pipeline(config_path)` |
| `src/spectral_pipeline.py` | **Current main science pipeline**: reads calibrated 1-D FITS spectra, rest-frame correction, discovery-date phase, minimum-trough line velocities/depths, pEW/non-parametric FWHM, line systematics columns, blackbody color-temperature proxy QC, host-line indices, CSV/figure generation | `build_all(project_root, output_dir)` |
| `src/finder.py` | **Finder chart generator**: astroquery SkyView query + matplotlib WCS plot with crosshair, scale bar | `generate_finder_chart()` |
| `scripts/fetch_target_params.py` | **CLI wrapper**: invokes `python -m src.pipeline` from project root | `main()` |
| `src/fetch_aux_data.py` | **Aux data orchestrator**: Lasair light curve + WISeREP spectra acquisition | `run(config_path)` |
| `scripts/build_analysis_products.py` | **Science-product builder**: command-line wrapper around `src.spectral_pipeline.build_all()` | `main()` |
| `scripts/build_presentation_figures.py` | **Slide-figure builder**: copies/recomposes analysis figures into `ppt/figures/` | `main()` |
| `src/lasair.py` | **Lasair light curve**: ZTF light curve download, CSV export, matplotlib plot with filters | `fetch_lasair_object()`, `plot_lightcurve()` |
| `src/wiserep.py` | **WISeREP spectra**: spectrum metadata search, file download, ASCII parsing, plotting | `fetch_spectra_metadata()`, `download_spectrum_file()`, `plot_spectra()` |
| `src/utils.py` | HTTP client, TNS credentials manager (`TnsCredentials`), `.env` loader, CSV I/O, rate-limit tracking | `load_env_file()`, `get_tns_credentials()`, `tns_auth_headers()` |
| `src/tns.py` | Bot-mode TNS API integration (Get Object, Get File, public catalog download) | `download_tns_catalog()`, `fetch_tns_object()`, `download_tns_spectra_files()` |
| `src/target.py` | `Target` dataclass with ~25 fields (coordinates, magnitudes, observability, URLs) | `Target`, `merge_targets()`, `filter_targets()` |
| `src/observability.py` | Nightly altitude/visibility computation (astropy primary, pure-Python fallback) | `compute_observability()`, `compute_observability_simple()` |
| `src/coordinates.py` | Coordinate format conversion (sexagesimal ↔ decimal degrees) | `deg_to_hms()`, `deg_to_dms()`, `sexagesimal_to_deg()` |
| `src/time_utils.py` | Julian Date conversion, GMST, solar position (low-precision), altitude formula | `datetime_to_jd()`, `altitude_deg()`, `sun_ra_dec_approx()` |
| `src/config.py` | JSON config loading with flattening, defaults, type coercion | `load_config()`, `flatten_config()` |
| `src/acceleration_config.py` | Superfit/DASH/TARDIS acceleration config loading, worker/thread resolution, runtime env setup, TARDIS YAML overlays | `load_acceleration_config()`, `apply_runtime_environment()`, `apply_tardis_config_overrides()` |
| `scripts/download_tardis_atom_data.py` | **TARDIS atomic data downloader**: downloads `kurucz_cd23_chianti_H_He_latest.h5` into `data/`, updates `~/.astropy/config/tardis_internal_config.yml` to point to project `data/` | `download_atom_data()` |
| `src/tardis_model_resources.py` | **TARDIS model-resource manager**: copies package example CSVY/density/abundance resources into `data/tardis_models/` and writes an index for reproducibility | `download_resources()` |
| `scripts/download_tardis_model_resources.py` | **TARDIS model-resource CLI**: dry-run or materialize model resources configured by `configs/tardis/model_resources.yml` | `main()` |
| `src/tardis_tuning.py` | **TARDIS tuning helpers**: observed-spectrum loading, target seeds, analytic/CSVY candidate generation, plasma physics presets, config writing, scoring, and adoption helpers | `generate_candidates()`, `build_tardis_config()`, `score_model()` |
| `scripts/run_tardis_tuning.py` | **TARDIS tuning CLI**: runs per-target candidate grids, writes comparison figures/scores, optionally adopts a checked best model; supports `--physics-preset current|literature|both` for analytic candidates | `main()` |

## Configuration

### `configs/sn_parameter.json`

Five sections, all flattened at load time:

- **`observing`**: `target`, `date`, `site_lat`, `site_lon`, `site_elevation_m`, `tz_offset`, `min_alt` (airmass≤2 threshold), `sun_alt_limit` (twilight), `time_step_minutes`
- **`tns`**: `enabled`, `download_files` (finder chart), `pause_seconds`
- **`lasair`**: `lasair_enabled`
- **`wiserep`**: `wiserep_enabled`
- **`output`**: `out_dir`, `report_file` (template with `{date}` and `{target}` placeholders), `finder_fov_arcmin`

### `configs/acceleration.json`

Central acceleration knob file for interactive Superfit/DASH/TARDIS helper workflows:

- **`runtime`**: `gpu`, `cuda_visible_devices`, `max_workers`, `blas_threads_per_worker`
- **`superfit`**: `workers`, `rerun_existing`, `z_range`, `z_step`, `resolution`, `how_many_plots`, `prefer_known_redshift`
- **`dash`**: `gpu`, `known_z`, `rlap_scores`, `top_n`, `batch_size`
- **`tardis`**: writes YAML overrides only; controls `nthreads`, `numba_num_threads`, `spectrum_source`, `montecarlo` packet/iteration counts, and `spectrum` grid/integrated options

`src.spectral_notebook_tools.run_superfit_batch()`, `run_dash_batch()`, and `build_tardis_config_from_context()` read this file by default from the project root. `tardis` environment package changes are intentionally separate from this repository config.

### `.env`

```env
# TNS user credentials (no bot needed; works for staged CSV catalog download).
# Get yours from your TNS account page (My Account → User-Agent specification).
TNS_USER_ID=
TNS_USER_NAME=

# Put your Lasair API token after the equals sign. Do not commit a real token.
# Both download scripts read this file automatically from the project root.
LASAIR_API_TOKEN=

# Backward-compatible alias. Leave blank unless you have old shell setup using this name.
LASAIR_TOKEN=

# WISeREP personal API key (optional — public spectra are accessible without it).
# Get yours from https://www.wiserep.org/user → My Account → Create new API Key.
WISEREP_API_KEY=
```

**Current auth mode: USER** (no bot API key). The pipeline downloads the TNS public catalog CSV (user-auth required) and scrapes the object page HTML.

### `configs/tardis/base_Ia.yml`

TARDIS simulation baseline for Type Ia SNe. YAML config with 7 sections (keys required at root, others optional):

| Key | Required | Description |
|-----|----------|-------------|
| `tardis_config_version` | YES | Always `v1.0` |
| `atom_data` | YES | Path to `kurucz_cd23_chianti_H_He_latest.h5` |
| `spectrum` | YES | `start/stop/num` in angstrom; also has `virtual` subkey for virtual packet spectrum logging |
| `supernova` | no | `luminosity_requested` (e.g. `9.4 log_lsun` or `1e43 erg/s`), `time_explosion` (e.g. `13 day`) |
| `model.structure` | no | `type: specific` with `velocity` (start/stop/num) + `density` (type: `branch85_w7`, `exponential`, `power_law`, or `uniform`) |
| `model.abundances` | no | `type: uniform` with element mass fractions summing to 1.0; or `type: file` referencing an external abundance file |
| `plasma` | no | `ionization` (lte/nebular), `excitation` (lte/dilute-lte), `radiative_rates_type` (dilute-blackbody/detailed), `line_interaction_type` (macroatom/scatter) |
| `montecarlo` | no | `seed`, `nthreads`, `no_of_packets`, `iterations`, `last_no_of_packets`, `no_of_virtual_packets`, `convergence_strategy` (damped with damping_constant, threshold, lock_t_inner_cycles, t_inner_update_exponent) |

**Density profile types:**
- `branch85_w7` — 7th-order polynomial fit to W7 Ia model, parametrised by time_explosion only (w7_time_0/w7_rho_0/w7_v_0 are fixed)
- `exponential` — ρ(v) = ρ₀·exp(-v/v₀), needs `rho_0`, `v_0`, optional `time_0`
- `power_law` — ρ(v) = ρ₀·(v/v₀)^n, needs `rho_0`, `v_0`, `exponent`
- `uniform` — Constant density, needs `value`

**criterion for velocity range:** inner boundary ~0.6×v_phot, outer boundary ~1.3×v_exp. For Ia, v_phot ≈ 0.7×v_line.

**Notebook auto-generates** per-target config at `configs/tardis/{TARGET}.yml` by overriding luminosity, time_explosion, velocity range, and (for non-Ia) abundances from the base template.

### `configs/tardis/model_resources.yml`

Optional TARDIS model-resource manifest used by `scripts/download_tardis_model_resources.py`. It currently copies available package resources from the installed `tardis` environment rather than downloading large external grids:

- Ia CSVY example models: delayed detonation, deflagration, double detonation, and merger composition examples.
- Example density/abundance tables: package examples for testing file-backed model inputs.
- Output location: `data/tardis_models/`, with `model_resources_index.csv` recording source, destination, size, and status.

These CSVY resources are useful for qualitative experiments and format coverage, but they are model resources referenced by `csvy_model`, not standalone run configs, and they are not automatically better physical fits for sparse observed spectra.

## TNS Data Flow

1. **Ensure catalog** (`ensure_catalog()`):
   - Check `data/tns_public_objects.csv` age (< 24h)
   - If stale/missing: download `tns_public_objects.csv.zip` with `User-Agent: tns_marker{...}` header
   - Extract CSV from ZIP → `data/tns_public_objects.csv`

2. **Lookup target** (`lookup_catalog_target()`):
   - Match by `name_prefix + name`, then by `name` alone, then by `internal_names`

3. **Build Target** (`build_target_from_catalog()`):
   - Fields from CSV: `name_prefix`, `name`, `type`, `ra` (decimal deg), `declination`, `redshift`, `discoverydate`, `discoverymag`, `discmagfilter`/`filter`

4. **Scrape object page** (`fetch_tns_object_page()` + `update_target_photometry_from_page()`):
   - Fetch `https://www.wis-tns.org/object/{name}` (no auth needed)
   - Parse HTML tables for photometry rows (skip `Lim. Mag.` and non-detection rows)
   - Update target magnitude with most recent (by JD) detection

5. **Find chart** (`find_page_image_urls()`):
   - Search `<img>` tags for files containing "atrep", "finder", "chart", "stamp"
   - Fallback: search `<a>` tags linking to `.png/.jpg`

6. **Astroquery finder chart** (`generate_finder_chart()`):
   - Query SkyView for survey cutout (DSS2 Red, configurable FOV)
   - Plot with matplotlib + astropy WCS projection
   - Annotate with crosshair at target position and scale bar
   - Save to `output/{target}/finder_astroquery_{survey}.png`

## Observability

`compute_observing_window()`:
- Time range: 18:00 local → 06:00 (+1d) local
- Step: `time_step_minutes` from config
- Primary: astropy `AltAz` + `get_sun` (requires IERS data)
- Fallback: pure-Python `altitude_deg()` + `sun_ra_dec_approx()`
- Returns dict: `{window_start, window_end, max_alt, max_alt_time, duration_hours, visible_hours, observable}`

## Output

- **Report**: `output/{target}/sn_report_{date}_{target}.txt` — plain text with target info, observing window, finder chart status
- **Finder chart (TNS)**: `output/{target}/finder_TNS_{filename}` — downloaded from TNS if available
- **Finder chart (astroquery)**: `output/{target}/finder_astroquery_{survey}.png` — generated via SkyView + matplotlib
- **Light curve CSV**: `output/{target}/lightcurve/lightcurve_lasair.csv` — ZTF photometry from Lasair
- **Light curve plot**: `output/{target}/lightcurve/lightcurve_lasair.png` — matplotlib plot with g/r filter coloring
- **Spectra CSV**: `output/{target}/spectrum/spectra_wiserep.csv` — spectra metadata from WISeREP
- **Spectra plot**: `output/{target}/spectrum/spectra_wiserep.png` — overlaid spectrum curves
- **Spectrum files**: `output/{target}/spectrum/spectrum_*.ascii` — raw downloaded spectral data
- **Clean 2-column spectra**: `output/{target}/spectrum/spectrum_*.dat` — `np.savetxt` cleaned (wl flux), for astrodash
- **Catalog cache**: `data/tns_public_objects.csv` (+ `.zip`)
- **TARDIS atom data**: `data/kurucz_cd23_chianti_H_He_latest.h5` (~212 MB) — Kurucz CD23 + CHIANTI atomic data; downloaded once, shared by all simulations
- **TARDIS model resources**: `data/tardis_models/` — optional package CSVY/density/abundance resources copied by `scripts/download_tardis_model_resources.py`
- **TARDIS simulation spectrum**: `output/{target}/tardis/tardis_spectrum_{target}.dat` — 2-column ASCII (rest-frame wavelength A, luminosity density erg/s/A); 10000 points on 500-20000 A grid
- **TARDIS per-target config**: `output/{target}/tardis/tardis_config_{target}.yml` — copy of the YAML config used for reproducibility
- **TARDIS tuning experiments**: `output/tardis_tuning/{TARGET}/` for baseline tuning and `output/tardis_tuning/{TARGET}__{RUN_LABEL}/` for labeled experiments; contains `scores.csv`, candidate configs/spectra, and comparison PNGs
- **TARDIS report assets**: `report/assets/tardis/` — local copies of adopted configs/spectra/figures plus selected experiment scores/figures for the Markdown report
- **Analysis pipeline tables**: `output/analysis_pipeline/*.csv` — target status, spectra summary, line diagnostics with QC flags/systematics/blend-proxy notes, blackbody color-temperature proxy QC, host-environment line indices with both instance and unique-line counts. `scripts/build_analysis_products.py` writes unprefixed batch names; `notebooks/02_spectral_analysis_pipeline.ipynb` writes `<RUN_TAG>_*.csv` when saving interactively.
- **Analysis pipeline figures**: `output/analysis_pipeline/figures/*.png` — target table, spectral sequences, velocity evolution, pEW evolution, color-temperature proxy, host-line detections. Interactive 02 outputs use target tags for shared summary figures.
- **Presentation figures**: `ppt/figures/*.png` — slide-ready copies/composites generated from analysis outputs

## Conda Environments

| Env | Python | Used For |
|-----|--------|----------|
| `astro_env` | 3.10 | Main pipeline: TNS query, observability, finder charts, light curves, spectrum download/plotting, [astrodash](https://github.com/daniel-murray/astrodash) classification |
| `tardis` | 3.13 | TARDIS Monte Carlo radiative transfer (v2 dev, installed from local repo `~/THU/astronomy/tardis/repo`); spectrum simulation and model-observation comparison. Also requires `tardisbase` package. |
| `py314` | ≥3.14 | Development/testing |

**Environment source of truth**: use `envs/environment_astro_env.yml`. There is no separate `requirements.txt`; do not recreate one unless the project is explicitly being repackaged for pip-only installation.

**Requirements**: astrodash needs `numpy < 1.24` and `tensorflow < 2.16`. The `envs/environment_astro_env.yml` file pins these constraints and also includes Jupyter/IPython tooling (`ipykernel`, `jupyterlab`, `nbconvert`, `nbformat`) for notebook reproducibility.

**CRITICAL — numpy pinning**: numpy MUST be `1.23.5` (the latest `< 1.24`). Even though conda installs `numpy<1.24`, TF's pip dependency `numpy>=1.23.5,<2.0.0` can upgrade numpy to `1.26.x` unless numpy is ALSO pinned in the pip section of the YAML as `numpy==1.23.5`. The YAML pins numpy in both conda and pip sections. Always verify with `python -c "import numpy; print(numpy.__version__)"` after env creation.

- `.env` MUST NOT be committed (contains TNS credentials)
- `output/` and `data/` are gitignored
- TNS Get Object API requires **bot** credentials → pipeline uses public catalog + page scraping instead
- The IERS warning about leap seconds is harmless (set `iers.conf.auto_download = False`)
- Target name normalization: strips `SN`/`AT` prefix, removes spaces for TNS lookup
- Config key flattening: nested dict sections (`observing`, `tns`, `output`) are flattened into a single dict; keys are `lower_snake_case`
- astro_env for astrodash must use `numpy < 1.24` and `tensorflow < 2.16` (or else `np.array([[np.zeros(n),...]])` and `array != []` fail in newer numpy)

## Auxiliary Data Modules

### Lasair (`src/lasair.py`)

`fetch_lasair_object(ztf_id)`:
- Queries `https://lasair-ztf.lsst.ac.uk/api/object/?objectId={ztf_id}`
- Auth via `LASAIR_API_TOKEN` from `.env` (GET query param or header)
- Returns dict with `candidates` (detections) and `forcedphot` (forced photometry)

`plot_lightcurve(candidates, target_name, output_path, *, ztf_id="", obs_date="")`:
- Calendar date x-axis (astropy `Time` mjd→datetime, with `%b %d` formatting)
- AB magnitude y-axis (inverted)
- g-band (green), r-band (red) color coding
- Detections as filled circles with error bars, upper limits as downward triangles
- Annotation: last photometry date and days before observing date

### WISeREP (`src/wiserep.py`)

`fetch_spectra_metadata(objname)`:
- GET `https://www.wiserep.org/search/spectra?name={name}&format=tsv`
- `name` param uses IAU name WITHOUT SN/AT prefix (e.g., `2026fov` not `SN2026fov`)
- Returns ZIP containing TSV with spectra metadata
- Optional `WISEREP_API_KEY` in `.env` for private data access

`plot_spectra(spectrum_files, target_name, output_path)`:
- Parses 2-column ASCII spectra (wavelength, flux)
- Overlays up to 5 spectra on single plot with wavelength in Angstroms

## Lasair Data Flow

1. **Get ZTF ID**: Extract from TNS catalog row's `internal_names` field
2. **Fetch object**: `fetch_lasair_object(ztf_id)` → candidates + forced photometry
3. **Merge**: Combine detection and forced photometry candidates
4. **Export CSV**: `save_lightcurve_csv(candidates, path)`
5. **Plot**: `plot_lightcurve(candidates, target_name, path)`

## TARDIS Simulation Flow

The current top-level TARDIS entry point is `notebooks/03_tardis_modeling_optional.ipynb`. For reproducible batch experiments, use `scripts/run_tardis_tuning.py` in the `tardis` environment. TARDIS should not depend on `notebooks/legacy/` or legacy data: it reads local `data/SN*/` FITS spectra and 02 analysis products such as `<RUN_TAG>_target_status.csv`, `<RUN_TAG>_spectra_summary.csv`, and `<RUN_TAG>_line_diagnostics_qc.csv`; if an old `<RUN_TAG>_manual_redshift_summary.csv` exists, treat it as a legacy fallback only. Older manual TARDIS work is preserved under `notebooks/legacy/` only for provenance. Run this only in the `tardis` kernel/environment and treat it as qualitative support rather than the primary science pipeline.

1. **Load observed spectrum** — reads local one-dimensional FITS spectra from `data/SN*/`, not legacy `.dat` files.
2. **Estimate target parameters from 02 products** — notebook uses the current 02 products (`target_status`, `spectra_summary`, `line_diagnostics_qc`) when available; if a legacy `manual_redshift_summary` still exists, treat it only as a fallback. Manual overrides remain available for redshift, type, velocity, epoch, apparent magnitude, and log luminosity.
   - `epoch_days` starts from manual override, otherwise median discovery-date `phase_days` plus a type-dependent rise-time default. This is not a measured maximum-light phase.
   - `luminosity_requested` starts from manual log(Lsun), or apparent magnitude + Planck18 luminosity distance, or a conservative type default.
   - `velocity start/stop` starts from adopted/check line velocity; for Ia, the photospheric proxy uses ~0.7×line velocity.
3. **Build YAML config** — loads `configs/tardis/base_Ia.yml` template, overrides supernova/model/velocity params, adjusts rough abundances for non-Ia families, applies `configs/acceleration.json` TARDIS YAML overrides, writes to `configs/tardis/{TARGET}.yml`
4. **Check atomic data** — verifies `data/kurucz_cd23_chianti_H_He_latest.h5` exists (~212 MB); if missing, run `scripts/download_tardis_atom_data.py`.
5. **Optional model resources** — run `scripts/download_tardis_model_resources.py` to copy package CSVY/density/abundance resources into `data/tardis_models/`. Use `--dry-run` to inspect sources without writing.
6. **Run simulation or tuning** — notebook uses `run_tardis(config_path, show_convergence_plots=False, log_level="WARNING")`; CLI tuning uses `python scripts/run_tardis_tuning.py --target SN2026KID --run-label analytic_refine --packet-scale quick`.
7. **Compare spectra** — de-redshifts selected local FITS spectrum to rest frame, normalises both, plots overlay + residual in 2-panel figure.
8. **Save results** — writes candidate spectra/configs under `output/tardis_tuning/`; only checked/adopted models should be copied to `configs/tardis/{TARGET}.yml` and `output/{target}/tardis/`.

Useful tuning flags:
- `--run-label LABEL` keeps exploratory output under `output/tardis_tuning/{TARGET}__{LABEL}/` instead of overwriting the baseline tuning directory.
- `--include-model-resources` adds Ia CSVY model-resource candidates to the analytic grid.
- `--model-resource-only` runs only CSVY model-resource candidates.
- `--physics-preset current|literature|both` controls analytic candidate plasma assumptions. `current` is the existing LTE baseline; `literature` uses `nebular` ionization, `dilute-lte` excitation, `dilute-blackbody` radiative rates, and `macroatom` line interaction; `both` compares both. CSVY model-resource candidates keep their resource-driven plasma override.
- `--adopt-best` copies the best-scoring candidate into `configs/tardis/` and `output/{target}/tardis/`; use it only after inspecting `scores.csv` and comparison PNGs.

**Notebook metadata:** use the `tardis` environment/kernel for TARDIS cells. Keep `RUN_TARDIS=False` while checking configuration; set it to `True` only when the TARDIS environment and atom data are ready.

**Switching targets:** change the `TARGET`, `ANALYSIS_TAG`, and `SPECTRUM_INDEX` variables in `notebooks/03_tardis_modeling_optional.ipynb`.

## TARDIS API v2 Notes (CRITICAL)

The installed TARDIS is **v2 development version** (0.1.dev1). The API differs significantly from v1 documented online:

| Old v1 API | New v2 API |
|-----------|-----------|
| `sim.model.t_inner` | `sim.simulation_state.t_inner` |
| `sim.transport.spectrum` | `sim.spectrum_solver.spectrum_real_packets` |
| `spectrum.flux.value` | `spectrum.luminosity_density_lambda.value` (luminosity density in erg/s/A; normalise for shape comparison) |
| `Configuration.from_yaml(path)` | Same — still works |
| `run_tardis(config_path)` | Same — still works; keyword args: `show_convergence_plots`, `log_level`, `show_progress_bars` |

In the current environment, import `Configuration` as `from tardis.io.configuration.config_reader import Configuration`; it is not exported from the `tardis.io.configuration` package root.

**Spectrum object** (`TARDISSpectrum` from `tardis.spectrum.spectrum`):
- `.wavelength` — Quantity array (Angstrom), descending order (20000→500 A), len=10000
- `.luminosity_density_lambda` — Quantity array (erg/s/A), no `distance` needed
- `.luminosity_density_nu` — Quantity array (erg/s/Hz)
- `.flux_nu`, `.flux_lambda` — require `.distance` attribute set first (use `.luminosity_density_lambda` for normalised comparison)
- `.frequency` — Quantity array (Hz)

**Simulation object** attributes (post-`run_tardis`):
- `.simulation_state` — `SimulationState` object: `.t_inner` (K), `.time_explosion`, `.velocity`, `.abundance`, `.dilution_factor`, `.t_radiative`
- `.plasma` — plasma state (`.electron_densities`, `.ion_number_density`, etc.)
- `.transport` — `MCTransportSolverClassic` (does NOT have `.spectrum`; use `.spectrum_solver`)
- `.spectrum_solver.spectrum_real_packets` — final output spectrum
- `.spectrum_solver.spectrum_virtual_packets` — virtual packet spectrum (if enabled)
- `.spectrum_solver.spectrum_integrated` — integrated spectrum
- `.iterations_executed` — number of completed iterations
- `.luminosity_requested` — target luminosity used (erg/s)

**Spectrum extraction for tuning:** prefer finite spectra in this order: integrated, virtual packets, real packets. Some CSVY resource runs in the current TARDIS v2 environment can produce `spectrum_integrated` with length 1 and `NaN`; skip that and fall back to virtual or real packets before scoring/plotting. Real-packet spectra can look like narrow vertical spikes when packet statistics are low or bin sampling is sparse; increase packets/virtual packets for smoother final comparison, but always judge against the observed line positions and broad features rather than smoothness alone.

**TARDIS internal config path:** `~/.astropy/config/tardis_internal_config.yml` contains `data_dir` pointing to project `data/`. Atom data file must be at `data/kurucz_cd23_chianti_H_He_latest.h5`. Use `get_data_dir()` from `tardis.io.configuration.config_internal` to resolve at runtime.

**Segfault note:** TARDIS v2 may segfault on process exit in some environments (macOS arm64). The simulation itself completes normally; the crash occurs during Python interpreter shutdown. Harmless for notebook use.

## WISeREP Data Flow

1. **Search spectra**: `fetch_spectra_metadata(name)` → TSV metadata
2. **Save CSV**: `save_spectra_csv(rows, path)` — metadata summary
3. **Download files**: `download_spectrum_file(url, path)` — 2-column ASCII
4. **Plot**: `plot_spectra(files, target_name, path)` — overlaid curves

## Important Notes

- `.env` MUST NOT be committed (contains TNS credentials)
- `output/` and `data/` are gitignored
- TNS Get Object API requires **bot** credentials → pipeline uses public catalog + page scraping instead
- The IERS warning about leap seconds is harmless (set `iers.conf.auto_download = False`)
- Target name normalization: strips `SN`/`AT` prefix, removes spaces for TNS lookup
- Config key flattening: nested dict sections (`observing`, `tns`, `output`) are flattened into a single dict; keys are `lower_snake_case`
- Long CSVY TARDIS tuning grids can accumulate memory and exit with code 137. Prefer small labeled batches, then validate one or two promising candidates with `--packet-scale final`.
- Current second-pass TARDIS check found no final adopted improvement from package CSVY resources. Keep the adopted model table in `report/tardis_report.md` as the source of truth unless a final-packet validation improves both score and visual line agreement.

## Notebooks

Current top-level notebooks are curated deliverables. Older exploratory notebooks are preserved under `notebooks/legacy/` and should not be treated as the main workflow.

| Notebook | Role |
|----------|------|
| `notebooks/01_data_collection_and_observing.ipynb` | Target metadata, observing preparation, and product inventory. Remote refresh is opt-in. |
| `notebooks/02_spectral_analysis_pipeline.ipynb` | Main interactive spectral diagnostics notebook; reads local FITS, adopts TNS redshift, supports type-aware automatic line selection, minimum-trough absorption measurements, single-line local checks with `CHECK_LINE_INDEX`, target-tagged CSV/figure output, and local diagnostic plots. |
| `notebooks/03_tardis_modeling_optional.ipynb` | Optional self-contained TARDIS setup/simulation notebook; uses local FITS and 02 products for starting parameters, no legacy dependency. |
| `notebooks/04_project_report.ipynb` | Chinese P2Rp2-style report notebook with question, data, analysis, figures, interpretation, conclusions, and contribution placeholders. |

Legacy notebooks in `notebooks/legacy/` include earlier DASH, Superfit, spectral reduction, normalization, diagnostics, and TARDIS experiments. They are useful for provenance but not for final reproducibility.

## Current Analysis Status

- Completed first-pass automation: multi-epoch spectral sequences, type-aware minimum-trough line velocity measurements, pEW/non-parametric FWHM/depth, empirical line-systematics columns, blackbody color-temperature proxy with context QC, host-line indices with instance/unique counts, target-level summary, and report-ready figures.
- Still partial: TARDIS modeling is qualitative only and not an automatic physical fitter, but the top-level 03 workflow is now self-contained from current project data/products.
- Still partial: host extinction/environment diagnostics are rough line-index outputs, not fully flux-calibrated environmental measurements.
- Still required before final science claims: inspect `line_diagnostics_qc.csv` or `<RUN_TAG>_line_diagnostics_qc.csv`, especially `qc_flag=check`, and maintain a final adopted-measurements table for values used in reports/slides.

## Testing

```bash
conda activate astro_env
python scripts/fetch_target_params.py
# or
python -m src.pipeline
# Auxiliary data (light curves + spectra):
python scripts/fetch_aux_data.py
# or
python -m src.fetch_aux_data
# Current batch science products:
python scripts/build_analysis_products.py
```

## Do NOT

- Commit `.env` or any file with credentials
- Add `api_key` to TNS form requests in user mode (401 error)
- Use `Lim. Mag./Flux` column for target magnitude
- Rely on TNS Get Object API without bot credentials
- Hardcode site coordinates in pipeline code (use config)
- Use TARDIS v1 API (`sim.model`, `sim.transport.spectrum`, `spectrum.flux`) — this project uses TARDIS v2 dev (see API notes above)
- Reinterpret `phase_days` as maximum-light phase without adding reliable peak-date/light-curve metadata first.
- Store atomic data outside project `data/` directory — TARDIS internal config must point to project data
- Use relative paths for `atom_data` in TARDIS YAML — prefer absolute path resolved from project root
- Overwrite baseline TARDIS tuning runs for exploratory experiments; use `--run-label` unless intentionally replacing the baseline.
- Use `--adopt-best` solely from the numeric score without inspecting the comparison PNG and checking whether a final-packet rerun preserves the improvement.
