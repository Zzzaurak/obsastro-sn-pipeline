from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from .coordinates import deg_to_dms, deg_to_hms, sexagesimal_to_deg
from .finder import generate_finder_chart
from .target import Target
from .utils import (
    clean_filename,
    download_file,
    info,
    load_env_file,
    mkdir,
    normalize_tns_name,
    save_text,
    tns_auth_headers,
    warn,
)

TNS_BASE_URL = "https://www.wis-tns.org"
TNS_CATALOG_URL = f"{TNS_BASE_URL}/system/files/tns_public_objects/tns_public_objects.csv.zip"
TNS_OBJECT_URL = f"{TNS_BASE_URL}/object"


# ═══════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════

def load_pipeline_config(config_path: str = "configs/sn_parameter.json") -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        warn(f"Config file not found: {path}")
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    flat: dict[str, Any] = {}
    for section in ("observing", "tns", "output"):
        for k, v in (raw.get(section) or {}).items():
            flat[k] = v

    defaults: dict[str, Any] = {
        "target": "", "date": dt.date.today().isoformat(),
        "site_lat": 40.0, "site_lon": 116.3, "site_elevation_m": 50.0,
        "tz_offset": 8.0, "min_alt": 30.0, "min_visible_hours": 0.5,
        "sun_alt_limit": -12.0, "time_step_minutes": 10,
        "enabled": True, "download_photometry": True, "download_files": True,
        "pause_seconds": 6.5, "out_dir": "output",
        "report_file": "sn_report_{date}_{target}.txt",
        "finder_fov_arcmin": 10.0,
    }
    for k, v in defaults.items():
        flat.setdefault(k, v)
    return flat


# ═══════════════════════════════════════════════════════════════
#  TNS public catalog (user-mode: CSV download)
# ═══════════════════════════════════════════════════════════════

def _get_catalog_cache_dir() -> Path:
    return Path("data")


def _get_catalog_csv_path() -> Path:
    return _get_catalog_cache_dir() / "tns_public_objects.csv"


def ensure_catalog() -> Path | None:
    """Download & cache the TNS public object catalog (CSV). Returns path to CSV."""
    csv_path = _get_catalog_csv_path()
    if csv_path.exists():
        mtime = dt.datetime.fromtimestamp(csv_path.stat().st_mtime)
        age_hours = (dt.datetime.now() - mtime).total_seconds() / 3600
        if age_hours < 24:
            info(f"Using cached TNS catalog ({age_hours:.0f}h old)")
            return csv_path
        info("Catalog older than 24h, re-downloading...")

    hdrs = tns_auth_headers()
    if not hdrs:
        warn("No TNS credentials — cannot download catalog")
        return None

    zip_path = _get_catalog_cache_dir() / "tns_public_objects.csv.zip"
    info("Downloading TNS public catalog...")
    try:
        req = urllib.request.Request(TNS_CATALOG_URL, headers=hdrs)
        with urllib.request.urlopen(req, timeout=120) as resp:
            mkdir(zip_path.parent)
            zip_path.write_bytes(resp.read())
    except Exception as exc:
        warn(f"Catalog download failed: {exc}")
        return None

    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            warn("Catalog ZIP contains no CSV")
            return None
        mkdir(csv_path.parent)
        csv_path.write_text(zf.read(names[0]).decode("utf-8", "replace"), encoding="utf-8")

    info(f"Catalog cached → {csv_path}")
    return csv_path


def _parse_catalog(csv_path: Path) -> list[dict[str, str]]:
    text = csv_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = 1 if lines and not lines[0].startswith('"') else 0
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    return [row for row in reader if row]


def lookup_catalog_target(catalog_rows: list[dict[str, str]], target_name: str) -> dict[str, str] | None:
    """Find a target in the TNS catalog by name."""
    search = normalize_tns_name(target_name).lower()
    for row in catalog_rows:
        full_name = f"{row.get('name_prefix', '')}{row.get('name', '')}"
        if full_name.lower() == search or (row.get("name") or "").lower() == search:
            return row
    # Try with SN/AT prefix
    for row in catalog_rows:
        full_name = f"{row.get('name_prefix', '')}{row.get('name', '')}"
        if full_name.upper() == target_name.upper().replace(" ", ""):
            return row
    # Try internal names
    for row in catalog_rows:
        internals = (row.get("internal_names") or "").split(",")
        for iname in internals:
            if iname.strip().upper() == target_name.upper().replace(" ", ""):
                return row
    return None


def build_target_from_catalog(row: dict[str, str]) -> Target:
    """Build a Target from a TNS catalog row."""
    prefix = row.get("name_prefix", "") or "SN"
    name = row.get("name", "") or ""
    full_name = f"{prefix} {name}".strip() if name else f"{prefix}{name}"

    target = Target(name=full_name)
    target.iau_name = full_name
    target.source_ids.add("TNS")

    # Type
    obj_type = (row.get("type") or "").strip("- ")
    target.object_type = obj_type or "Unclassified"

    # Coordinates (catalog has ra/declination in decimal degrees)
    ra_str = row.get("ra", "")
    dec_str = row.get("declination", "")
    try:
        target.ra_deg = float(ra_str)
    except (ValueError, TypeError):
        target.ra_deg = sexagesimal_to_deg(ra_str, is_ra=True)
    try:
        target.dec_deg = float(dec_str)
    except (ValueError, TypeError):
        target.dec_deg = sexagesimal_to_deg(dec_str, is_ra=False)

    target.ra_hms = deg_to_hms(target.ra_deg)
    target.dec_dms = deg_to_dms(target.dec_deg)

    # Discovery
    discovery = row.get("discoverydate", "") or row.get("discovery_date", "")
    target.discovery_date = discovery

    # Discovery magnitude
    dmag = row.get("discoverymag", "")
    if dmag:
        try:
            target.mag = round(float(dmag), 2)
            target.mag_filter = row.get("discmagfilter", "").strip()
            if target.mag_filter == "1":
                target.mag_filter = row.get("filter", "").strip()
            target.mag_note = discovery
        except (ValueError, TypeError):
            pass

    # Redshift
    z = row.get("redshift", "")
    if z and z not in ("None", "", "null"):
        target.redshift = z

    # Host
    host = row.get("hostname", "") or row.get("host", "")
    if host and host != "None":
        target.host = host

    target.finalize()
    return target


# ═══════════════════════════════════════════════════════════════
#  TNS object page scraping (for latest photometry + finder chart)
# ═══════════════════════════════════════════════════════════════

def fetch_tns_object_page(tns_name: str) -> str | None:
    """Fetch the TNS object page HTML."""
    url = f"{TNS_OBJECT_URL}/{tns_name}"
    info(f"Fetching TNS page: {url}")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:
        warn(f"TNS page fetch failed: {exc}")
        return None


def _cell_text(cell: str) -> str:
    return re.sub(r"<[^>]+>", "", cell).replace("&amp;", "&").replace("&nbsp;", " ").strip()


def _parse_tables(html: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for t_m in re.finditer(r"<table[^>]*>(.*?)</table>", html, re.DOTALL | re.I):
        rows: list[list[str]] = []
        for r_m in re.finditer(r"<tr[^>]*>(.*?)</tr>", t_m.group(1), re.DOTALL | re.I):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r_m.group(1), re.DOTALL | re.I)
            rows.append([_cell_text(c) for c in cells])
        tables.append(rows)
    return tables


def update_target_photometry_from_page(target: Target, html: str) -> None:
    """Scrape the TNS object page for a more recent magnitude."""
    tables = _parse_tables(html)
    best_jd = -1.0
    best_mag = None
    best_filter = ""
    best_date = ""

    for rows in tables:
        if not rows:
            continue
        header = rows[0]
        if "Mag. / Flux" not in " ".join(header):
            continue
        jd_col = mag_col = filt_col = date_col = -1
        for i, h in enumerate(header):
            hl = h.lower()
            if hl == "jd":
                jd_col = i
            elif "mag" in hl and "lim" not in hl:
                mag_col = i
            elif hl == "filter":
                filt_col = i
            elif "obs-date" in hl or "obs date" in hl:
                date_col = i
        if mag_col < 0:
            continue
        for row in rows[1:]:
            if len(row) <= mag_col:
                continue
            mag_str = row[mag_col]
            if not mag_str:
                continue
            # skip non-detection rows
            if row and len(row) > 0:
                last_cell = row[-1].lower()
                if "non detection" in last_cell:
                    continue
            try:
                mag = float(mag_str)
            except (ValueError, TypeError):
                continue
            jd = 0.0
            if 0 <= jd_col < len(row):
                try:
                    jd = float(row[jd_col])
                except (ValueError, TypeError):
                    pass
            if jd > best_jd:
                best_jd = jd
                best_mag = mag
                best_filter = row[filt_col] if 0 <= filt_col < len(row) else ""
                best_date = row[date_col] if 0 <= date_col < len(row) else ""

    if best_mag is not None:
        target.mag = round(best_mag, 2)
        target.mag_filter = best_filter
        target.mag_note = best_date


def find_page_image_urls(html: str) -> list[str]:
    """Find image URLs on the TNS page that could be finder charts."""
    urls = []
    # First check <img> tags
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I):
        src = m.group(1)
        if src.startswith("/"):
            src = TNS_BASE_URL + src
        fname = src.split("/")[-1].lower()
        if any(kw in fname for kw in ("finder", "chart", "finding", "atrep", "field", "stamp")):
            urls.append(src)
    if not urls:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I):
            src = m.group(1)
            if src.startswith("/"):
                src = TNS_BASE_URL + src
            if re.search(r"atrep_\d+.*\.(png|jpg|jpeg)", src, re.I):
                urls.append(src)
    # Also check <a> links to images (TNS stores discovery report images via links)
    if not urls:
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+\.(?:png|jpg|jpeg))["\']', html, re.I):
            href = m.group(1)
            if href.startswith("/"):
                href = TNS_BASE_URL + href
            urls.append(href)
    return urls


# ═══════════════════════════════════════════════════════════════
#  Observability
# ═══════════════════════════════════════════════════════════════

def compute_observing_window(
    target: Target,
    date_str: str,
    *,
    site_lat: float, site_lon: float, site_elevation_m: float,
    tz_offset: float, time_step_minutes: int,
    sun_alt_limit: float, min_alt: float,
) -> dict[str, Any]:
    ra = target.ra_deg
    dec = target.dec_deg
    if ra is None or dec is None:
        return _empty_window()

    local_date = dt.date.fromisoformat(date_str)
    tz = dt.timezone(dt.timedelta(hours=tz_offset))
    start_local = dt.datetime.combine(local_date, dt.time(18, 0), tzinfo=tz)
    end_local = dt.datetime.combine(local_date + dt.timedelta(days=1), dt.time(6, 0), tzinfo=tz)
    start_utc = start_local.astimezone(dt.timezone.utc)
    end_utc = end_local.astimezone(dt.timezone.utc)

    step = dt.timedelta(minutes=time_step_minutes)
    times_dt: list[dt.datetime] = []
    cur = start_utc
    while cur <= end_utc:
        times_dt.append(cur)
        cur += step

    alts: list[float] = []
    sun_alts: list[float] = []

    try:
        from astropy import units as u
        from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_sun
        from astropy.time import Time
        from astropy.utils import iers

        iers.conf.auto_download = False
        times = Time(times_dt)
        location = EarthLocation(
            lat=site_lat * u.deg, lon=site_lon * u.deg, height=site_elevation_m * u.m,
        )
        frame = AltAz(obstime=times, location=location)
        sun_alts = get_sun(times).transform_to(frame).alt.deg.tolist()
        coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
        alts = coord.transform_to(frame).alt.deg.tolist()
    except Exception:
        from .time_utils import altitude_deg, datetime_to_jd, sun_ra_dec_approx
        jds = [datetime_to_jd(t) for t in times_dt]
        sun_data = [sun_ra_dec_approx(jd) for jd in jds]
        sun_alts = [
            altitude_deg(sra, sdec, jd, site_lat, site_lon)
            for (sra, sdec), jd in zip(sun_data, jds)
        ]
        alts = [altitude_deg(ra, dec, jd, site_lat, site_lon) for jd in jds]

    dark_mask = [sa < sun_alt_limit for sa in sun_alts]
    visible_mask = [a > min_alt and d for a, d in zip(alts, dark_mask)]

    if not any(visible_mask):
        return _empty_window()

    first_idx = next(i for i, v in enumerate(visible_mask) if v)
    last_idx = next(i for i in range(len(visible_mask) - 1, -1, -1) if visible_mask[i])

    start_lt = times_dt[first_idx].astimezone(tz)
    end_lt = times_dt[last_idx].astimezone(tz)
    best_idx = max(range(len(alts)), key=lambda i: alts[i])
    max_alt_time_lt = times_dt[best_idx].astimezone(tz)

    duration_h = round((last_idx - first_idx + 1) * time_step_minutes / 60.0, 2)
    visible_h = round(sum(1 for v in visible_mask if v) * time_step_minutes / 60.0, 2)

    return {
        "window_start": start_lt.strftime("%H:%M"),
        "window_end": end_lt.strftime("%H:%M"),
        "max_alt": round(float(alts[best_idx]), 1),
        "max_alt_time": max_alt_time_lt.strftime("%H:%M"),
        "duration_hours": duration_h,
        "visible_hours": visible_h,
        "observable": True,
    }


def _empty_window() -> dict[str, Any]:
    return {
        "window_start": "", "window_end": "",
        "max_alt": None, "max_alt_time": "",
        "duration_hours": 0.0, "visible_hours": 0.0,
        "observable": False,
    }


# ═══════════════════════════════════════════════════════════════
#  Aladin Lite
# ═══════════════════════════════════════════════════════════════

def generate_aladin_lite_url(ra_deg: float | None, dec_deg: float | None, fov_arcmin: float = 10.0) -> str:
    if ra_deg is None or dec_deg is None:
        return ""
    fov_deg = fov_arcmin / 60.0
    return (
        f"https://aladin.cds.unistra.fr/AladinLite/"
        f"?target={ra_deg:.5f}%20{dec_deg:.5f}"
        f"&fov={fov_deg:.4f}"
        f"&survey=P%2FDSS2%2Fcolor"
    )


# ═══════════════════════════════════════════════════════════════
#  Report
# ═══════════════════════════════════════════════════════════════

def format_report(
    target: Target,
    date_str: str,
    window: dict[str, Any],
    tz_offset: float,
    tns_finder_status: str,
    astroquery_finder_status: str,
    aladin_url: str,
) -> str:
    tz_hr = tz_offset
    tz_label = "CST" if tz_hr == 8 else f"UTC{tz_offset:+}"

    disc_display = "unknown"
    if target.discovery_date:
        disc_display = _format_date_short(target.discovery_date)
    name_with_disc = f"{target.name} ({disc_display})" if disc_display != "unknown" else target.name

    obj_type = target.object_type or "Unclassified"
    ra_hms = target.ra_hms or "N/A"
    dec_dms = target.dec_dms or "N/A"
    ra_deg = f"{target.ra_deg:.5f}" if target.ra_deg is not None else "N/A"
    dec_deg = f"{target.dec_deg:.5f}" if target.dec_deg is not None else "N/A"

    mag_line = "N/A"
    if target.mag is not None:
        parts = [f"{target.mag:.1f}"]
        if target.mag_filter:
            parts.append(target.mag_filter)
        if target.mag_note:
            parts.append(f"({_format_date_short(target.mag_note)})")
        mag_line = " ".join(parts)

    if window["observable"]:
        start_str = window["window_start"]
        end_str = window["window_end"]
        if end_str < start_str:
            end_str = f"{end_str} (+1d)"
        dur_h = int(window["duration_hours"])
        dur_m = int((window["duration_hours"] - dur_h) * 60)
        dur_str = f"{dur_h}h {dur_m:02d}m" if dur_h > 0 else f"{dur_m}m"
        max_alt_str = f"{window['max_alt']:.1f} deg at {window['max_alt_time']} {tz_label}"
        window_lines = [
            f"  Start:         {start_str} {tz_label}",
            f"  End:           {end_str} {tz_label}",
            f"  Duration:      {dur_str}",
            f"  Max Altitude:  {max_alt_str}",
        ]
    else:
        window_lines = ["  Not observable on this night (below altitude limit during dark time)"]

    extra_lines = []
    if target.host:
        extra_lines.append(f"Host Galaxy:  {target.host}")
    if target.redshift:
        extra_lines.append(f"Redshift:     {target.redshift}")

    lines = [
        "=" * 44,
        f"  SN Observing Report — {date_str}",
        "=" * 44,
        "",
        f"Target:       {name_with_disc}",
        f"Type:         {obj_type}",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    lines.extend([
        "",
        f"RA  (J2000):  {ra_hms}",
        f"Dec (J2000):  {dec_dms}",
        f"RA  (deg):    {ra_deg}",
        f"Dec (deg):    {dec_deg}",
        "",
        f"Mag:          {mag_line}",
        "",
        f"Observing Window ({date_str}):",
    ])
    lines.extend(window_lines)
    lines.extend(["", "Finding Chart:"])

    if tns_finder_status.startswith("downloaded"):
        lines.append(f"  TNS:            {tns_finder_status}")
    elif tns_finder_status.startswith("not available"):
        lines.append(f"  TNS:            not available for this target")
    elif tns_finder_status.startswith("error"):
        lines.append(f"  TNS:            download failed — {tns_finder_status}")
    else:
        lines.append(f"  TNS:            {tns_finder_status}")

    if astroquery_finder_status.startswith("generated"):
        lines.append(f"  Astroquery:     {astroquery_finder_status}")
    elif astroquery_finder_status.startswith("error"):
        lines.append(f"  Astroquery:     failed — {astroquery_finder_status}")
    elif astroquery_finder_status.startswith("skipped"):
        lines.append(f"  Astroquery:     skipped (no coordinates)")
    else:
        lines.append(f"  Astroquery:     {astroquery_finder_status}")

    if aladin_url:
        lines.append(f"  Aladin Lite:    {aladin_url}")
    lines.extend(["", "=" * 44])
    return "\n".join(lines) + "\n"


def _format_date_short(date_str: str) -> str:
    date_str = date_str.strip()
    date_str = re.sub(r"\.\d+$", "", date_str)
    # Each format maps to the expected string length of the date prefix
    formats = [
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%dT%H:%M:%S", 19),
        ("%Y-%m-%d", 10),
    ]
    for fmt, expect_len in formats:
        if len(date_str) >= expect_len:
            try:
                d = dt.datetime.strptime(date_str[:expect_len], fmt)
                return f"{d.month}/{d.day}"
            except ValueError:
                continue
    parts = date_str.split("-")
    if len(parts) >= 3:
        try:
            return f"{int(parts[1])}/{int(parts[2])}"
        except ValueError:
            pass
    return date_str


# ═══════════════════════════════════════════════════════════════
#  Pipeline
# ═══════════════════════════════════════════════════════════════

def run_pipeline(config_path: str | None = None) -> int:
    if config_path is None:
        config_path = "configs/sn_parameter.json"

    load_env_file()
    cfg = load_pipeline_config(config_path)
    if not cfg:
        warn("Cannot proceed without config")
        return 1

    target_name = cfg.get("target", "").strip()
    if not target_name:
        warn("No target specified in config")
        return 1

    date_str = cfg.get("date", dt.date.today().isoformat())
    out_base = Path(cfg.get("out_dir", "output"))
    pause_s = float(cfg.get("pause_seconds", 2.0))

    info(f"Pipeline: target={target_name}  date={date_str}")

    # ── Step 1: Download/load catalog → get basic target info ──
    csv_path = ensure_catalog()
    if not csv_path:
        return 1

    catalog = _parse_catalog(csv_path)
    row = lookup_catalog_target(catalog, target_name)
    if not row:
        warn(f"Target '{target_name}' not found in TNS catalog")
        return 1

    target = build_target_from_catalog(row)
    info(f"Catalog data: {target.name}  type={target.object_type}  "
         f"ra={target.ra_hms}  dec={target.dec_dms}  mag={target.mag}")

    # ── Step 2: Scrape object page for latest photometry + finder chart ──
    tns_name = row.get("name", "") or normalize_tns_name(target_name)
    html = fetch_tns_object_page(tns_name)
    if html:
        update_target_photometry_from_page(target, html)
        if target.mag is not None:
            info(f"Updated mag from page: {target.mag} {target.mag_filter} ({target.mag_note})")

        # Finder chart images from page
        image_urls = find_page_image_urls(html)
    else:
        image_urls = []

    # ── Step 3: Compute observability ──
    window = compute_observing_window(
        target, date_str,
        site_lat=float(cfg["site_lat"]),
        site_lon=float(cfg["site_lon"]),
        site_elevation_m=float(cfg.get("site_elevation_m", 50.0)),
        tz_offset=float(cfg["tz_offset"]),
        time_step_minutes=int(cfg["time_step_minutes"]),
        sun_alt_limit=float(cfg["sun_alt_limit"]),
        min_alt=float(cfg["min_alt"]),
    )
    if window["observable"]:
        info(f"Window: {window['window_start']}–{window['window_end']} "
             f"(max alt {window['max_alt']:.1f}°)")

    # ── Step 4: Create per-target output directory & download finder charts ──
    clean_tgt = clean_filename(target_name)
    out_dir = out_base / clean_tgt

    aladin_url = generate_aladin_lite_url(
        target.ra_deg, target.dec_deg,
        fov_arcmin=float(cfg.get("finder_fov_arcmin", 10.0)),
    )

    # 4a. TNS finder chart
    tns_finder_status = "not attempted"
    if cfg.get("download_files", True) and image_urls:
        downloaded = False
        for img_url in image_urls[:3]:
            fname = img_url.split("/")[-1].split("?")[0]
            dest = out_dir / f"finder_TNS_{fname}"
            info(f"Downloading TNS finder: {img_url}")
            if download_file(img_url, dest, timeout=60):
                tns_finder_status = f"downloaded → {dest}"
                downloaded = True
                break
        if not downloaded:
            tns_finder_status = "error: download failed"
    elif not image_urls:
        tns_finder_status = "not available: no finder image on TNS page"
    else:
        tns_finder_status = "disabled in config"

    # 4b. Astroquery finder chart
    astroquery_finder_status = "not attempted"
    if cfg.get("download_files", True) and target.ra_deg is not None and target.dec_deg is not None:
        chart_path = generate_finder_chart(
            ra_deg=target.ra_deg,
            dec_deg=target.dec_deg,
            target_name=target.name,
            output_dir=out_dir,
            fov_arcmin=float(cfg.get("finder_fov_arcmin", 10.0)),
        )
        if chart_path:
            astroquery_finder_status = f"generated → {chart_path}"
        else:
            astroquery_finder_status = "error: generation failed"
    else:
        astroquery_finder_status = "skipped: no coordinates"

    # ── Step 5: Generate & save report ──
    report = format_report(
        target, date_str, window, float(cfg["tz_offset"]),
        tns_finder_status, astroquery_finder_status, aladin_url,
    )

    report_tpl = str(cfg.get("report_file", "sn_report_{date}_{target}.txt"))
    report_file = report_tpl.replace("{date}", date_str).replace("{target}", clean_tgt)
    report_path = out_dir / report_file
    save_text(report_path, report)
    info(f"Report saved → {report_path}")

    print(report)
    return 0


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(run_pipeline(config_path))
