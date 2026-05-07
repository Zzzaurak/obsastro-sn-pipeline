from __future__ import annotations

import csv
import datetime as dt
import html as html_lib
import io
import json
import math
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .coordinates import deg_to_dms, deg_to_hms, sexagesimal_to_deg
from .finder import generate_finder_chart
from .target import Target
from .time_utils import datetime_to_jd, jd_to_iso
from .utils import (
    clean_filename,
    first_float,
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


@dataclass(frozen=True)
class PhotometryPoint:
    jd: float
    mag: float
    filter: str = ""
    source: str = ""
    date_utc: str = ""
    err: float | None = None


@dataclass(frozen=True)
class TnsFinderCandidate:
    url: str
    label: str
    score: int
    reason: str = ""


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
    for section in ("observing", "tns", "lasair", "output"):
        for k, v in (raw.get(section) or {}).items():
            flat[k] = v

    defaults: dict[str, Any] = {
        "target": "", "date": dt.date.today().isoformat(),
        "site_lat": 40.0, "site_lon": 116.3, "site_elevation_m": 50.0,
        "tz_offset": 8.0, "min_alt": 30.0, "min_visible_hours": 0.5,
        "sun_alt_limit": -12.0, "time_step_minutes": 10,
        "moon_enabled": True, "min_moon_sep": 30.0,
        "preferred_moon_sep": 45.0, "ignore_moon_below_alt": 0.0,
        "enabled": True, "download_photometry": True, "download_files": True,
        "lasair_enabled": True,
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
            mag_jd = _date_to_jd(discovery) or 0.0
            target.mag = round(float(dmag), 2)
            target.mag_filter = _catalog_filter(row)
            target.mag_note = discovery
            target.mag_source = "TNS catalog"
            target.mag_jd = mag_jd or None
            target.mag_date_utc = discovery
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


def _catalog_filter(row: dict[str, str]) -> str:
    filt = (row.get("discmagfilter") or "").strip()
    named = (row.get("filter") or "").strip()
    if named and (not filt or filt.isdigit()):
        return named
    return filt or named


def _parse_datetime_utc(value: str) -> dt.datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    cleaned = value.replace("T", " ").replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(cleaned)
    except ValueError:
        parsed = None
        for fmt, width in (
            ("%Y-%m-%d %H:%M:%S", 19),
            ("%Y-%m-%d %H:%M", 16),
            ("%Y-%m-%d", 10),
        ):
            try:
                parsed = dt.datetime.strptime(cleaned[:width], fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _date_to_jd(value: str) -> float | None:
    parsed = _parse_datetime_utc(value)
    if parsed is None:
        return None
    return datetime_to_jd(parsed)


def _date_from_jd(jd: float) -> str:
    try:
        return jd_to_iso(jd).replace(" ", "T")[:19]
    except Exception:
        return ""


def photometry_from_catalog_row(row: dict[str, str]) -> PhotometryPoint | None:
    mag = first_float(row.get("discoverymag"))
    if mag is None:
        return None
    date_utc = (row.get("discoverydate") or row.get("discovery_date") or "").strip()
    jd = _date_to_jd(date_utc) or 0.0
    if not date_utc and jd:
        date_utc = _date_from_jd(jd)
    return PhotometryPoint(
        jd=jd,
        mag=mag,
        filter=_catalog_filter(row),
        source="TNS catalog",
        date_utc=date_utc,
    )


def apply_photometry_point(target: Target, point: PhotometryPoint) -> None:
    target.mag = round(point.mag, 2)
    target.mag_filter = point.filter
    target.mag_note = point.date_utc
    target.mag_source = point.source
    target.mag_jd = point.jd if point.jd > 0 else None
    target.mag_date_utc = point.date_utc or (_date_from_jd(point.jd) if point.jd > 0 else "")
    target.mag_err = point.err


def select_latest_photometry(points: list[PhotometryPoint]) -> PhotometryPoint | None:
    valid = [
        point for point in points
        if point.mag is not None and math.isfinite(point.mag) and point.jd > 0
    ]
    if not valid:
        return None
    return max(valid, key=lambda point: point.jd)


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


def extract_tns_page_photometry(html: str) -> list[PhotometryPoint]:
    """Scrape TNS object page detections into timestamped photometry points."""
    tables = _parse_tables(html)
    points: list[PhotometryPoint] = []

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
            date_utc = row[date_col] if 0 <= date_col < len(row) else ""
            if jd <= 0:
                jd = _date_to_jd(date_utc) or 0.0
            if not date_utc and jd > 0:
                date_utc = _date_from_jd(jd)
            points.append(PhotometryPoint(
                jd=jd,
                mag=mag,
                filter=row[filt_col] if 0 <= filt_col < len(row) else "",
                source="TNS",
                date_utc=date_utc,
            ))

    return points


def update_target_photometry_from_page(target: Target, html: str) -> None:
    """Scrape the TNS object page and apply its latest detection."""
    latest = select_latest_photometry(extract_tns_page_photometry(html))
    if latest is not None:
        apply_photometry_point(target, latest)


class _MediaTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"a", "img"}:
            return
        self.tags.append((tag.lower(), {k.lower(): v or "" for k, v in attrs}))


def _extract_html_media_tags(html: str) -> list[tuple[str, dict[str, str], str]]:
    """Return media/link tags with nearby text for finder-chart classification."""
    tags: list[tuple[str, dict[str, str], str]] = []
    tag_re = re.compile(r"<(img|a)\b[^>]*>", re.I)
    for match in tag_re.finditer(html):
        parser = _MediaTagParser()
        try:
            parser.feed(match.group(0))
        except Exception:
            continue
        if not parser.tags:
            continue
        tag, attrs = parser.tags[0]
        lo = max(0, match.start() - 700)
        hi = min(len(html), match.end() + 700)
        context = _clean_html_fragment(html[lo:hi])
        tags.append((tag, attrs, context))
    return tags


def _clean_html_fragment(fragment: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", fragment, flags=re.DOTALL | re.I)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_tns_link(url: str) -> str:
    url = html_lib.unescape((url or "").strip())
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    return urllib.parse.urljoin(TNS_BASE_URL, url)


def _image_url_kind(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host.endswith("legacysurvey.org") and path.endswith("/cutout.jpg"):
        return "legacy"
    if host.endswith("skyserver.sdss.org") and "imgcutout/getjpeg" in path:
        return "sdss"
    if path.endswith((".png", ".jpg", ".jpeg")):
        return "uploaded"
    return ""


def _has_bad_finder_context(text: str) -> bool:
    lowered = text.lower()
    bad_terms = (
        "spectra",
        "spectrum",
        "spectroscopy",
        "snid",
        "sage",
        "template",
        "best match",
        "rest wavelength",
        "obs. wavelength",
        "obs wavelength",
    )
    return any(term in lowered for term in bad_terms)


def _has_positive_finder_context(text: str, url: str) -> bool:
    combined = f"{text} {urllib.parse.urlparse(url).path}".lower()
    positive_terms = (
        "finder",
        "finding",
        "finding chart",
        "finder chart",
        "chart",
        "field",
        "sky",
        "cutout",
        "stamp",
    )
    return any(term in combined for term in positive_terms)


def _candidate_from_link(url: str, context: str) -> TnsFinderCandidate | None:
    kind = _image_url_kind(url)
    if not kind:
        return None

    if kind == "legacy":
        return TnsFinderCandidate(url, "Legacy Survey cutout", 100, "known TNS sky cutout")
    if kind == "sdss":
        return TnsFinderCandidate(url, "SDSS cutout", 95, "known TNS sky cutout")

    positive = _has_positive_finder_context(context, url)
    if not positive:
        return None
    if _has_bad_finder_context(context):
        return None
    score = 80 if re.search(r"find(?:er|ing).*chart|finder|finding", f"{context} {url}", re.I) else 65
    return TnsFinderCandidate(url, "TNS uploaded finder", score, "finder-like upload context")


def find_tns_finder_candidates(html: str) -> list[TnsFinderCandidate]:
    """Find and rank TNS page images that are likely to be real finder charts."""
    best_by_url: dict[str, TnsFinderCandidate] = {}
    for tag, attrs, context in _extract_html_media_tags(html):
        attr_names = ("src", "data-src", "href") if tag == "img" else ("href", "data-src", "src")
        for attr_name in attr_names:
            url = _normalize_tns_link(attrs.get(attr_name, ""))
            candidate = _candidate_from_link(url, context)
            if candidate is None:
                continue
            current = best_by_url.get(candidate.url)
            if current is None or candidate.score > current.score:
                best_by_url[candidate.url] = candidate

    return sorted(best_by_url.values(), key=lambda item: item.score, reverse=True)


def find_page_image_urls(html: str) -> list[str]:
    """Find ranked finder-chart image URLs on the TNS page."""
    return [candidate.url for candidate in find_tns_finder_candidates(html)]


def _image_magic_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    return ""


def _is_known_sky_cutout(candidate: TnsFinderCandidate) -> bool:
    return candidate.label.lower().startswith(("legacy survey", "sdss"))


def _white_background_fraction(image: Any) -> float:
    try:
        rgb = image.convert("RGB").resize((80, 80))
    except Exception:
        return 1.0
    raw = rgb.tobytes()
    if not raw:
        return 1.0
    white = 0
    total = len(raw) // 3
    for i in range(0, len(raw) - 2, 3):
        if raw[i] > 235 and raw[i + 1] > 235 and raw[i + 2] > 235:
            white += 1
    return white / total if total else 1.0


def validate_tns_finder_image(
    data: bytes,
    content_type: str,
    candidate: TnsFinderCandidate,
) -> tuple[bool, str]:
    """Validate that downloaded bytes are an image and likely a finder/sky chart."""
    content_type = (content_type or "").split(";")[0].strip().lower()
    magic_type = _image_magic_type(data)
    if content_type.startswith("text/") or data[:128].lstrip().lower().startswith(b"<!doctype html"):
        return False, "response is HTML/text, not an image"
    if not magic_type and not content_type.startswith("image/"):
        return False, "response is not image bytes"

    try:
        from PIL import Image
    except Exception:
        if _is_known_sky_cutout(candidate):
            return True, "accepted known sky cutout without Pillow"
        return False, "Pillow unavailable for uploaded-image validation"

    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
    except Exception as exc:
        return False, f"image decode failed: {exc}"

    if width < 80 or height < 80:
        return False, f"image too small ({width}x{height})"
    if _is_known_sky_cutout(candidate):
        return True, f"validated known sky cutout ({width}x{height})"

    white_fraction = _white_background_fraction(image)
    if white_fraction > 0.45:
        return False, f"white-background plot-like image ({white_fraction:.0%} white)"
    return True, f"validated uploaded finder-like image ({width}x{height})"


def _request_bytes_with_content_type(url: str, *, timeout: int = 60) -> tuple[bytes, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def _tns_finder_filename(candidate: TnsFinderCandidate, index: int) -> str:
    parsed = urllib.parse.urlparse(candidate.url)
    name = Path(urllib.parse.unquote(parsed.path)).name
    if not name or "." not in name:
        ext = ".jpg" if _image_url_kind(candidate.url) in {"legacy", "sdss"} else ".png"
        name = f"{clean_filename(candidate.label)}_{index}{ext}"
    return clean_filename(name)


def download_valid_tns_finder(
    candidate: TnsFinderCandidate,
    dest: Path,
    *,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Download a TNS finder candidate only if it validates as a sky/finder image."""
    if dest.exists():
        ok, reason = validate_tns_finder_image(dest.read_bytes(), "", candidate)
        if ok:
            return True, f"already exists; {reason}"

    try:
        data, content_type = _request_bytes_with_content_type(candidate.url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return False, f"download failed: {exc}"

    ok, reason = validate_tns_finder_image(data, content_type, candidate)
    if not ok:
        return False, reason
    mkdir(dest.parent)
    dest.write_bytes(data)
    return True, reason


def _ztf_filter_from_fid(fid: Any) -> str:
    try:
        fid_int = int(fid)
    except (TypeError, ValueError):
        return ""
    if fid_int == 1:
        return "g-ZTF"
    if fid_int == 2:
        return "r-ZTF"
    return ""


def extract_lasair_photometry(obj: dict[str, Any]) -> list[PhotometryPoint]:
    """Extract valid Lasair/ZTF detections and positive-flux forced points."""
    points: list[PhotometryPoint] = []

    for cand in obj.get("candidates") or []:
        mag = first_float(cand.get("magpsf"))
        if mag is None:
            continue
        jd = first_float(cand.get("jd")) or 0.0
        if jd <= 0 and cand.get("mjd") is not None:
            mjd = first_float(cand.get("mjd"))
            jd = (mjd + 2400000.5) if mjd is not None else 0.0
        if jd <= 0:
            continue
        points.append(PhotometryPoint(
            jd=jd,
            mag=mag,
            filter=_ztf_filter_from_fid(cand.get("fid")),
            source="Lasair/ZTF",
            date_utc=_date_from_jd(jd),
            err=first_float(cand.get("sigmapsf")),
        ))

    for forced in obj.get("forcedphot") or []:
        flux = first_float(forced.get("forcediffimflux"))
        zp = first_float(forced.get("magzpsci"))
        jd = first_float(forced.get("jd")) or 0.0
        if flux is None or zp is None or flux <= 0 or jd <= 0:
            continue
        try:
            mag = zp - 2.5 * math.log10(flux)
        except (ValueError, TypeError):
            continue
        err = None
        flux_unc = first_float(forced.get("forcediffimfluxunc"))
        if flux_unc is not None and flux_unc > 0:
            err = 2.5 * flux_unc / flux
        points.append(PhotometryPoint(
            jd=jd,
            mag=mag,
            filter=_ztf_filter_from_fid(forced.get("fid")),
            source="Lasair/ZTF forced",
            date_utc=_date_from_jd(jd),
            err=err,
        ))

    return points


def fetch_lasair_photometry(row: dict[str, str]) -> list[PhotometryPoint]:
    from .lasair import fetch_lasair_object, get_ztf_id_from_catalog_row

    ztf_id = get_ztf_id_from_catalog_row(row)
    if not ztf_id:
        warn(f"No ZTF ID found for Lasair lookup (internal_names={row.get('internal_names', '')})")
        return []
    obj = fetch_lasair_object(ztf_id)
    if not obj:
        return []
    return extract_lasair_photometry(obj)


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
    moon_enabled: bool = True,
    min_moon_sep: float = 30.0,
    preferred_moon_sep: float = 45.0,
    ignore_moon_below_alt: float = 0.0,
) -> dict[str, Any]:
    ra = target.ra_deg
    dec = target.dec_deg
    if ra is None or dec is None:
        return _empty_window(
            reason="missing coordinates",
            time_step_minutes=time_step_minutes,
            min_alt=min_alt,
            sun_alt_limit=sun_alt_limit,
            moon_enabled=moon_enabled,
            min_moon_sep=min_moon_sep,
            preferred_moon_sep=preferred_moon_sep,
            ignore_moon_below_alt=ignore_moon_below_alt,
        )

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
    moon_alts: list[float] | None = None
    moon_seps: list[float] | None = None
    moon_illums: list[float] | None = None
    moon_available = False
    moon_warning = ""

    try:
        from astropy import units as u
        from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body, get_sun
        from astropy.time import Time
        from astropy.utils import iers
        import numpy as np

        iers.conf.auto_download = False
        times = Time(times_dt)
        location = EarthLocation(
            lat=site_lat * u.deg, lon=site_lon * u.deg, height=site_elevation_m * u.m,
        )
        frame = AltAz(obstime=times, location=location)
        sun_coord = get_sun(times)
        sun_alts = sun_coord.transform_to(frame).alt.deg.tolist()
        coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
        target_altaz = coord.transform_to(frame)
        alts = target_altaz.alt.deg.tolist()

        if moon_enabled:
            try:
                moon_coord = get_body("moon", times, location=location)
                moon_altaz = moon_coord.transform_to(frame)
                moon_alts = moon_altaz.alt.deg.tolist()
                moon_seps = target_altaz.separation(moon_altaz).deg.tolist()
                moon_geo = get_body("moon", times)
                elongation = moon_geo.separation(sun_coord).deg
                moon_illums = ((1.0 - np.cos(np.deg2rad(elongation))) / 2.0 * 100.0).tolist()
                moon_available = True
            except Exception as exc:  # noqa: BLE001
                moon_warning = f"Moon unavailable ({exc}); moon constraint not applied"
                warn(moon_warning)
    except Exception as exc:  # noqa: BLE001
        from .time_utils import altitude_deg, sun_ra_dec_approx
        jds = [datetime_to_jd(t) for t in times_dt]
        sun_data = [sun_ra_dec_approx(jd) for jd in jds]
        sun_alts = [
            altitude_deg(sra, sdec, jd, site_lat, site_lon)
            for (sra, sdec), jd in zip(sun_data, jds)
        ]
        alts = [altitude_deg(ra, dec, jd, site_lat, site_lon) for jd in jds]
        if moon_enabled:
            moon_warning = f"Astropy unavailable ({exc}); moon constraint not applied"
            warn(moon_warning)

    return summarize_observing_samples(
        times_dt=times_dt,
        tz=tz,
        alts=alts,
        sun_alts=sun_alts,
        time_step_minutes=time_step_minutes,
        sun_alt_limit=sun_alt_limit,
        min_alt=min_alt,
        moon_enabled=moon_enabled,
        min_moon_sep=min_moon_sep,
        preferred_moon_sep=preferred_moon_sep,
        ignore_moon_below_alt=ignore_moon_below_alt,
        moon_available=moon_available,
        moon_alts=moon_alts,
        moon_seps=moon_seps,
        moon_illums=moon_illums,
        moon_warning=moon_warning,
    )


def summarize_observing_samples(
    *,
    times_dt: list[dt.datetime],
    tz: dt.tzinfo,
    alts: list[float],
    sun_alts: list[float],
    time_step_minutes: int,
    sun_alt_limit: float,
    min_alt: float,
    moon_enabled: bool,
    min_moon_sep: float,
    preferred_moon_sep: float,
    ignore_moon_below_alt: float,
    moon_available: bool = False,
    moon_alts: list[float] | None = None,
    moon_seps: list[float] | None = None,
    moon_illums: list[float] | None = None,
    moon_warning: str = "",
) -> dict[str, Any]:
    dark_mask = [sa < sun_alt_limit for sa in sun_alts]
    visible_mask: list[bool] = []
    for i, (alt, dark) in enumerate(zip(alts, dark_mask)):
        moon_ok = _moon_sample_ok(
            moon_enabled=moon_enabled,
            moon_available=moon_available,
            moon_alt=moon_alts[i] if moon_alts is not None else None,
            moon_sep=moon_seps[i] if moon_seps is not None else None,
            min_moon_sep=min_moon_sep,
            ignore_moon_below_alt=ignore_moon_below_alt,
        )
        visible_mask.append(alt > min_alt and dark and moon_ok)

    runs = _true_runs(visible_mask)
    if not runs:
        return _empty_window(
            reason="no samples meet altitude, dark-time, and moon constraints",
            time_step_minutes=time_step_minutes,
            min_alt=min_alt,
            sun_alt_limit=sun_alt_limit,
            moon_enabled=moon_enabled,
            min_moon_sep=min_moon_sep,
            preferred_moon_sep=preferred_moon_sep,
            ignore_moon_below_alt=ignore_moon_below_alt,
            moon_available=moon_available,
            moon_warning=moon_warning,
        )

    first_idx, last_idx = max(
        runs,
        key=lambda run: (run[1] - run[0] + 1, max(alts[i] for i in range(run[0], run[1] + 1))),
    )
    best_idx = max(range(first_idx, last_idx + 1), key=lambda i: alts[i])

    start_lt = times_dt[first_idx].astimezone(tz)
    end_lt = times_dt[last_idx].astimezone(tz)
    max_alt_time_lt = times_dt[best_idx].astimezone(tz)

    duration_h = round((last_idx - first_idx + 1) * time_step_minutes / 60.0, 2)
    visible_h = round(sum(1 for v in visible_mask if v) * time_step_minutes / 60.0, 2)
    moon_alt = moon_alts[best_idx] if moon_alts is not None else None
    moon_sep = moon_seps[best_idx] if moon_seps is not None else None
    moon_illum = moon_illums[best_idx] if moon_illums is not None else None

    return {
        "window_start": start_lt.strftime("%H:%M"),
        "window_end": end_lt.strftime("%H:%M"),
        "max_alt": round(float(alts[best_idx]), 1),
        "max_alt_time": max_alt_time_lt.strftime("%H:%M"),
        "duration_hours": duration_h,
        "visible_hours": visible_h,
        "observable": True,
        "time_step_minutes": time_step_minutes,
        "min_alt": min_alt,
        "sun_alt_limit": sun_alt_limit,
        "moon_enabled": moon_enabled,
        "min_moon_sep": min_moon_sep,
        "preferred_moon_sep": preferred_moon_sep,
        "ignore_moon_below_alt": ignore_moon_below_alt,
        "moon_available": moon_available,
        "moon_warning": moon_warning,
        "moon_alt": round(float(moon_alt), 1) if moon_alt is not None else None,
        "moon_sep": round(float(moon_sep), 1) if moon_sep is not None else None,
        "moon_illum": round(float(moon_illum), 0) if moon_illum is not None else None,
        "moon_status": _moon_status(
            moon_enabled=moon_enabled,
            moon_available=moon_available,
            moon_alt=moon_alt,
            moon_sep=moon_sep,
            min_moon_sep=min_moon_sep,
            preferred_moon_sep=preferred_moon_sep,
            ignore_moon_below_alt=ignore_moon_below_alt,
        ),
    }


def _moon_sample_ok(
    *,
    moon_enabled: bool,
    moon_available: bool,
    moon_alt: float | None,
    moon_sep: float | None,
    min_moon_sep: float,
    ignore_moon_below_alt: float,
) -> bool:
    if not moon_enabled or not moon_available:
        return True
    if moon_alt is None or moon_sep is None:
        return True
    if moon_alt <= ignore_moon_below_alt:
        return True
    return moon_sep >= min_moon_sep


def _moon_status(
    *,
    moon_enabled: bool,
    moon_available: bool,
    moon_alt: float | None,
    moon_sep: float | None,
    min_moon_sep: float,
    preferred_moon_sep: float,
    ignore_moon_below_alt: float,
) -> str:
    if not moon_enabled:
        return "disabled"
    if not moon_available:
        return "unavailable"
    if moon_alt is None or moon_sep is None:
        return "unavailable"
    if moon_alt <= ignore_moon_below_alt:
        return "OK (Moon below limit)"
    if moon_sep >= preferred_moon_sep:
        return "OK"
    if moon_sep >= min_moon_sep:
        return "Marginal"
    return "Too close"


def _true_runs(mask: list[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start = None
    for i, value in enumerate(mask):
        if value and start is None:
            start = i
        elif not value and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def _empty_window(
    *,
    reason: str = "",
    time_step_minutes: int | None = None,
    min_alt: float | None = None,
    sun_alt_limit: float | None = None,
    moon_enabled: bool = True,
    min_moon_sep: float = 30.0,
    preferred_moon_sep: float = 45.0,
    ignore_moon_below_alt: float = 0.0,
    moon_available: bool = False,
    moon_warning: str = "",
) -> dict[str, Any]:
    return {
        "window_start": "", "window_end": "",
        "max_alt": None, "max_alt_time": "",
        "duration_hours": 0.0, "visible_hours": 0.0,
        "observable": False,
        "reason": reason,
        "time_step_minutes": time_step_minutes,
        "min_alt": min_alt,
        "sun_alt_limit": sun_alt_limit,
        "moon_enabled": moon_enabled,
        "min_moon_sep": min_moon_sep,
        "preferred_moon_sep": preferred_moon_sep,
        "ignore_moon_below_alt": ignore_moon_below_alt,
        "moon_available": moon_available,
        "moon_warning": moon_warning,
        "moon_alt": None,
        "moon_sep": None,
        "moon_illum": None,
        "moon_status": "unavailable" if moon_enabled else "disabled",
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
        mag_note = _format_mag_note(target)
        if mag_note:
            parts.append(f"({mag_note})")
        mag_line = " ".join(parts)

    criteria_lines = _format_window_criteria(window)
    if window["observable"]:
        start_str = window["window_start"]
        end_str = window["window_end"]
        if end_str < start_str:
            end_str = f"{end_str} (+1d)"
        dur_total_min = int(round(window["duration_hours"] * 60))
        dur_h, dur_m = divmod(dur_total_min, 60)
        dur_str = f"{dur_h}h {dur_m:02d}m" if dur_h > 0 else f"{dur_m}m"
        max_alt_str = f"{window['max_alt']:.1f} deg at {window['max_alt_time']} {tz_label}"
        window_lines = criteria_lines + [
            f"  Start:         {start_str} {tz_label}",
            f"  End:           {end_str} {tz_label}",
            f"  Duration:      {dur_str}",
            f"  Max Altitude:  {max_alt_str}",
            f"  Moon:          {_format_moon_line(window)}",
        ]
    else:
        reason = window.get("reason") or "below altitude limit during dark time"
        window_lines = criteria_lines + [f"  Not observable on this night ({reason})"]
        moon_line = _format_moon_line(window)
        if moon_line:
            window_lines.append(f"  Moon:          {moon_line}")

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


def _format_date_for_mag(date_str: str) -> str:
    parsed = _parse_datetime_utc(date_str)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%d")
    return _format_date_short(date_str)


def _format_mag_note(target: Target) -> str:
    parts = []
    date_text = target.mag_date_utc or target.mag_note
    if date_text:
        parts.append(_format_date_for_mag(date_text))
    if target.mag_source:
        parts.append(target.mag_source)
    return ", ".join(part for part in parts if part)


def _format_window_criteria(window: dict[str, Any]) -> list[str]:
    min_alt = window.get("min_alt")
    sun_alt_limit = window.get("sun_alt_limit")
    time_step = window.get("time_step_minutes")
    criteria = []
    if min_alt is not None and sun_alt_limit is not None:
        text = f"alt > {float(min_alt):.1f} deg, Sun < {float(sun_alt_limit):.1f} deg"
        if window.get("moon_enabled"):
            text += (
                f", Moon sep >= {float(window.get('min_moon_sep', 30.0)):.1f} deg"
                f" when Moon alt > {float(window.get('ignore_moon_below_alt', 0.0)):.1f} deg"
            )
        criteria.append(f"  Criteria:      {text}")
    if time_step is not None:
        criteria.append(f"  Time Step:     {int(time_step)} min sampling")
    if window.get("moon_warning"):
        criteria.append(f"  Warning:       {window['moon_warning']}")
    return criteria


def _format_moon_line(window: dict[str, Any]) -> str:
    if not window.get("moon_enabled", True):
        return "disabled"
    if not window.get("moon_available", False):
        return "unavailable (moon constraint not applied)"
    pieces = []
    moon_sep = window.get("moon_sep")
    moon_alt = window.get("moon_alt")
    moon_illum = window.get("moon_illum")
    if moon_sep is not None:
        pieces.append(f"sep {float(moon_sep):.1f} deg")
    if moon_alt is not None:
        pieces.append(f"alt {float(moon_alt):.1f} deg")
    if moon_illum is not None:
        pieces.append(f"illum {float(moon_illum):.0f}%")
    status = window.get("moon_status")
    if status:
        pieces.append(str(status))
    return ", ".join(pieces)


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
    from .lasair import get_ztf_id_from_catalog_row
    target.ztf_id = get_ztf_id_from_catalog_row(row) or ""
    info(f"Catalog data: {target.name}  type={target.object_type}  "
         f"ra={target.ra_hms}  dec={target.dec_dms}  mag={target.mag}")

    # ── Step 2: Collect latest photometry + finder chart links ──
    photometry_points: list[PhotometryPoint] = []
    catalog_point = photometry_from_catalog_row(row)
    if catalog_point is not None:
        photometry_points.append(catalog_point)

    tns_name = row.get("name", "") or normalize_tns_name(target_name)
    html = fetch_tns_object_page(tns_name)
    if html:
        page_points = extract_tns_page_photometry(html)
        photometry_points.extend(page_points)
        info(f"TNS page photometry points: {len(page_points)}")

        # Finder chart images from page
        finder_candidates = find_tns_finder_candidates(html)
    else:
        finder_candidates = []

    if cfg.get("lasair_enabled", True):
        lasair_points = fetch_lasair_photometry(row)
        photometry_points.extend(lasair_points)
        info(f"Lasair photometry points: {len(lasair_points)}")
    else:
        info("Lasair photometry disabled in config")

    latest_photometry = select_latest_photometry(photometry_points)
    if latest_photometry is not None:
        apply_photometry_point(target, latest_photometry)
        info(
            "Latest mag selected: "
            f"{target.mag} {target.mag_filter} "
            f"({target.mag_date_utc or target.mag_note}, {target.mag_source})"
        )

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
        moon_enabled=bool(cfg.get("moon_enabled", True)),
        min_moon_sep=float(cfg.get("min_moon_sep", 30.0)),
        preferred_moon_sep=float(cfg.get("preferred_moon_sep", 45.0)),
        ignore_moon_below_alt=float(cfg.get("ignore_moon_below_alt", 0.0)),
    )
    target.max_alt_deg = window["max_alt"]
    target.visible_hours = window["visible_hours"]
    target.moon_alt_at_best = window.get("moon_alt")
    target.moon_sep_at_best = window.get("moon_sep")
    target.moon_illum_at_best = window.get("moon_illum")
    target.moon_status_at_best = window.get("moon_status", "")
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
    if cfg.get("download_files", True) and finder_candidates:
        downloaded = False
        reject_reasons: list[str] = []
        for index, candidate in enumerate(finder_candidates[:5], start=1):
            fname = _tns_finder_filename(candidate, index)
            dest = out_dir / f"finder_TNS_{fname}"
            info(f"Downloading TNS finder candidate ({candidate.label}): {candidate.url}")
            ok, reason = download_valid_tns_finder(candidate, dest, timeout=60)
            if ok:
                tns_finder_status = f"downloaded → {dest}"
                downloaded = True
                break
            reject_reasons.append(f"{candidate.label}: {reason}")
            warn(f"TNS finder candidate rejected: {candidate.url} ({reason})")
        if not downloaded:
            detail = "; ".join(reject_reasons[:3])
            tns_finder_status = "not available: no validated TNS finder chart"
            if detail:
                tns_finder_status += f" ({detail})"
    elif not finder_candidates:
        tns_finder_status = "not available: no validated TNS finder chart"
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
            overwrite=True,
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
