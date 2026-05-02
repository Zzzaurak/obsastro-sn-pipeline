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

## Conda Environments

| Env | Python | Used For |
|-----|--------|----------|
| `astro_env` | 3.10 | All functionality: TNS pipeline, observability, finder charts, light curves, spectrum download/plotting, [astrodash](https://github.com/daniel-murray/astrodash) classification |

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
