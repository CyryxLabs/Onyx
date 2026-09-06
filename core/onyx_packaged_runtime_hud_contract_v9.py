"""Packaged authority for calibrated humanoid attention over immutable V8."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v9.manifest.json"
)
MANIFEST_SHA256: Final = (
    "636da9d3bdfb24ae687f670f52f711cb111a09e0fa335217a2c0ba6dd8c9de2b"
)
PREDECESSOR_MODULE: Final = Path("core/onyx_packaged_runtime_hud_contract_v8.py")
PREDECESSOR_MODULE_SHA256: Final = (
    "3b8d9803f43e18f9f662d2c6bcead4c1de8a913f631b7ef97541be55b9dc433b"
)
PREDECESSOR_MANIFEST: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v8.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "6ea70210fdb87047a2edc9a8b2066baabb596d173054ab8fa67e7ca6be7a3163"
)


class PackagedRuntimeHudContractV9Error(RuntimeError):
    """The packaged V9 contract or immutable V8 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise PackagedRuntimeHudContractV9Error("noncanonical packaged V9 path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PackagedRuntimeHudContractV9Error("packaged V9 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise PackagedRuntimeHudContractV9Error("packaged V9 input is linked")
    return resolved


def verify_packaged_runtime_hud_contract(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_MODULE, PREDECESSOR_MODULE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise PackagedRuntimeHudContractV9Error(
                "immutable packaged V8 predecessor drifted"
            )
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise PackagedRuntimeHudContractV9Error("packaged V9 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackagedRuntimeHudContractV9Error("packaged V9 manifest invalid") from error
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.packaged-runtime-hud-contract.v9"
        or type(entries) is not list
        or len(entries) != 8
        or manifest.get("semantics")
        != {
            "current_orb": "humanoid-presence-v10",
            "global_pointer_attention": True,
            "camera_gesture_attention": True,
            "session_hand_calibration": True,
            "camera_frame_retention": False,
            "attention_bridge_coalesced": True,
            "intermittent_flicker_guard": True,
            "governed_native_close": True,
            "provider_independent": True,
            "formal_release_ready": False,
        }
    ):
        raise PackagedRuntimeHudContractV9Error("packaged V9 contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise PackagedRuntimeHudContractV9Error("packaged V9 binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise PackagedRuntimeHudContractV9Error(
                f"packaged V9 input drifted: {entry['path']}"
            )
    return {
        "schema": manifest["schema"],
        "runtime_inputs": len(entries),
        "current_orb": manifest["semantics"]["current_orb"],
        "camera_gesture_attention": True,
        "session_hand_calibration": True,
        "attention_bridge_coalesced": True,
        "intermittent_flicker_guard": True,
        "governed_native_close": True,
        "formal_release_ready": False,
    }


__all__ = [
    "MANIFEST_RELATIVE",
    "PackagedRuntimeHudContractV9Error",
    "verify_packaged_runtime_hud_contract",
]
