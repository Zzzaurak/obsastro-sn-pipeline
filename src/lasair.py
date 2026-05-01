from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .utils import (
    get_lasair_token,
    info,
    lasair_url,
    mkdir,
    request_json,
    warn,
)

LASAIR_API_BASE = "https://lasair-ztf.lsst.ac.uk/api"
LASAIR_OBJECT_URL = f"{LASAIR_API_BASE}/object/"


def get_ztf_id_from_catalog_row(row: dict[str, str]) -> str | None:
    """Extract ZTF object ID from a TNS catalog row's internal_names."""
    internals = (row.get("internal_names") or "").strip()
    if not internals:
        return None
    for name in internals.split(","):
        name = name.strip()
        if name.upper().startswith("ZTF"):
            return name
    return None


def fetch_lasair_object(ztf_id: str) -> dict[str, Any] | None:
    """Fetch Lasair object data (including light curve) by ZTF ID."""
    token = get_lasair_token()
    if not token:
        warn("No Lasair API token found (set LASAIR_API_TOKEN in .env)")
        return None

    url = lasair_url(LASAIR_OBJECT_URL, {"objectId": ztf_id})
    info(f"Lasair query: {ztf_id}")

    try:
        data = request_json(url, timeout=60)
    except Exception as exc:
        warn(f"Lasair API request failed: {exc}")
        return None

    if not isinstance(data, dict):
        warn(f"Lasair returned unexpected data type: {type(data)}")
        return None

    if not data.get("candidates"):
        warn(f"Lasair returned no candidates for {ztf_id}")
        return None

    return data


def save_lightcurve_csv(candidates: list[dict], output_path: Path) -> None:
    """Save Lasair candidate light curve data to CSV."""
    if not candidates:
        mkdir(output_path.parent)
        output_path.write_text("", encoding="utf-8")
        return

    mkdir(output_path.parent)
    fieldnames = [
        "jd", "mjd", "fid", "filter", "magpsf", "sigmapsf",
        "diffmaglim", "isdiffpos", "ra", "dec", "candid", "nid", "utc",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for c in candidates:
            row = dict(c)
            row["filter"] = _fid_to_filter(c.get("fid"))
            # Ensure mjd is set (Lasair sometimes returns null)
            if not row.get("mjd") and row.get("jd"):
                row["mjd"] = round(float(row["jd"]) - 2400000.5, 6)
            writer.writerow(row)


def plot_lightcurve(
    candidates: list[dict],
    target_name: str,
    output_path: Path,
    *,
    ztf_id: str = "",
    obs_date: str = "",
) -> Path | None:
    """Plot Lasair light curve as PNG with calendar-date x-axis."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np

    if not candidates:
        return None

    mkdir(output_path.parent)

    # Convert MJD to datetime for each candidate
    def _mjd_to_dt(mjd_val: float):
        try:
            from astropy.time import Time
            return Time(mjd_val, format="mjd").datetime
        except Exception:
            import datetime as _dt
            jd = mjd_val + 2400000.5
            return _dt.datetime(1858, 11, 17) + _dt.timedelta(days=jd - 2400000.5)

    fig, ax = plt.subplots(figsize=(11, 6))

    color_map = {1: "#2ca02c", 2: "#d62728"}  # green=g, red=r
    label_map = {1: "ZTF-g", 2: "ZTF-r"}

    max_mjd = 0.0
    for fid, color in color_map.items():
        dets = [c for c in candidates if c.get("fid") == fid and c.get("magpsf") is not None]
        nondets = [c for c in candidates if c.get("fid") == fid and c.get("magpsf") is None]

        if dets:
            dates = [_mjd_to_dt(_get_mjd(c)) for c in dets]
            mags = [c["magpsf"] for c in dets]
            errs = [c.get("sigmapsf") for c in dets]
            has_err = any(e is not None for e in errs)
            if has_err:
                ax.errorbar(dates, mags, yerr=errs, fmt="o", color=color,
                            markersize=5, capsize=2, elinewidth=1,
                            label=label_map[fid], zorder=3)
            else:
                ax.scatter(dates, mags, c=color, s=40, zorder=3, label=label_map[fid])
            # Track latest MJD for annotation
            for c in dets:
                mj = _get_mjd(c)
                if mj > max_mjd:
                    max_mjd = mj

        if nondets:
            dates = [_mjd_to_dt(_get_mjd(c)) for c in nondets]
            lims = [c.get("diffmaglim") for c in nondets]
            ax.scatter(dates, lims, marker="v", c=color, s=24,
                       alpha=0.35, zorder=2)

    ax.invert_yaxis()
    ax.set_xlabel("Date (UTC)")
    ax.set_ylabel("Magnitude (AB)")

    # Format x-axis as short dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=30, ha="right")

    # ── Annotation: last photometry vs observing date ──
    annotation = ""
    if max_mjd > 0:
        last_date = _mjd_to_dt(max_mjd)
        last_str = last_date.strftime("%Y-%m-%d")
        annotation += f"Last photometry: {last_str} (JD {max_mjd + 2400000.5:.1f})"
        if obs_date:
            try:
                import datetime as _dt
                obs_dt = _dt.date.fromisoformat(obs_date)
                days_ago = (obs_dt - last_date.date()).days
                annotation += f"  |  {days_ago} days before obs date {obs_date}"
            except Exception:
                pass

    title = f"Light Curve: {target_name}"
    if ztf_id:
        title += f" ({ztf_id})"
    if annotation:
        title += f"\n{annotation}"
    ax.set_title(title, fontsize=11)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    info(f"Light curve plot saved → {output_path}")
    return output_path


def _fid_to_filter(fid: int | None) -> str:
    if fid == 1:
        return "g"
    if fid == 2:
        return "r"
    return ""


def _get_mjd(c: dict) -> float:
    if "mjd" in c and c["mjd"] is not None:
        return float(c["mjd"])
    jd = c.get("jd")
    if jd is not None:
        return float(jd) - 2400000.5
    return 0.0
