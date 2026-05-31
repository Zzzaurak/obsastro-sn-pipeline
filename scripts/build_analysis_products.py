"""Build the compact analysis products used by the report notebooks and slides."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.spectral_pipeline import build_all


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory; defaults to output/analysis_pipeline under the project root",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else None
    paths = build_all(project_root=project_root, output_dir=output_dir)

    print("Generated analysis products:")
    for key, value in paths.items():
        if isinstance(value, list):
            print(f"- {key}: {len(value)} files")
            for item in value:
                print(f"  - {item}")
        else:
            print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
