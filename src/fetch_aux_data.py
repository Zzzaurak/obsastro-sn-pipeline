from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any

from .lasair import (
    fetch_lasair_object,
    get_ztf_id_from_catalog_row,
    plot_lightcurve,
    save_lightcurve_csv,
)
from .pipeline import (
    _parse_catalog,
    ensure_catalog,
    load_env_file,
    lookup_catalog_target,
)
from .utils import clean_filename, info, mkdir, normalize_tns_name, warn
from .wiserep import (
    download_spectrum_file,
    fetch_spectra_metadata,
    plot_spectra,
    save_clean_two_column_spectrum,
    save_spectra_csv,
)


def load_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        warn(f"Config not found: {path}")
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    flat: dict[str, Any] = {}
    for section in ("observing", "lasair", "wiserep", "output"):
        for k, v in (raw.get(section) or {}).items():
            flat[k] = v

    defaults = {
        "target": "", "date": dt.date.today().isoformat(),
        "out_dir": "output",
    }
    for k, v in defaults.items():
        flat.setdefault(k, v)
    return flat


def run(config_path: str) -> int:
    load_env_file()
    cfg = load_config(config_path)
    if not cfg:
        return 1

    target_name = cfg.get("target", "").strip()
    if not target_name:
        warn("No target in config")
        return 1

    date_str = cfg.get("date", "")
    out_base = Path(cfg.get("out_dir", "output"))
    clean_tgt = clean_filename(target_name)
    out_dir = out_base / clean_tgt
    lc_dir = out_dir / "lightcurve"
    spec_dir = out_dir / "spectrum"

    info(f"Aux data: target={target_name}")

    # ── Load TNS catalog for ZTF ID lookup ──
    csv_path = ensure_catalog()
    if not csv_path:
        return 1

    catalog = _parse_catalog(csv_path)
    row = lookup_catalog_target(catalog, target_name)
    if not row:
        warn(f"Target '{target_name}' not found in TNS catalog")
        return 1

    ztf_id = get_ztf_id_from_catalog_row(row)
    tns_name = row.get("name", "") or normalize_tns_name(target_name)

    # ═══════════════════════════════════════════════════════════
    #  Lasair light curve
    # ═══════════════════════════════════════════════════════════

    lasair_enabled = cfg.get("lasair_enabled", True)
    lc_csv_path = lc_dir / "lightcurve_lasair.csv"
    lc_png_path = lc_dir / "lightcurve_lasair.png"

    if lasair_enabled and ztf_id:
        info(f"Lasair: ZTF ID = {ztf_id}")
        obj = fetch_lasair_object(ztf_id)
        if obj:
            candidates = obj.get("candidates", [])
            force = obj.get("forcedphot", [])

            # Merge candidates + forced photometry
            merged = list(candidates)
            if force:
                for fp in force:
                    if fp.get("forcediffimflux", -99999) > 0:
                        try:
                            mag = float(fp["magzpsci"]) - 2.5 * math.log10(fp["forcediffimflux"])
                            err = 2.5 * fp["forcediffimfluxunc"] / fp["forcediffimflux"]
                            mjd = fp.get("jd", 0) - 2400000.5
                            merged.append({
                                "candid": None,
                                "jd": fp["jd"],
                                "mjd": mjd,
                                "fid": fp["fid"],
                                "magpsf": round(mag, 4),
                                "sigmapsf": round(err, 4) if err > 0 else None,
                                "diffmaglim": None,
                                "isdiffpos": "t",
                                "ra": None,
                                "dec": None,
                            })
                        except Exception:
                            pass

            save_lightcurve_csv(merged, lc_csv_path)
            info(f"Light curve CSV saved → {lc_csv_path}")

            plot_lightcurve(merged, target_name, lc_png_path,
                            ztf_id=ztf_id, obs_date=date_str)
        else:
            warn("Lasair returned no data")
    elif not ztf_id:
        warn(f"No ZTF ID found for {target_name} (internal_names={row.get('internal_names','')})")
    else:
        info("Lasair disabled in config")

    # ═══════════════════════════════════════════════════════════
    #  WISeREP spectra
    # ═══════════════════════════════════════════════════════════

    wiserep_enabled = cfg.get("wiserep_enabled", True)
    spec_csv_path = spec_dir / "spectra_wiserep.csv"
    spec_png_path = spec_dir / "spectra_wiserep.png"

    if wiserep_enabled:
        spec_rows = fetch_spectra_metadata(tns_name)
        if spec_rows:
            save_spectra_csv(spec_rows, spec_csv_path)
            info(f"Spectra metadata CSV saved → {spec_csv_path} ({len(spec_rows)} spectra)")

            # Download up to 2 spectrum files, clean them, and plot
            downloaded: list[Path] = []
            cleaned: list[Path] = []
            for srow in spec_rows[:2]:
                ascii_url = srow.get("Ascii file", "").strip()
                if not ascii_url:
                    continue
                spec_id = srow.get("Spec. ID", "unknown")
                dest = spec_dir / f"spectrum_{spec_id}.ascii"
                if download_spectrum_file(ascii_url, dest):
                    downloaded.append(dest)
                    # Save clean 2-column version for astrodash etc.
                    clean_dest = spec_dir / f"spectrum_{spec_id}.dat"
                    if save_clean_two_column_spectrum(dest, clean_dest):
                        cleaned.append(clean_dest)

            if downloaded:
                plot_spectra(downloaded, target_name, spec_png_path)
            else:
                warn("No spectrum files downloaded")
        else:
            warn(f"No spectra found in WISeREP for {tns_name}")
    else:
        info("WISeREP disabled in config")

    info("Aux data fetch complete.")
    return 0


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "configs/sn_parameter.json"
    sys.exit(run(config_path))
