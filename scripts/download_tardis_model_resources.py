#!/usr/bin/env python
"""Prepare TARDIS model resource files for later tuning.

Run in the tardis environment when copying package-bundled resources:
    conda activate tardis
    python scripts/download_tardis_model_resources.py

This only prepares density/abundance resource files under data/tardis_models/.
It does not run TARDIS simulations or modify per-target configs.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tardis_model_resources import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
