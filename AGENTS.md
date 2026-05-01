# AGENTS.md — AI Agent Instructions

## Project Overview

Supernova observing pipeline that queries TNS (Transient Name Server) for target data, computes nightly observability windows, and generates observing reports with finder charts.

## Module Map

| File | Role | Entry Points |
|------|------|-------------|
| `src/pipeline.py` | **Core orchestrator**: config loading, TNS data acquisition (catalog + page scraping), observability calculation, finder chart download, report generation | `run_pipeline(config_path)` |
| `scripts/fetch_target_params.py` | **CLI wrapper**: invokes `python -m src.pipeline` from project root | `main()` |
| `src/utils.py` | HTTP client, TNS credentials manager (`TnsCredentials`), `.env` loader, CSV I/O, rate-limit tracking | `load_env_file()`, `get_tns_credentials()`, `tns_auth_headers()` |
| `src/tns.py` | Bot-mode TNS API integration (Get Object, Get File, public catalog download) | `download_tns_catalog()`, `fetch_tns_object()`, `download_tns_spectra_files()` |
| `src/target.py` | `Target` dataclass with ~25 fields (coordinates, magnitudes, observability, URLs) | `Target`, `merge_targets()`, `filter_targets()` |
| `src/observability.py` | Nightly altitude/visibility computation (astropy primary, pure-Python fallback) | `compute_observability()`, `compute_observability_simple()` |
| `src/coordinates.py` | Coordinate format conversion (sexagesimal ↔ decimal degrees) | `deg_to_hms()`, `deg_to_dms()`, `sexagesimal_to_deg()` |
| `src/time_utils.py` | Julian Date conversion, GMST, solar position (low-precision), altitude formula | `datetime_to_jd()`, `altitude_deg()`, `sun_ra_dec_approx()` |
| `src/config.py` | JSON config loading with flattening, defaults, type coercion | `load_config()`, `flatten_config()` |

## Configuration

### `configs/sn_parameter.json`

Three sections, all flattened at load time:

- **`observing`**: `target`, `date`, `site_lat`, `site_lon`, `site_elevation_m`, `tz_offset`, `min_alt` (airmass≤2 threshold), `sun_alt_limit` (twilight), `time_step_minutes`
- **`tns`**: `enabled`, `download_files` (finder chart), `pause_seconds`
- **`output`**: `out_dir`, `report_file` (template with `{date}` and `{target}` placeholders), `finder_fov_arcmin`

### `.env`

```env
TNS_USER_ID=4299
TNS_USER_NAME=Zzzaurak
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

## Observability

`compute_observing_window()`:
- Time range: 18:00 local → 06:00 (+1d) local
- Step: `time_step_minutes` from config
- Primary: astropy `AltAz` + `get_sun` (requires IERS data)
- Fallback: pure-Python `altitude_deg()` + `sun_ra_dec_approx()`
- Returns dict: `{window_start, window_end, max_alt, max_alt_time, duration_hours, visible_hours, observable}`

## Output

- **Report**: `output/sn_report_{date}_{target}.txt` — plain text with target info, observing window, finder chart status
- **Finder chart**: `output/images/{target}_finder_{filename}` — downloaded from TNS if available
- **Catalog cache**: `data/tns_public_objects.csv` (+ `.zip`)

## Important Notes

- `.env` MUST NOT be committed (contains TNS credentials)
- `output/` and `data/` are gitignored
- TNS Get Object API requires **bot** credentials → pipeline uses public catalog + page scraping instead
- The IERS warning about leap seconds is harmless (set `iers.conf.auto_download = False`)
- Target name normalization: strips `SN`/`AT` prefix, removes spaces for TNS lookup
- Config key flattening: nested dict sections (`observing`, `tns`, `output`) are flattened into a single dict; keys are `lower_snake_case`

## Testing

```bash
conda activate tardis
python scripts/fetch_target_params.py
# or
python -m src.pipeline
```

## Do NOT

- Commit `.env` or any file with credentials
- Add `api_key` to TNS form requests in user mode (401 error)
- Use `Lim. Mag./Flux` column for target magnitude
- Rely on TNS Get Object API without bot credentials
- Hardcode site coordinates in pipeline code (use config)
