"""Additive packaged-runtime HUD contract for the current capability slice."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final

from scripts.package_hygiene import CAPABILITY_RUNTIME_FILES

MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v3.manifest.json"
)
PREDECESSOR_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v2.manifest.json"
)
PREDECESSOR_SHA256: Final = (
    "c98c35d0a527a89e61859c6aa951074891ff31d20df2422d1283a9eb905ce377"
)
PACKAGE_HYGIENE_RELATIVE: Final = Path("scripts/package_hygiene.py")
PACKAGE_HYGIENE_SHA256: Final = (
    "ecc4f3b964e33ad7f11e9294b4b5a208cfc0863b285a159c8bcb341b3cd5a741"
)
REQUIRED_HOST_PORTS: Final = frozenset(CAPABILITY_RUNTIME_FILES)


class PackagedRuntimeHudContractV3Error(RuntimeError):
    """The V3 packaged runtime closure is unavailable or drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: Path) -> Path:
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts:
        raise PackagedRuntimeHudContractV3Error("noncanonical packaged V3 path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise PackagedRuntimeHudContractV3Error(
            f"packaged V3 input unavailable: {relative}"
        )
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PackagedRuntimeHudContractV3Error(
            f"packaged V3 input escapes root: {relative}"
        ) from exc
    if resolved != candidate.absolute():
        raise PackagedRuntimeHudContractV3Error(
            f"packaged V3 input is linked: {relative}"
        )
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise PackagedRuntimeHudContractV3Error(
                    "duplicate packaged V3 manifest key"
                )
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackagedRuntimeHudContractV3Error(
            "packaged V3 manifest unreadable"
        ) from exc
    if type(value) is not dict:
        raise PackagedRuntimeHudContractV3Error("packaged V3 manifest must be an object")
    return value


def _artifact_root(records: list[dict[str, str]]) -> str:
    material = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(records, key=lambda item: item["path"])
    ).encode()
    return hashlib.sha256(material).hexdigest()


def verify_packaged_runtime_hud_contract_v3(
    stage: Path, *, project: Path
) -> dict[str, object]:
    """Authenticate the current staged capabilities against source authority."""
    source = Path(project).resolve(strict=True)
    runtime = Path(stage).resolve(strict=True)
    manifest = _strict_json(_canonical_file(source, MANIFEST_RELATIVE))
    predecessor = {
        "path": PREDECESSOR_RELATIVE.as_posix(),
        "sha256": PREDECESSOR_SHA256,
    }
    hygiene = {
        "path": PACKAGE_HYGIENE_RELATIVE.as_posix(),
        "sha256": PACKAGE_HYGIENE_SHA256,
    }
    semantics = {
        "capability_smoke": "provider-free-explicit",
        "checkout_fallback": False,
        "provider_dispatch": False,
        "tests_in_runtime": False,
        "package_hygiene": "current-source-authenticated",
    }
    if (
        set(manifest)
        != {
            "schema",
            "predecessor",
            "package_hygiene",
            "required_host_ports",
            "artifact_root_sha256",
            "semantics",
        }
        or manifest.get("schema") != "onyx.packaged-runtime-hud.v3"
        or manifest.get("predecessor") != predecessor
        or manifest.get("package_hygiene") != hygiene
        or manifest.get("semantics") != semantics
    ):
        raise PackagedRuntimeHudContractV3Error("packaged V3 manifest contract drift")
    if _sha256(_canonical_file(source, PREDECESSOR_RELATIVE)) != PREDECESSOR_SHA256:
        raise PackagedRuntimeHudContractV3Error("packaged V2 predecessor drift")
    if _sha256(_canonical_file(source, PACKAGE_HYGIENE_RELATIVE)) != PACKAGE_HYGIENE_SHA256:
        raise PackagedRuntimeHudContractV3Error("current package hygiene drift")

    entries = manifest.get("required_host_ports")
    if type(entries) is not list or len(entries) != len(REQUIRED_HOST_PORTS):
        raise PackagedRuntimeHudContractV3Error("current host port membership drift")
    records: list[dict[str, str]] = []
    for relative, entry in zip(sorted(REQUIRED_HOST_PORTS), entries, strict=True):
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or entry.get("path") != relative
            or type(entry.get("sha256")) is not str
            or len(entry["sha256"]) != 64
        ):
            raise PackagedRuntimeHudContractV3Error("current host port membership drift")
        if _sha256(_canonical_file(runtime, Path(relative))) != entry["sha256"]:
            raise PackagedRuntimeHudContractV3Error(
                f"packaged V3 host port drift: {relative}"
            )
        records.append(entry)
    if _artifact_root(records) != manifest.get("artifact_root_sha256"):
        raise PackagedRuntimeHudContractV3Error("packaged V3 artifact root drift")
    if (runtime / "tests").exists():
        raise PackagedRuntimeHudContractV3Error("packaged V3 tests are forbidden")
    return {
        "schema": manifest["schema"],
        "required_host_ports": len(records),
        "artifact_root_sha256": manifest["artifact_root_sha256"],
        "tests_in_runtime": False,
        "checkout_fallback": False,
        "provider_dispatch": False,
    }


__all__ = [
    "MANIFEST_RELATIVE",
    "PACKAGE_HYGIENE_RELATIVE",
    "PREDECESSOR_RELATIVE",
    "PackagedRuntimeHudContractV3Error",
    "REQUIRED_HOST_PORTS",
    "verify_packaged_runtime_hud_contract_v3",
]
