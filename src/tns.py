from __future__ import annotations

import csv
import io
import json as json_mod
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

from .utils import (
    RateLimitTracker,
    clean_filename,
    first_float,
    get_tns_credentials,
    info,
    mkdir,
    normalize_tns_name,
    request_bytes_rate_limited,
    request_json_rate_limited,
    save_text,
    tns_auth_headers,
    tns_auth_headers_with_content_type,
    tns_has_bot,
    warn,
    write_csv,
)

TNS_API_BASE = "https://www.wis-tns.org/api"
TNS_GET_OBJECT = f"{TNS_API_BASE}/get/object"
TNS_GET_FILE = f"{TNS_API_BASE}/get/file"
TNS_PUBLIC_CSV_URL = "https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects.csv.zip"


def download_tns_catalog(catalog_dir: Path, *, overwrite: bool = False) -> Path | None:
    try:
        import urllib.request as _urllib

        csv_zip_path = catalog_dir / "tns_public_objects.csv.zip"
        csv_path = catalog_dir / "tns_public_objects.csv"
        if csv_path.exists() and not overwrite:
            info(f"TNS catalog already cached at {csv_path}")
            return csv_path

        creds = get_tns_credentials()
        marker_hdrs = tns_auth_headers()
        if not marker_hdrs:
            hdrs = {"User-Agent": "sn-target-downloader/0.2"}
        else:
            hdrs = marker_hdrs

        if not csv_zip_path.exists() or overwrite:
            info("Downloading TNS public objects catalog...")
            req = _urllib.Request(TNS_PUBLIC_CSV_URL, headers=hdrs)
            with _urllib.urlopen(req, timeout=120) as response:
                mkdir(catalog_dir)
                csv_zip_path.write_bytes(response.read())

        with zipfile.ZipFile(csv_zip_path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not names:
                warn("TNS catalog ZIP contains no CSV file")
                return None
            csv_zip_path_bytes = zf.read(names[0]).decode("utf-8", "replace")
            mkdir(catalog_dir)
            csv_path.write_text(csv_zip_path_bytes, encoding="utf-8")

        info(f"TNS catalog saved to {csv_path}")
        return csv_path
    except Exception as exc:
        warn(f"TNS catalog download failed: {exc}")
        return None


def parse_tns_catalog(catalog_path: Path) -> list[dict[str, str]]:
    text = catalog_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = 1 if lines and not lines[0].startswith('"') else 0
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    return [row for row in reader if row]


def tns_lookup_targets(catalog_rows: list[dict[str, str]], targets: list[Any]) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for target in targets:
        names_to_try = []
        if hasattr(target, "iau_name") and target.iau_name:
            names_to_try.append(target.iau_name.strip())
            normalized = normalize_tns_name(target.iau_name)
            if normalized and normalized != target.iau_name.strip():
                names_to_try.append(normalized)
        if hasattr(target, "name") and target.name:
            names_to_try.append(target.name.strip())
            if target.name.lower().startswith("sn") or target.name.lower().startswith("at"):
                names_to_try.append(normalize_tns_name(target.name))

        for name in set(names_to_try):
            for row in catalog_rows:
                full_name = (row.get("name") or "").strip()
                tns_prefix = (row.get("name_prefix") or "").strip()
                combined = f"{tns_prefix}{full_name}".strip()
                if combined.upper() == name.upper() or full_name.upper() == name.upper():
                    key = clean_filename(getattr(target, "name", target.ztf_id))
                    found[key] = row
                    break

        if not found.get(clean_filename(getattr(target, "name", getattr(target, "ztf_id", "unknown")))):
            ztf_id = getattr(target, "ztf_id", "")
            if ztf_id:
                for row in catalog_rows:
                    internal_names = (row.get("internal_names") or "").strip()
                    if ztf_id.upper() in internal_names.upper():
                        key = clean_filename(getattr(target, "name", ztf_id))
                        found[key] = row
                        break

    return found


def fetch_tns_object(
    target: Any,
    catalog_row: dict[str, str] | None,
    objects_dir: Path,
    tracker: RateLimitTracker,
    *,
    max_requests: int = 0,
    include_photometry: bool = True,
    include_spectra: bool = True,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "tns_id": "",
        "object_path": "",
        "photometry_csv": "",
        "spectra_csv": "",
        "spectra_count": 0,
        "photometry_count": 0,
    }

    if not tracker.has_budget(max_requests):
        tracker.record_skip(f"budget exhausted TNS object {getattr(target, 'name', '')}")
        return result

    if not tns_has_bot():
        tracker.record_skip("TNS bot credentials not set (Get Object API requires bot-level access)")
        return result

    creds = get_tns_credentials()
    if not creds or not creds.api_key:
        tracker.record_skip("no TNS API key")
        return result

    obj_name = None
    obj_id = None

    if catalog_row:
        obj_id = (catalog_row.get("objid") or "").strip()
        prefix = (catalog_row.get("name_prefix") or "").strip()
        name = (catalog_row.get("name") or "").strip()
        if prefix and name:
            obj_name = f"{prefix} {name}"
        elif name:
            obj_name = name

    if not obj_name and hasattr(target, "iau_name") and target.iau_name:
        obj_name = target.iau_name.strip()

    if not obj_name and not obj_id:
        tracker.record_skip(f"no TNS name/id for {getattr(target, 'name', '')}")
        return result

    tns_id = obj_id or obj_name or "unknown"
    result["tns_id"] = tns_id

    target_label = clean_filename(getattr(target, "name", getattr(target, "ztf_id", tns_id)))
    obj_dir = mkdir(objects_dir / target_label)
    object_json_path = obj_dir / f"{clean_filename(tns_id)}_tns_object.json"

    if object_json_path.exists():
        try:
            obj_data = json_mod.loads(object_json_path.read_text(encoding="utf-8"))
            result["object_path"] = str(object_json_path)
            result["ok"] = True
        except Exception:
            pass
        else:
            if include_photometry and obj_data.get("photometry"):
                result["photometry_csv"] = _save_tns_photometry(obj_dir, tns_id, obj_data["photometry"])
                result["photometry_count"] = len(obj_data["photometry"])
            if include_spectra and obj_data.get("spectra"):
                result["spectra_csv"] = _save_tns_spectra_manifest(obj_dir, tns_id, obj_data["spectra"])
                result["spectra_count"] = len(obj_data["spectra"])
            return result

    form_data = urllib.parse.urlencode({
        "api_key": creds.api_key,
        "objname": obj_name or "",
        "objid": obj_id or "",
        "photometry": "1" if include_photometry else "0",
        "spectra": "1" if include_spectra else "0",
    }).encode("ascii")

    hdrs = tns_auth_headers_with_content_type()

    data, resp_headers = request_json_rate_limited(
        TNS_GET_OBJECT,
        tracker,
        max_requests=max_requests,
        timeout=90,
        headers=hdrs,
        method="POST",
        post_data=form_data,
    )

    if data is None:
        return result

    result["ok"] = True
    result["object_path"] = str(object_json_path)
    save_text(object_json_path, json_mod.dumps(data, indent=2, ensure_ascii=False, default=str))

    if isinstance(data, dict):
        tns_obj = data.get("data", {}).get("reply") or data.get("reply") or data
        if include_photometry and tns_obj.get("photometry"):
            result["photometry_csv"] = _save_tns_photometry(obj_dir, tns_id, tns_obj["photometry"])
            result["photometry_count"] = len(tns_obj["photometry"])
        if include_spectra and tns_obj.get("spectra"):
            result["spectra_csv"] = _save_tns_spectra_manifest(obj_dir, tns_id, tns_obj["spectra"])
            result["spectra_count"] = len(tns_obj["spectra"])

    _update_target_from_tns(target, data)
    return result


def _save_tns_photometry(obj_dir: Path, tns_id: str, photometry: list[dict[str, Any]]) -> str:
    csv_path = obj_dir / f"{clean_filename(tns_id)}_tns_photometry.csv"
    rows: list[dict[str, Any]] = []
    for group in photometry:
        if not isinstance(group, dict):
            continue
        group_name = group.get("groupid") or group.get("group_name") or ""
        for pt in group.get("photometry", []):
            if not isinstance(pt, dict):
                continue
            row = dict(pt)
            row["tns_id"] = tns_id
            row["groupid"] = str(group_name)
            rows.append(row)
    if rows:
        write_csv(csv_path, rows)
        return str(csv_path)
    return ""


def _save_tns_spectra_manifest(obj_dir: Path, tns_id: str, spectra: list[dict[str, Any]]) -> str:
    csv_path = obj_dir / f"{clean_filename(tns_id)}_tns_spectra_manifest.csv"
    rows: list[dict[str, Any]] = []
    for spec in spectra:
        if not isinstance(spec, dict):
            continue
        row = dict(spec)
        row["tns_id"] = tns_id
        rows.append(row)
    if rows:
        write_csv(csv_path, rows)
        return str(csv_path)
    return ""


def _update_target_from_tns(target: Any, tns_data: dict[str, Any]) -> None:
    if not isinstance(tns_data, dict):
        return
    tns_obj = tns_data.get("data", {}).get("reply") or tns_data.get("reply") or tns_data

    tns_name = tns_obj.get("name_prefix", "") + " " + tns_obj.get("name", "")
    tns_name = tns_name.strip()
    if tns_name and not getattr(target, "iau_name", ""):
        target.iau_name = tns_name
        target.aliases.add(tns_name)

    ra_val = tns_obj.get("ra")
    dec_val = tns_obj.get("declination")
    if ra_val and getattr(target, "ra_deg", None) is None:
        ra_deg = _parse_tns_ra(ra_val)
        if ra_deg is not None:
            target.ra_deg = ra_deg
            from .coordinates import deg_to_hms
            target.ra_hms = deg_to_hms(ra_deg)
    if dec_val and getattr(target, "dec_deg", None) is None:
        dec_deg = _parse_tns_dec(dec_val)
        if dec_deg is not None:
            target.dec_deg = dec_deg
            from .coordinates import deg_to_dms
            target.dec_dms = deg_to_dms(dec_deg)

    obj_type = tns_obj.get("object_type", {}).get("name") or tns_obj.get("type") or ""
    if obj_type and not getattr(target, "object_type", ""):
        target.object_type = str(obj_type).strip("- ")

    redshift = first_float(tns_obj.get("redshift"))
    if redshift is not None and not getattr(target, "redshift", ""):
        target.redshift = str(redshift)

    host_name = tns_obj.get("hostname") or ""
    if host_name and not getattr(target, "host", ""):
        target.host = host_name

    discovery_date = tns_obj.get("discoverydate") or tns_obj.get("discovery_date") or ""
    if discovery_date and not getattr(target, "discovery_date", ""):
        target.discovery_date = discovery_date

    phot_count = len(tns_obj.get("photometry", []))
    spec_count = len(tns_obj.get("spectra", []))
    target.source_ids.add("TNS")
    if phot_count:
        target.notes.append(f"TNS photometry groups={phot_count}")
    if spec_count:
        target.notes.append(f"TNS spectra={spec_count}")


def _parse_tns_ra(ra_str: str) -> float | None:
    try:
        parts = ra_str.strip().replace("h", " ").replace("m", " ").replace("s", " ").split()
        if len(parts) >= 3:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return (h + m / 60.0 + s / 3600.0) * 15.0
        return float(ra_str)
    except (ValueError, TypeError):
        return None


def _parse_tns_dec(dec_str: str) -> float | None:
    try:
        dec_str = dec_str.strip().replace("d", " ").replace("m", " ").replace("s", " ").replace("'", " ").replace('"', " ")
        sign = -1.0 if dec_str.startswith("-") else 1.0
        dec_str = dec_str.lstrip("+-")
        parts = dec_str.split()
        if len(parts) >= 3:
            d, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return sign * (abs(d) + m / 60.0 + s / 3600.0)
        return float(dec_str)
    except (ValueError, TypeError):
        return None


def download_tns_spectra_files(
    target: Any,
    tns_object_result: dict[str, Any],
    spectra_dir: Path,
    tracker: RateLimitTracker,
    *,
    max_requests: int = 0,
    max_files: int = 2,
) -> int:
    if not tns_object_result.get("ok") or not tns_object_result.get("spectra_count"):
        return 0

    if not tns_has_bot():
        return 0

    creds = get_tns_credentials()
    if not creds or not creds.api_key:
        return 0

    spectra_csv_path = tns_object_result.get("spectra_csv")
    if not spectra_csv_path:
        return 0
    spectra_csv = Path(spectra_csv_path)
    if not spectra_csv.exists():
        return 0

    with spectra_csv.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    target_label = clean_filename(getattr(target, "name", getattr(target, "ztf_id", "unknown")))
    obj_dir = mkdir(spectra_dir / target_label)
    downloaded = 0

    hdrs = tns_auth_headers_with_content_type()

    for spec_row in reader:
        if not tracker.has_budget(max_requests):
            tracker.record_skip("budget exhausted TNS spectra")
            break
        if downloaded >= max_files:
            break

        file_id = spec_row.get("fileid") or ""
        if not file_id:
            continue
        filename = spec_row.get("filename") or spec_row.get("name") or f"tns_spec_{file_id}"
        filename = clean_filename(filename, f"tns_spectrum_{downloaded + 1}")

        dest = obj_dir / filename
        if dest.exists():
            downloaded += 1
            continue

        form_data = urllib.parse.urlencode({
            "api_key": creds.api_key,
            "fileid": file_id,
        }).encode("ascii")

        file_data, resp_headers = request_bytes_rate_limited(
            TNS_GET_FILE,
            tracker,
            max_requests=max_requests,
            timeout=120,
            headers=hdrs,
            method="POST",
            post_data=form_data,
        )

        if file_data:
            dest.write_bytes(file_data)
            downloaded += 1

    return downloaded
