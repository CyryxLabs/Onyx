"""Additive packaged-runtime HUD contract for the V35 runtime closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final

from scripts.package_hygiene import CAPABILITY_RUNTIME_FILES

MANIFEST_RELATIVE: Final = Path("core/onyx_packaged_runtime_hud_contract_v4.manifest.json")
PREDECESSOR_RELATIVE: Final = Path("core/onyx_packaged_runtime_hud_contract_v3.manifest.json")
PREDECESSOR_SHA256: Final = "5acad81a41f4469c95faebf6a527e338ab5b48f6253d229ab2c21e95f873e7ce"
PACKAGE_HYGIENE_RELATIVE: Final = Path("scripts/package_hygiene.py")
PACKAGE_HYGIENE_SHA256: Final = "4bde0827d7f6d981c59503cc097cf21cdf40221f46d19dcdc223962266d0619b"
REQUIRED_RUNTIME_FILES: Final = frozenset(CAPABILITY_RUNTIME_FILES)


class PackagedRuntimeHudContractV4Error(RuntimeError):
    """The V4 packaged runtime closure is unavailable or drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: Path) -> Path:
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts:
        raise PackagedRuntimeHudContractV4Error("noncanonical packaged V4 path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise PackagedRuntimeHudContractV4Error(f"packaged V4 input unavailable: {relative}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PackagedRuntimeHudContractV4Error(f"packaged V4 input escapes root: {relative}") from exc
    if resolved != candidate.absolute():
        raise PackagedRuntimeHudContractV4Error(f"packaged V4 input is linked: {relative}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise PackagedRuntimeHudContractV4Error("duplicate packaged V4 manifest key")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackagedRuntimeHudContractV4Error("packaged V4 manifest unreadable") from exc
    if type(value) is not dict:
        raise PackagedRuntimeHudContractV4Error("packaged V4 manifest must be an object")
    return value


def _artifact_root(records: list[dict[str, str]]) -> str:
    material = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(records, key=lambda item: item["path"])
    ).encode()
    return hashlib.sha256(material).hexdigest()


def verify_packaged_runtime_hud_contract_v4(stage: Path, *, project: Path) -> dict[str, object]:
    """Authenticate the exact V35 staged runtime against source authority."""
    source = Path(project).resolve(strict=True)
    runtime = Path(stage).resolve(strict=True)
    manifest = _strict_json(_canonical_file(source, MANIFEST_RELATIVE))
    predecessor = {"path": PREDECESSOR_RELATIVE.as_posix(), "sha256": PREDECESSOR_SHA256}
    hygiene = {"path": PACKAGE_HYGIENE_RELATIVE.as_posix(), "sha256": PACKAGE_HYGIENE_SHA256}
    semantics = {
        "capability_smoke": "provider-free-explicit",
        "checkout_fallback": False,
        "provider_dispatch": False,
        "tests_in_runtime": False,
        "package_hygiene": "current-source-authenticated",
    }
    if (
        set(manifest) != {"schema", "predecessor", "package_hygiene", "required_runtime_files", "artifact_root_sha256", "semantics"}
        or manifest.get("schema") != "onyx.packaged-runtime-hud.v4"
        or manifest.get("predecessor") != predecessor
        or manifest.get("package_hygiene") != hygiene
        or manifest.get("semantics") != semantics
    ):
        raise PackagedRuntimeHudContractV4Error("packaged V4 manifest contract drift")
    if _sha256(_canonical_file(source, PREDECESSOR_RELATIVE)) != PREDECESSOR_SHA256:
        raise PackagedRuntimeHudContractV4Error("packaged V3 predecessor drift")
    if _sha256(_canonical_file(source, PACKAGE_HYGIENE_RELATIVE)) != PACKAGE_HYGIENE_SHA256:
        raise PackagedRuntimeHudContractV4Error("current package hygiene drift")
    entries = manifest.get("required_runtime_files")
    if type(entries) is not list or len(entries) != len(REQUIRED_RUNTIME_FILES):
        raise PackagedRuntimeHudContractV4Error("current runtime membership drift")
    records: list[dict[str, str]] = []
    for relative, entry in zip(sorted(REQUIRED_RUNTIME_FILES), entries, strict=True):
        if type(entry) is not dict or set(entry) != {"path", "sha256"} or entry.get("path") != relative or type(entry.get("sha256")) is not str or len(entry["sha256"]) != 64:
            raise PackagedRuntimeHudContractV4Error("current runtime membership drift")
        if _sha256(_canonical_file(runtime, Path(relative))) != entry["sha256"]:
            raise PackagedRuntimeHudContractV4Error(f"packaged V4 runtime drift: {relative}")
        records.append(entry)
    if _artifact_root(records) != manifest.get("artifact_root_sha256"):
        raise PackagedRuntimeHudContractV4Error("packaged V4 artifact root drift")
    if (runtime / "tests").exists():
        raise PackagedRuntimeHudContractV4Error("packaged V4 tests are forbidden")
    return {"schema": manifest["schema"], "required_runtime_files": len(records), "artifact_root_sha256": manifest["artifact_root_sha256"], "tests_in_runtime": False}


__all__ = ["MANIFEST_RELATIVE", "PackagedRuntimeHudContractV4Error", "REQUIRED_RUNTIME_FILES", "verify_packaged_runtime_hud_contract_v4"]
