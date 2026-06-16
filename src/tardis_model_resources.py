"""Helpers for preparing external TARDIS model resources.

This module only manages density/abundance model files. It does not run TARDIS
or modify per-target simulation configs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import yaml


DEFAULT_OUTPUT_SUBDIR = Path("data") / "tardis_models"
DEFAULT_MANIFEST = Path("configs") / "tardis" / "model_resources.yml"


@dataclass(frozen=True)
class ModelResource:
    resource_id: str
    family: str
    description: str
    source_type: str
    target: Path
    source_path: Path | None = None
    url: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class InstallResult:
    resource_id: str
    status: str
    source_type: str
    output_path: Path
    bytes_written: int

    def as_row(self) -> dict[str, str | int]:
        return {
            "resource_id": self.resource_id,
            "status": self.status,
            "source_type": self.source_type,
            "output_path": str(self.output_path),
            "bytes_written": self.bytes_written,
        }


FetchUrl = Callable[[str, int], bytes]


def project_root_from_module() -> Path:
    return Path(__file__).resolve().parents[1]


def load_manifest(path: Path | str) -> list[ModelResource]:
    manifest_path = Path(path)
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    raw_resources = data.get("resources", [])
    if not isinstance(raw_resources, list):
        raise ValueError(f"manifest resources must be a list: {manifest_path}")

    resources: list[ModelResource] = []
    for index, raw in enumerate(raw_resources):
        if not isinstance(raw, dict):
            raise ValueError(f"resource #{index} must be a mapping")
        source = raw.get("source", {})
        if not isinstance(source, dict):
            raise ValueError(f"resource {raw.get('id', index)!r} source must be a mapping")

        resource_id = str(raw.get("id") or "").strip()
        source_type = str(source.get("type") or "").strip()
        target = str(raw.get("target") or "").strip()
        if not resource_id:
            raise ValueError(f"resource #{index} is missing id")
        if source_type not in {"package_file", "url"}:
            raise ValueError(f"resource {resource_id!r} has unsupported source type: {source_type!r}")
        if not target:
            raise ValueError(f"resource {resource_id!r} is missing target")

        source_path = None
        url = None
        sha256 = None
        if source_type == "package_file":
            source_path_text = str(source.get("path") or "").strip()
            if not source_path_text:
                raise ValueError(f"resource {resource_id!r} package source is missing path")
            source_path = Path(source_path_text)
        else:
            url = str(source.get("url") or "").strip()
            sha256 = str(source.get("sha256") or "").strip() or None
            if not url:
                raise ValueError(f"resource {resource_id!r} URL source is missing url")

        resources.append(
            ModelResource(
                resource_id=resource_id,
                family=str(raw.get("family") or "").strip(),
                description=str(raw.get("description") or "").strip(),
                source_type=source_type,
                target=Path(target),
                source_path=source_path,
                url=url,
                sha256=sha256,
            )
        )
    return resources


def resolve_output_path(project_root: Path | str, target: Path | str) -> Path:
    root = Path(project_root).resolve()
    output_root = (root / DEFAULT_OUTPUT_SUBDIR).resolve()
    target_path = Path(target)
    if target_path.is_absolute():
        raise ValueError(f"resource target must be relative: {target}")
    destination = (output_root / target_path).resolve()
    try:
        destination.relative_to(output_root)
    except ValueError as exc:
        raise ValueError(f"resource target escapes {output_root}: {target}") from exc
    return destination


def resolve_package_path(package_root: Path | str, source_path: Path | str) -> Path:
    root = Path(package_root).resolve()
    source = Path(source_path)
    if source.is_absolute():
        raise ValueError(f"package source path must be relative: {source_path}")
    resolved = (root / source).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"package source escapes {root}: {source_path}") from exc
    return resolved


def default_package_root() -> Path:
    try:
        import tardis
    except ImportError as exc:
        raise RuntimeError("tardis package is required for package_file resources") from exc
    return Path(tardis.__file__).resolve().parent


def fetch_url_bytes(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "obsastro-sn-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def verify_sha256(data: bytes, expected_sha256: str | None, *, resource_id: str) -> None:
    if not expected_sha256:
        return
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise ValueError(f"sha256 mismatch for {resource_id}: expected {expected_sha256}, got {actual}")


def install_resource(
    resource: ModelResource,
    *,
    project_root: Path | str,
    package_root: Path | str | None = None,
    force: bool = False,
    dry_run: bool = False,
    fetch_url: FetchUrl = fetch_url_bytes,
    timeout: int = 120,
) -> InstallResult:
    destination = resolve_output_path(project_root, resource.target)
    if destination.exists() and not force:
        return InstallResult(resource.resource_id, "exists", resource.source_type, destination, destination.stat().st_size)

    if dry_run:
        return InstallResult(resource.resource_id, "would_write", resource.source_type, destination, 0)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if resource.source_type == "package_file":
        source_root = Path(package_root).resolve() if package_root is not None else default_package_root()
        if resource.source_path is None:
            raise ValueError(f"resource {resource.resource_id!r} has no package source path")
        source = resolve_package_path(source_root, resource.source_path)
        if not source.exists():
            raise FileNotFoundError(f"resource {resource.resource_id!r} source not found: {source}")
        shutil.copy2(source, destination)
        return InstallResult(resource.resource_id, "copied", resource.source_type, destination, destination.stat().st_size)

    if resource.url is None:
        raise ValueError(f"resource {resource.resource_id!r} has no source URL")
    data = fetch_url(resource.url, timeout)
    verify_sha256(data, resource.sha256, resource_id=resource.resource_id)
    destination.write_bytes(data)
    return InstallResult(resource.resource_id, "downloaded", resource.source_type, destination, len(data))


def install_resources(
    *,
    manifest_path: Path | str,
    project_root: Path | str,
    package_root: Path | str | None = None,
    source_types: Iterable[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    fetch_url: FetchUrl = fetch_url_bytes,
    timeout: int = 120,
) -> list[InstallResult]:
    allowed = set(source_types or {"package_file", "url"})
    resources = [resource for resource in load_manifest(manifest_path) if resource.source_type in allowed]
    return [
        install_resource(
            resource,
            project_root=project_root,
            package_root=package_root,
            force=force,
            dry_run=dry_run,
            fetch_url=fetch_url,
            timeout=timeout,
        )
        for resource in resources
    ]


def write_index(results: Iterable[InstallResult], path: Path | str) -> None:
    rows = [result.as_row() for result in results]
    index_path = Path(path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["resource_id", "status", "source_type", "output_path", "bytes_written"],
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare TARDIS density/abundance model resources without running simulations.",
    )
    parser.add_argument("--manifest", type=Path, default=None, help="model resource manifest YAML")
    parser.add_argument("--project-root", type=Path, default=None, help="project root; defaults to this repository")
    parser.add_argument("--package-root", type=Path, default=None, help="override installed tardis package root")
    parser.add_argument("--source-type", choices=["package_file", "url"], action="append", help="limit source type")
    parser.add_argument("--force", action="store_true", help="overwrite existing resource files")
    parser.add_argument("--dry-run", action="store_true", help="show what would be written without writing files")
    parser.add_argument("--timeout", type=int, default=120, help="URL download timeout in seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.project_root.resolve() if args.project_root is not None else project_root_from_module()
    manifest = args.manifest.resolve() if args.manifest is not None else root / DEFAULT_MANIFEST
    results = install_resources(
        manifest_path=manifest,
        project_root=root,
        package_root=args.package_root,
        source_types=args.source_type,
        force=args.force,
        dry_run=args.dry_run,
        timeout=args.timeout,
    )
    if not args.dry_run:
        write_index(results, root / DEFAULT_OUTPUT_SUBDIR / "model_resources_index.csv")
    for result in results:
        print(f"{result.status:10s} {result.resource_id:32s} {result.output_path}")
    print(f"resources processed: {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
