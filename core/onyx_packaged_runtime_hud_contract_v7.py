"""Packaged authority for multimodal humanoid attention over immutable V6."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v7.manifest.json"
)
MANIFEST_SHA256: Final = (
    "9322fbed4119b0b450610aa49d7b32a4dabf95b5a2a59d7e8c749f8ab504702a"
)
PREDECESSOR_MODULE: Final = Path("core/onyx_packaged_runtime_hud_contract_v6.py")
PREDECESSOR_MODULE_SHA256: Final = (
    "c9132462a47d4f99dbe22d10c69bba4b7f4f8f6dc574309a9b8f5bf61b5d335e"
)
PREDECESSOR_MANIFEST: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v6.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "9fe601cc6449be0d08d3811bcafd4a5d8313eb14d51a1a0d6b82724b75bc372e"
)


class PackagedRuntimeHudContractV7Error(RuntimeError):
    """The packaged V7 contract or immutable V6 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if pure.is_absolute() or pure.as_posix() != relative or ".." in pure.parts:
        raise PackagedRuntimeHudContractV7Error("noncanonical packaged V7 path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PackagedRuntimeHudContractV7Error("packaged V7 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise PackagedRuntimeHudContractV7Error("packaged V7 input is linked")
    return resolved


def verify_packaged_runtime_hud_contract(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_MODULE, PREDECESSOR_MODULE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise PackagedRuntimeHudContractV7Error(
                "immutable packaged V6 predecessor drifted"
            )
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise PackagedRuntimeHudContractV7Error("packaged V7 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackagedRuntimeHudContractV7Error("packaged V7 manifest invalid") from error
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.packaged-runtime-hud-contract.v7"
        or type(entries) is not list
        or len(entries) != 8
        or manifest.get("semantics")
        != {
            "current_orb": "humanoid-presence-v10",
            "global_pointer_attention": True,
            "camera_gesture_attention": True,
            "provider_independent": True,
            "formal_release_ready": False,
        }
    ):
        raise PackagedRuntimeHudContractV7Error("packaged V7 contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise PackagedRuntimeHudContractV7Error("packaged V7 binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise PackagedRuntimeHudContractV7Error(
                f"packaged V7 input drifted: {entry['path']}"
            )
    return {
        "schema": manifest["schema"],
        "runtime_inputs": len(entries),
        "current_orb": manifest["semantics"]["current_orb"],
        "camera_gesture_attention": True,
        "formal_release_ready": False,
    }


__all__ = [
    "MANIFEST_RELATIVE",
    "PackagedRuntimeHudContractV7Error",
    "verify_packaged_runtime_hud_contract",
]
