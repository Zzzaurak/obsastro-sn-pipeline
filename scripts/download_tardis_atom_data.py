#!/usr/bin/env python
"""Configure and download the TARDIS atomic data file into project data/.

Run with the tardis conda environment:
    conda activate tardis
    python scripts/download_tardis_atom_data.py

The script points TARDIS' internal data directory at this project's data/
directory, then downloads or reuses kurucz_cd23_chianti_H_He_latest.h5 there.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


ATOM_DATA_NAME = "kurucz_cd23_chianti_H_He_latest"
ATOM_DATA_FILE = f"{ATOM_DATA_NAME}.h5"


def project_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def default_tardis_config_path() -> Path:
    try:
        from astropy.config import get_config_dir
    except ImportError as exc:
        raise RuntimeError(
            "astropy not found. Activate the 'tardis' conda environment first."
        ) from exc

    return Path(get_config_dir()) / "tardis_internal_config.yml"


def write_tardis_internal_config(config_path: Path, data_dir: Path) -> None:
    config_path = Path(config_path).expanduser()
    data_dir = Path(data_dir).resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump({"data_dir": str(data_dir)}, sort_keys=False),
        encoding="utf-8",
    )


def load_download_atom_data():
    try:
        from tardis.io.atom_data import download_atom_data
    except ImportError as exc:
        raise RuntimeError(
            "tardis not found. Activate the 'tardis' conda environment first:\n"
            "  conda activate tardis"
        ) from exc

    return download_atom_data


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure TARDIS to use this project's data/ directory and download atomic data.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="force re-download even if the atomic data file already exists",
    )
    parser.add_argument(
        "--configure-only",
        action="store_true",
        help="only update TARDIS' internal data_dir config; do not download",
    )
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    project_root: Path | str | None = None,
    config_path: Path | str | None = None,
    downloader=None,
) -> int:
    args = parse_args(argv)
    root = Path(project_root).resolve() if project_root is not None else project_root_from_script()
    data_dir = root / "data"
    target = data_dir / ATOM_DATA_FILE
    data_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = Path(config_path).expanduser() if config_path is not None else default_tardis_config_path()
    write_tardis_internal_config(cfg_path, data_dir)

    print("Configured TARDIS data directory:")
    print(f"  {data_dir}")
    print("Wrote internal config:")
    print(f"  {cfg_path}")

    if args.configure_only:
        print("Configure-only mode: skipped atomic data download.")
        return 0

    print("Atomic data target:")
    print(f"  {target}")
    print()

    download = downloader or load_download_atom_data()
    download(ATOM_DATA_NAME, force_download=args.force)

    if not target.exists():
        print(f"ERROR: expected atomic data file was not found after download: {target}", file=sys.stderr)
        return 1

    print("\nDone. Atomic data is available at:")
    print(f"  {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
