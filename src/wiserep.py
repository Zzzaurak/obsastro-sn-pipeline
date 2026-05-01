from __future__ import annotations

import csv
import io
import os
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

from .utils import info, mkdir, normalize_tns_name, warn

WISEREP_BASE = "https://www.wiserep.org"
WISEREP_SPECTRA_SEARCH = f"{WISEREP_BASE}/search/spectra"


def get_wiserep_api_key() -> str:
    return os.environ.get("WISEREP_API_KEY", "").strip()


def fetch_spectra_metadata(
    objname: str,
    *,
    api_key: str | None = None,
) -> list[dict[str, str]]:
    """Fetch spectra metadata from WISeREP.

    Searches by object IAU name (e.g., '2026fov' without SN prefix).
    Returns list of dicts with columns: spec_id, obs_date, instrument, etc.
    """
    # Strip SN/AT prefix for WISeREP search
    search_name = normalize_tns_name(objname)
    if api_key is None:
        api_key = get_wiserep_api_key()

    params = {
        "name": search_name,
        "format": "tsv",
        "num_page": "250",
        "page": "0",
    }
    url = f"{WISEREP_SPECTRA_SEARCH}?{urllib.parse.urlencode(params)}"

    info(f"WISeREP query: {search_name}")

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; sn-pipeline/0.1)",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except Exception as exc:
        warn(f"WISeREP request failed: {exc}")
        return []

    if data[:2] != b"PK":
        warn("WISeREP did not return ZIP data")
        return []

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".tsv")]
        if not names:
            warn("WISeREP ZIP has no TSV file")
            return []
        tsv_text = zf.read(names[0]).decode("utf-8", "replace")

    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    return [row for row in reader if row.get("Spec. ID")]


def save_spectra_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    """Save spectra metadata to CSV."""
    mkdir(output_path.parent)
    if not rows:
        output_path.write_text("", encoding="utf-8")
        return

    fieldnames = [
        "Obj. ID", "IAU name", "Spec. ID", "Obs-date", "JD",
        "Telescope", "Instrument", "Spec. type", "Spec. quality",
        "Exp-time", "Redshift", "Ascii file", "Fits file",
        "Phase (days)", "WL Medium", "WL Units", "Spec. units",
        "Obj. RA", "Obj. DEC", "Obj. Type",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def download_spectrum_file(url: str, output_path: Path) -> bool:
    """Download a single spectrum ASCII file from WISeREP."""
    if output_path.exists():
        return True
    try:
        info(f"Downloading spectrum: {output_path.name}")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; sn-pipeline/0.1)",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            mkdir(output_path.parent)
            output_path.write_bytes(resp.read())
        return True
    except Exception as exc:
        warn(f"Spectrum download failed: {exc}")
        return False


def _read_ascii_spectrum(filepath: Path | str) -> tuple[list[float], list[float]] | None:
    """Parse a WISeREP ASCII spectrum file (two-column: wavelength flux)."""
    filepath = Path(filepath)
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    wavelengths = []
    fluxes = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                wl = float(parts[0])
                fl = float(parts[1])
                if wl > 0 and fl != 0:
                    wavelengths.append(wl)
                    fluxes.append(fl)
            except (ValueError, IndexError):
                continue

    if len(wavelengths) < 10:
        return None
    return wavelengths, fluxes

def plot_spectra(
    spectrum_files: list[Path | str],
    target_name: str,
    output_path: Path | None = None,
    *,
    jupyter: bool = False,
) -> Path | None:

    plots = 0

    if not jupyter and output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True) 

    fig, ax = plt.subplots(figsize=(10, 5))
    colors = plt.cm.tab10.colors

    for i, sp_path in enumerate(spectrum_files[:5]):
        result = _read_ascii_spectrum(sp_path)
        if result is None:
            print(f"Warning: {Path(sp_path).name} 读取失败或返回None，已跳过")
            continue
        wl, flux = result
        label = Path(sp_path).stem.replace("_", " ")
        ax.plot(wl, flux, lw=0.8, color=colors[i % len(colors)], label=label)
        plots += 1

    if plots == 0:
        plt.close(fig)
        return None

    ax.set_xlabel("Wavelength (Angstrom)")
    ax.set_ylabel("Flux")
    ax.set_title(f"Spectra: {target_name}")
    if plots > 1:
        ax.legend(loc="best", fontsize=8)

    fig.tight_layout()

    if jupyter:
        # 在 Jupyter 中显示图像
        plt.show()
        return None

    # 如果不是 Jupyter，保存图片
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig) 

    # info(f"Spectrum plot saved → {output_path}") # 假设 info 是你自定义的 log
    print(f"Spectrum plot saved → {output_path}")
    return output_path


def save_clean_two_column_spectrum(input_path: Path | str, output_path: Path) -> bool:
    """Re-save a spectrum file as clean 2-column (wl flux) via np.savetxt.

    Useful for tools like astrodash that require strictly formatted input.
    """
    result = _read_ascii_spectrum(input_path)
    if result is None:
        warn(f"Cannot clean {input_path}: parse failed")
        return False

    wl, flux = result
    mkdir(output_path.parent)
    # No header line — tools like astrodash/pandas expect pure numeric data
    np.savetxt(output_path, np.column_stack((wl, flux)),
               fmt=["%.4f", "%.6e"], delimiter="  ")
    info(f"Clean spectrum saved → {output_path}")
    return True