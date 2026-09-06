"""Additive current HUD acceptance for the complete governed capability host."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final

from scripts.package_hygiene import CAPABILITY_RUNTIME_FILES


class CurrentHudAcceptanceV34Error(RuntimeError):
    """The V34 source delta or immutable V33 predecessor drifted."""


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V34-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V33-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "08cf9b873d709776514240a48c875966bb7d71258b117807ad72cd5a5907a4ce"
)
PREDECESSOR_ACCEPTANCE_RELATIVE: Final = Path(
    "core/onyx_hud_current_acceptance_v33.py"
)
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "756bc1806e1e7229b1b36b476584ee0eb93bf739e80410a1b923a920d0c30886"
)
CURRENT_ROOT: Final = Path("qml/OnyxLiveShellV11.qml")
CURRENT_RUNTIME_PATHS: Final = tuple(
    Path(relative)
    for relative in (
        *CAPABILITY_RUNTIME_FILES,
        "scripts/package_hygiene.py",
        "core/onyx_packaged_runtime_hud_contract_v3.py",
        "core/onyx_packaged_runtime_hud_contract_v3.manifest.json",
    )
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: Path) -> Path:
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts:
        raise CurrentHudAcceptanceV34Error("noncanonical V34 source path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise CurrentHudAcceptanceV34Error(f"V34 source input unavailable: {relative}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CurrentHudAcceptanceV34Error(
            f"V34 source input escapes root: {relative}"
        ) from exc
    if resolved != candidate.absolute():
        raise CurrentHudAcceptanceV34Error(f"V34 source input is linked: {relative}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise CurrentHudAcceptanceV34Error("duplicate V34 manifest key")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentHudAcceptanceV34Error("V34 manifest unreadable") from exc
    if type(value) is not dict:
        raise CurrentHudAcceptanceV34Error("V34 manifest must be an object")
    return value


def _artifact_root(records: list[dict[str, str]]) -> str:
    payload = "".join(
        f"{entry['path']}\0{entry['sha256']}\n"
        for entry in sorted(records, key=lambda item: item["path"])
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    """Authenticate V33 plus the exact current capability/package delta."""
    root = Path(project).resolve(strict=True)
    manifest = _strict_json(_canonical_file(root, MANIFEST_RELATIVE))
    predecessor = {
        "manifest_path": PREDECESSOR_MANIFEST_RELATIVE.as_posix(),
        "manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "acceptance_path": PREDECESSOR_ACCEPTANCE_RELATIVE.as_posix(),
        "acceptance_sha256": PREDECESSOR_ACCEPTANCE_SHA256,
    }
    semantics = {
        "source_acceptance": "V34-current-capability-package-successor",
        "release_version": "1.1.10",
        "stable_activation": "V24",
        "qml_root": "V11",
        "owner_scope_protections_preserved": True,
        "runtime_refusal_bypass": False,
        "packaged_test_sources": False,
        "package_hygiene": "current-source-authenticated",
        "capability_membership": "exact-current",
    }
    if (
        set(manifest)
        != {
            "schema",
            "candidate",
            "decision",
            "current_root",
            "predecessor",
            "runtime_inputs",
            "artifact_root_sha256",
            "semantics",
        }
        or manifest.get("schema") != "onyx.hud.current.v34.acceptance.v1"
        or manifest.get("candidate") != "onyx-hud-v34-1.1.10-capability-current-001"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != CURRENT_ROOT.as_posix()
        or manifest.get("predecessor") != predecessor
        or manifest.get("semantics") != semantics
    ):
        raise CurrentHudAcceptanceV34Error("V34 manifest contract drift")

    for relative, expected in (
        (PREDECESSOR_MANIFEST_RELATIVE, PREDECESSOR_MANIFEST_SHA256),
        (PREDECESSOR_ACCEPTANCE_RELATIVE, PREDECESSOR_ACCEPTANCE_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise CurrentHudAcceptanceV34Error(
                f"immutable V33 predecessor drift: {relative}"
            )

    entries = manifest.get("runtime_inputs")
    if type(entries) is not list or len(entries) != len(CURRENT_RUNTIME_PATHS):
        raise CurrentHudAcceptanceV34Error("V34 source membership drift")
    records: list[dict[str, str]] = []
    for relative, entry in zip(CURRENT_RUNTIME_PATHS, entries, strict=True):
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or entry.get("path") != relative.as_posix()
            or type(entry.get("sha256")) is not str
            or len(entry["sha256"]) != 64
        ):
            raise CurrentHudAcceptanceV34Error("V34 source membership drift")
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise CurrentHudAcceptanceV34Error(f"V34 source input drift: {relative}")
        records.append(entry)
    if _artifact_root(records) != manifest.get("artifact_root_sha256"):
        raise CurrentHudAcceptanceV34Error("V34 artifact root drift")
    return {
        "candidate": manifest["candidate"],
        "runtime_inputs": len(records),
        "capability_runtime_files": len(CAPABILITY_RUNTIME_FILES),
        "artifact_root_sha256": manifest["artifact_root_sha256"],
        "packaged_test_sources": False,
    }


__all__ = [
    "CURRENT_RUNTIME_PATHS",
    "CurrentHudAcceptanceV34Error",
    "MANIFEST_RELATIVE",
    "PREDECESSOR_ACCEPTANCE_RELATIVE",
    "PREDECESSOR_MANIFEST_RELATIVE",
    "verify_current_hud_acceptance",
]
