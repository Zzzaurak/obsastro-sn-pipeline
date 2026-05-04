# AGENTS.md — AI Agent Instructions

## Project Overview

Supernova observing pipeline that queries TNS (Transient Name Server) for target data, computes nightly observability windows, and generates observing reports with finder charts.

## Module Map

| File | Role | Entry Points |
|------|------|-------------|
| `src/pipeline.py` | **Core orchestrator**: config loading, TNS data acquisition (catalog + page scraping), observability calculation, finder chart download, report generation | `run_pipeline(config_path)` |
| `src/finder.py` | **Finder chart generator**: astroquery SkyView query + matplotlib WCS plot with crosshair, scale bar | `generate_finder_chart()` |
| `scripts/fetch_target_params.py` | **CLI wrapper**: invokes `python -m src.pipeline` from project root | `main()` |
| `src/fetch_aux_data.py` | **Aux data orchestrator**: Lasair light curve + WISeREP spectra acquisition | `run(config_path)` |
| `src/lasair.py` | **Lasair light curve**: ZTF light curve download, CSV export, matplotlib plot with filters | `fetch_lasair_object()`, `plot_lightcurve()` |
| `src/wiserep.py` | **WISeREP spectra**: spectrum metadata search, file download, ASCII parsing, plotting | `fetch_spectra_metadata()`, `download_spectrum_file()`, `plot_spectra()` |
| `src/utils.py` | HTTP client, TNS credentials manager (`TnsCredentials`), `.env` loader, CSV I/O, rate-limit tracking | `load_env_file()`, `get_tns_credentials()`, `tns_auth_headers()` |
| `src/tns.py` | Bot-mode TNS API integration (Get Object, Get File, public catalog download) | `download_tns_catalog()`, `fetch_tns_object()`, `download_tns_spectra_files()` |
| `src/target.py` | `Target` dataclass with ~25 fields (coordinates, magnitudes, observability, URLs) | `Target`, `merge_targets()`, `filter_targets()` |
| `src/observability.py` | Nightly altitude/visibility computation (astropy primary, pure-Python fallback) | `compute_observability()`, `compute_observability_simple()` |
| `src/coordinates.py` | Coordinate format conversion (sexagesimal ↔ decimal degrees) | `deg_to_hms()`, `deg_to_dms()`, `sexagesimal_to_deg()` |
| `src/time_utils.py` | Julian Date conversion, GMST, solar position (low-precision), altitude formula | `datetime_to_jd()`, `altitude_deg()`, `sun_ra_dec_approx()` |
| `src/config.py` | JSON config loading with flattening, defaults, type coercion | `load_config()`, `flatten_config()` |
| `scripts/download_tardis_atom_data.py` | **TARDIS atomic data downloader**: downloads `kurucz_cd23_chianti_H_He_latest.h5` into `data/`, updates `~/.astropy/config/tardis_internal_config.yml` to point to project `data/` | `download_atom_data()` |

## Configuration

### `configs/sn_parameter.json`

Five sections, all flattened at load time:

- **`observing`**: `target`, `date`, `site_lat`, `site_lon`, `site_elevation_m`, `tz_offset`, `min_alt` (airmass≤2 threshold), `sun_alt_limit` (twilight), `time_step_minutes`
- **`tns`**: `enabled`, `download_files` (finder chart), `pause_seconds`
- **`lasair`**: `lasair_enabled`
- **`wiserep`**: `wiserep_enabled`
- **`output`**: `out_dir`, `report_file` (template with `{date}` and `{target}` placeholders), `finder_fov_arcmin`

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
| `montecarlo` | no | `seed`, `no_of_packets`, `iterations`, `last_no_of_packets`, `no_of_virtual_packets`, `convergence_strategy` (damped with damping_constant, threshold, lock_t_inner_cycles, t_inner_update_exponent) |

**Density profile types:**
- `branch85_w7` — 7th-order polynomial fit to W7 Ia model, parametrised by time_explosion only (w7_time_0/w7_rho_0/w7_v_0 are fixed)
- `exponential` — ρ(v) = ρ₀·exp(-v/v₀), needs `rho_0`, `v_0`, optional `time_0`
- `power_law` — ρ(v) = ρ₀·(v/v₀)^n, needs `rho_0`, `v_0`, `exponent`
- `uniform` — Constant density, needs `value`

**criterion for velocity range:** inner boundary ~0.6×v_phot, outer boundary ~1.3×v_exp. For Ia, v_phot ≈ 0.7×v_line.

**Notebook auto-generates** per-target config at `configs/tardis/{TARGET}.yml` by overriding luminosity, time_explosion, velocity range, and (for non-Ia) abundances from the base template.

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
- **TARDIS simulation spectrum**: `output/{target}/tardis/tardis_spectrum_{target}.dat` — 2-column ASCII (rest-frame wavelength A, luminosity density erg/s/A); 10000 points on 500-20000 A grid
- **TARDIS per-target config**: `output/{target}/tardis/tardis_config_{target}.yml` — copy of the YAML config used for reproducibility

## Conda Environments

| Env | Python | Used For |
|-----|--------|----------|
| `astro_env` | 3.10 | Main pipeline: TNS query, observability, finder charts, light curves, spectrum download/plotting, [astrodash](https://github.com/daniel-murray/astrodash) classification |
| `tardis` | 3.13 | TARDIS Monte Carlo radiative transfer (v2 dev, installed from local repo `~/THU/astronomy/tardis/repo`); spectrum simulation and model-observation comparison. Also requires `tardisbase` package. |
| `py314` | ≥3.14 | Development/testing |

**Requirements**: astrodash needs `numpy < 1.24` and `tensorflow < 2.16`. The `envs/environment_astro_env.yml` file pins these constraints.

**CRITICAL — numpy pinning**: numpy MUST be `1.23.5` (the latest `< 1.24`). Even though conda installs `numpy<1.24`, TF's pip dependency `numpy>=1.23.5,<2.0.0` will upgrade numpy to `1.26.x` unless numpy is ALSO pinned in the pip section of the YAML as `numpy==1.23.5`. Always verify with `D:\Anaconda\envs\astro_env\python.exe -c "import numpy; print(numpy.__version__)"` after env creation.

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

The `notebooks/tardis_simulation.ipynb` notebook (runs in `tardis` kernel) implements:

1. **Load observed spectrum** — reads `output/{target}/spectrum/spectrum_*.dat` (2-column: wavelength_A, flux)
2. **Set target parameters** — user provides redshift, SN type (Ia/II/Ibc), DASH age (days from peak), DASH velocity (km/s). Notebook auto-computes:
   - `epoch_days` = dash_age + 18 (Ia) or +15 (II) — time since explosion
   - `luminosity_requested` — from apparent magnitude + luminosity distance via Planck18 cosmology → log(Lsun)
   - `velocity start/stop` — inner boundary ~0.7×v_phot, outer ~1.3×v_exp
3. **Build YAML config** — loads `configs/tardis/base_Ia.yml` template, overrides supernova/model/velocity params, adjusts abundances for non-Ia types, writes to `configs/tardis/{TARGET}.yml`
4. **Check atomic data** — verifies `data/kurucz_cd23_chianti_H_He_latest.h5` exists (~212 MB); if missing, instructs user to run `scripts/download_tardis_atom_data.py`
5. **Run simulation** — `run_tardis(config_path, show_convergence_plots=False, log_level="WARNING")` → returns `Simulation` object
6. **Compare spectra** — de-redshifts observed spectrum to rest frame, normalises both, plots overlay + residual in 2-panel figure
7. **Save results** — writes TARDIS spectrum `.dat` and config copy to `output/{target}/tardis/`

**Notebook metadata:** kernel `tardis`, display_name `Python (tardis)`. Python files in `src/` are imported via `sys.path.insert(0, os.path.abspath('..'))` (not needed for TARDIS sim, but kept for potential reuse of `src/wiserep.py` plotting).

**Switching targets:** change `TARGET = "SN2026jlm"` in Cell 3. The notebook auto-detects all `.dat` files in `output/{TARGET}/spectrum/`.

## TARDIS API v2 Notes (CRITICAL)

The installed TARDIS is **v2 development version** (0.1.dev1). The API differs significantly from v1 documented online:

| Old v1 API | New v2 API |
|-----------|-----------|
| `sim.model.t_inner` | `sim.simulation_state.t_inner` |
| `sim.transport.spectrum` | `sim.spectrum_solver.spectrum_real_packets` |
| `spectrum.flux.value` | `spectrum.luminosity_density_lambda.value` (luminosity density in erg/s/A; normalise for shape comparison) |
| `Configuration.from_yaml(path)` | Same — still works |
| `run_tardis(config_path)` | Same — still works; keyword args: `show_convergence_plots`, `log_level`, `show_progress_bars` |

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

## Notebooks

### `notebooks/spectral_processing.ipynb` (astro_env kernel)
- Cell 1: imports + `plot_spectra` from `src/wiserep`
- Cell 2: load `.dat` spectrum, plot via `plot_spectra()`
- Cell 3: DASH classification (`astrodash.Classify`) — outputs type, age, redshift, best-match template; plots template overlay
- Cell 4: expansion velocity — picks characteristic line from DASH type (Si II for Ia, Ha for II, He I for Ibc), finds absorption minimum in rest-frame, computes v/c = Δλ/λ₀

### `notebooks/tardis_simulation.ipynb` (tardis kernel) — 9 cells
- **Cell 0**: markdown overview
- **Cell 1**: imports + setup (numpy, matplotlib, yaml, tardis, astropy, pathlib)
- **Cell 2** (section 1): load observed spectrum — `TARGET`, `SPECTRUM_DIR`, plot
- **Cell 3** (section 2): target parameters — `target_z`, `sn_type`, `dash_age`, `dash_vel` → computes luminosity, epoch, velocity range
- **Cell 4** (section 3): build YAML config — loads `base_Ia.yml`, overrides params, handles II/Ibc abundances, writes to `configs/tardis/{TARGET}.yml`
- **Cell 5** (section 4): check atomic data — verifies `.h5` exists in `data/`
- **Cell 6** (section 5): run TARDIS — `run_tardis()`, prints `t_inner`, extracts spectrum
- **Cell 7** (section 6): compare spectra — rest-frame correction, normalisation, 2-panel plot (overlay + residual)
- **Cell 8** (section 7): save results — writes spectrum `.dat` + config `.yml` to `output/{TARGET}/tardis/`
- **Cell 9**: next steps markdown

**Key notebook variables** that cross cells:
- `TARGET` (str), `target_z` (float), `sn_type` (str), `epoch_days` (float), `v_start`/`v_stop` (float), `lum_log_sol` (float)
- `wave_obs`, `flux_obs` — from spectrum file (Cell 2, used in Cell 7)
- `out_config_path` — pathlib Path to generated YAML (Cell 4, used in Cells 6, 8)
- `ATOM_H5_PATH` — absolute path to `.h5` (Cell 4, used in Cells 5, 6)
- `sim` — TARDIS Simulation object (Cell 6)
- `spectrum` — `sim.spectrum_solver.spectrum_real_packets` (Cell 6, used in Cell 7)
- `tardis_wave`, `tardis_flux` — extracted arrays (Cell 7, used in Cell 8)

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
```

## Do NOT

- Commit `.env` or any file with credentials
- Add `api_key` to TNS form requests in user mode (401 error)
- Use `Lim. Mag./Flux` column for target magnitude
- Rely on TNS Get Object API without bot credentials
- Hardcode site coordinates in pipeline code (use config)
- Use TARDIS v1 API (`sim.model`, `sim.transport.spectrum`, `spectrum.flux`) — this project uses TARDIS v2 dev (see API notes above)
- Store atomic data outside project `data/` directory — TARDIS internal config must point to project data
- Use relative paths for `atom_data` in TARDIS YAML — prefer absolute path resolved from project root
