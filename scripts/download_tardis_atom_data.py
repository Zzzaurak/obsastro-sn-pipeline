#!/usr/bin/env python
"""Download TARDIS atomic data file (~300 MB).

Run with the tardis conda environment:
    conda activate tardis
    python scripts/download_tardis_atom_data.py

The file is downloaded to ~/Downloads/tardis-data/ by default.
"""

import sys
import os

# Make sure tardis is importable
try:
    from tardis.io.atom_data import download_atom_data
except ImportError:
    print("ERROR: tardis not found. Activate the 'tardis' conda environment first.")
    print("  conda activate tardis")
    sys.exit(1)

URL = ("https://media.githubusercontent.com/media/tardis-sn/"
       "tardis-regression-data/main/atom_data/"
       "kurucz_cd23_chianti_H_He_latest.h5")
MD5 = "16341df5d104b462be4c3e51b167a893"

# Project data directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DATA = os.path.join(PROJECT_ROOT, "data")

# Update TARDIS internal config to use project data dir
import yaml
from pathlib import Path
cfg_path = os.path.expanduser("~/.astropy/config/tardis_internal_config.yml")
os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
with open(cfg_path, 'w') as f:
    parts = Path(PROJECT_DATA).parts
    f.write("data_dir: !!python/object/apply:pathlib._local.PosixPath\n")
    for p in parts[1:]:  # skip root '/'
        f.write(f"- {p}\n")

TARGET = os.path.join(PROJECT_DATA, "kurucz_cd23_chianti_H_He_latest.h5")

print(f"Downloading atomic data from:")
print(f"  {URL}")
print(f"to:")
print(f"  {TARGET}")
print(f"Expected MD5: {MD5}")
print()

download_atom_data()
print("\nDone.")
