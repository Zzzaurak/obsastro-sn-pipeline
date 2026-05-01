#!/usr/bin/env python3
"""SN Observing Pipeline — Fetch target parameters from TNS and generate observing report.

Usage:
    python scripts/fetch_target_params.py                           # use configs/sn_parameter.json
    python scripts/fetch_target_params.py --config configs/my.json  # custom config

Requirements:
    Activate the tardis conda environment first:
        conda activate tardis
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
        [sys.executable, "-m", "src.pipeline"] + sys.argv[1:],
        env=env,
        cwd=PROJECT_ROOT,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
