#!/usr/bin/env python3
"""Fetch auxiliary data: Lasair light curves and WISeREP spectra.

Usage:
    python scripts/fetch_aux_data.py                           # use configs/sn_parameter.json
    python scripts/fetch_aux_data.py --config configs/my.json  # custom config

Requirements:
    Activate the astro_env conda environment first:
        conda activate astro_env
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    env = os.environ.copy()
    pythonpath = str(PROJECT_ROOT)
    existing = env.get("PYTHONPATH", "")
    if existing:
        pythonpath = pythonpath + os.pathsep + existing
    env["PYTHONPATH"] = pythonpath

    return subprocess.run(
        [sys.executable, "-m", "src.fetch_aux_data"] + sys.argv[1:],
        env=env,
        cwd=PROJECT_ROOT,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
