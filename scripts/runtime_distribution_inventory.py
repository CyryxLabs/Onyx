"""Resolve and inventory the exact runtime distributions shipped by Onyx."""

from __future__ import annotations

import hashlib
import json
import os
import re
from email.parser import BytesParser
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


INVENTORY_CONTRACT = "OnyxBundleInventory.v1"
EXCLUDED_OPTIONAL_DISTRIBUTIONS = frozenset({"mouseinfo", "pypiwin32"})
LEGAL_FILE_RE = re.compile(
    r"(?:^|/)(?:licen[cs]e[^/]*|copying[^/]*|notice[^/]*|copyright[^/]*)(?:/|$)",
    re.IGNORECASE,
)


class BundleInventoryError(RuntimeError):
    """A bundle cannot be reconciled with its runtime dependency closure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _marker_applies(marker: object, extras: Iterable[str]) -> bool:
    if marker is None:
        return True
    values = set(extras) or {""}
    environment = default_environment()
    return any(
        marker.evaluate({**environment, "extra": extra})  # type: ignore[union-attr]
        for extra in values
    )


def runtime_distribution_closure(requirements_path: Path) -> tuple[metadata.Distribution, ...]:
    """Resolve direct requirements and active extras for the current host."""

    if not requirements_path.is_file() or requirements_path.is_symlink():
        raise BundleInventoryError(f"runtime requirements are unavailable: {requirements_path}")
    queued: list[tuple[str, frozenset[str]]] = []
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        requirement = Requirement(raw)
        if _marker_applies(requirement.marker, requirement.extras):
            queued.append((requirement.name, frozenset(requirement.extras)))

    selected_extras: dict[str, frozenset[str]] = {}
    resolved: dict[str, metadata.Distribution] = {}
    while queued:
        requested_name, extras = queued.pop()
        key = canonicalize_name(requested_name)
        if key in EXCLUDED_OPTIONAL_DISTRIBUTIONS:
            continue
        previous = selected_extras.get(key, frozenset())
        combined = previous | extras
        if key in resolved and combined == previous:
            continue
        try:
            distribution = metadata.distribution(requested_name)
        except metadata.PackageNotFoundError as exc:
            raise BundleInventoryError(
                f"runtime distribution is not installed: {requested_name}"
            ) from exc
        selected_extras[key] = combined
        resolved[key] = distribution
        for raw_dependency in distribution.requires or ():
            dependency = Requirement(raw_dependency)
            if _marker_applies(dependency.marker, combined):
                queued.append((dependency.name, frozenset(dependency.extras)))
    return tuple(resolved[key] for key in sorted(resolved))


def expected_runtime_identities(requirements_path: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                canonicalize_name(str(distribution.metadata["Name"])),
                distribution.version,
            )
            for distribution in runtime_distribution_closure(requirements_path)
        )
    )


def _canonical_relative(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise BundleInventoryError(f"bundle path escaped root: {path}") from exc
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise BundleInventoryError(f"bundle path is not canonical: {relative}")
    return relative


def _distribution_record(metadata_path: Path, bundle: Path) -> dict[str, Any]:
    try:
        parsed = BytesParser().parsebytes(metadata_path.read_bytes())
    except (OSError, UnicodeError) as exc:
        raise BundleInventoryError(f"distribution metadata is unreadable: {metadata_path}") from exc
    name = str(parsed.get("Name", "")).strip()
    version = str(parsed.get("Version", "")).strip()
    if not name or not version:
        raise BundleInventoryError(f"distribution metadata lacks identity: {metadata_path}")
    metadata_dir = metadata_path.parent
    legal_files = []
    for candidate in sorted(metadata_dir.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        relative = _canonical_relative(candidate, bundle)
        within_metadata = candidate.relative_to(metadata_dir).as_posix()
        if LEGAL_FILE_RE.search(within_metadata):
            legal_files.append(
                {
                    "path": relative,
                    "size": candidate.stat().st_size,
                    "sha256": sha256_file(candidate),
                }
            )
    license_expression = (
        str(parsed.get("License-Expression", "")).strip()
        or str(parsed.get("License", "")).strip()
        or "NOASSERTION"
    )
    return {
        "name": name,
        "normalizedName": canonicalize_name(name),
        "version": version,
        "licenseDeclared": license_expression,
        "metadataPath": _canonical_relative(metadata_path, bundle),
        "metadataSha256": sha256_file(metadata_path),
        "legalFiles": legal_files,
    }


def build_bundle_inventory(
    *, bundle: Path, version: str, system: str, architecture: str,
    requirements_path: Path,
) -> dict[str, Any]:
    """Hash the bundle and prove every expected runtime distribution metadata set."""

    bundle = bundle.resolve()
    if not bundle.is_dir() or bundle.is_symlink():
        raise BundleInventoryError(f"bundle is unavailable: {bundle}")
    files: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []
    aggregate = hashlib.sha256()
    for candidate in sorted(bundle.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = _canonical_relative(candidate, bundle)
        if candidate.is_symlink():
            target = os.readlink(candidate)
            links.append({"path": relative, "target": target})
            aggregate.update(f"L {relative}\0{target}\n".encode("utf-8"))
        elif candidate.is_file():
            size = candidate.stat().st_size
            digest = sha256_file(candidate)
            files.append({"path": relative, "size": size, "sha256": digest})
            aggregate.update(f"F {digest} {size} {relative}\n".encode("utf-8"))

    distributions: dict[tuple[str, str], dict[str, Any]] = {}
    for metadata_path in bundle.rglob("*.dist-info/METADATA"):
        if metadata_path.is_symlink() or not metadata_path.is_file():
            raise BundleInventoryError("distribution metadata must be a regular file")
        record = _distribution_record(metadata_path, bundle)
        key = (record["normalizedName"], record["version"])
        previous = distributions.get(key)
        if previous is not None and previous != record:
            raise BundleInventoryError(
                f"conflicting duplicate distribution metadata: {key[0]}=={key[1]}"
            )
        distributions[key] = record

    expected = set(expected_runtime_identities(requirements_path))
    present = set(distributions)
    missing = sorted(expected - present)
    if missing:
        rendered = ", ".join(f"{name}=={version}" for name, version in missing)
        raise BundleInventoryError(f"bundle lacks runtime distribution metadata: {rendered}")
    selected = [distributions[key] for key in sorted(distributions)]
    distribution_root = hashlib.sha256(
        "".join(
            f"{item['metadataSha256']} {item['normalizedName']}=={item['version']}\n"
            for item in selected
        ).encode("utf-8")
    ).hexdigest()
    return {
        "contract": INVENTORY_CONTRACT,
        "product": "Onyx",
        "version": version,
        "system": system,
        "architecture": architecture,
        "bundleRootSha256": aggregate.hexdigest(),
        "fileCount": len(files),
        "symlinkCount": len(links),
        "files": files,
        "symlinks": links,
        "runtimeDistributionCount": len(selected),
        "runtimeDistributionRootSha256": distribution_root,
        "runtimeDistributions": selected,
    }


def write_bundle_inventory(
    *, bundle: Path, output: Path, version: str, system: str,
    architecture: str, requirements_path: Path,
) -> dict[str, Any]:
    inventory = build_bundle_inventory(
        bundle=bundle,
        version=version,
        system=system,
        architecture=architecture,
        requirements_path=requirements_path,
    )
    output.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return inventory
