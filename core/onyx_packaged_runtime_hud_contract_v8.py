"""Packaged authority for stable humanoid attention over immutable V7."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v8.manifest.json"
)
MANIFEST_SHA256: Final = (
    "6ea70210fdb87047a2edc9a8b2066baabb596d173054ab8fa67e7ca6be7a3163"
)
PREDECESSOR_MODULE: Final = Path("core/onyx_packaged_runtime_hud_contract_v7.py")
PREDECESSOR_MODULE_SHA256: Final = (
    "c2bb59c9ae3a6c346840738b47904672eb10ddb1275edb5826666e57aca87680"
)
PREDECESSOR_MANIFEST: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v7.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "9322fbed4119b0b450610aa49d7b32a4dabf95b5a2a59d7e8c749f8ab504702a"
)


class PackagedRuntimeHudContractV8Error(RuntimeError):
    """The packaged V8 contract or immutable V7 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise PackagedRuntimeHudContractV8Error("noncanonical packaged V8 path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PackagedRuntimeHudContractV8Error("packaged V8 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise PackagedRuntimeHudContractV8Error("packaged V8 input is linked")
    return resolved


def verify_packaged_runtime_hud_contract(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_MODULE, PREDECESSOR_MODULE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise PackagedRuntimeHudContractV8Error(
                "immutable packaged V7 predecessor drifted"
            )
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise PackagedRuntimeHudContractV8Error("packaged V8 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackagedRuntimeHudContractV8Error("packaged V8 manifest invalid") from error
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.packaged-runtime-hud-contract.v8"
        or type(entries) is not list
        or len(entries) != 8
        or manifest.get("semantics")
        != {
            "current_orb": "humanoid-presence-v10",
            "global_pointer_attention": True,
            "camera_gesture_attention": True,
            "attention_bridge_coalesced": True,
            "intermittent_flicker_guard": True,
            "governed_native_close": True,
            "provider_independent": True,
            "formal_release_ready": False,
        }
    ):
        raise PackagedRuntimeHudContractV8Error("packaged V8 contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise PackagedRuntimeHudContractV8Error("packaged V8 binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise PackagedRuntimeHudContractV8Error(
                f"packaged V8 input drifted: {entry['path']}"
            )
    return {
        "schema": manifest["schema"],
        "runtime_inputs": len(entries),
        "current_orb": manifest["semantics"]["current_orb"],
        "camera_gesture_attention": True,
        "attention_bridge_coalesced": True,
        "intermittent_flicker_guard": True,
        "governed_native_close": True,
        "formal_release_ready": False,
    }


__all__ = [
    "MANIFEST_RELATIVE",
    "PackagedRuntimeHudContractV8Error",
    "verify_packaged_runtime_hud_contract",
]
