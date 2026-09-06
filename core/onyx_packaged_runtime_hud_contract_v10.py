"""Packaged authority for the temporally stable humanoid over immutable V9."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v10.manifest.json"
)
MANIFEST_SHA256: Final = (
    "9e05366f95ebffb28eba0e433457950e72dc0464b75edaff9fe1dcc53f061c54"
)
PREDECESSOR_MODULE: Final = Path("core/onyx_packaged_runtime_hud_contract_v9.py")
PREDECESSOR_MODULE_SHA256: Final = (
    "d8ad3673d001d1769a3c6e87d975d9233bfe83467acea740115fb4447e69c335"
)
PREDECESSOR_MANIFEST: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v9.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "636da9d3bdfb24ae687f670f52f711cb111a09e0fa335217a2c0ba6dd8c9de2b"
)


class PackagedRuntimeHudContractV10Error(RuntimeError):
    """The packaged V10 contract or immutable V9 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise PackagedRuntimeHudContractV10Error("noncanonical packaged V10 path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PackagedRuntimeHudContractV10Error(
            "packaged V10 input unavailable"
        ) from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise PackagedRuntimeHudContractV10Error("packaged V10 input is linked")
    return resolved


def verify_packaged_runtime_hud_contract(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_MODULE, PREDECESSOR_MODULE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise PackagedRuntimeHudContractV10Error(
                "immutable packaged V9 predecessor drifted"
            )
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise PackagedRuntimeHudContractV10Error("packaged V10 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackagedRuntimeHudContractV10Error(
            "packaged V10 manifest invalid"
        ) from error
    semantics = {
        "current_orb": "humanoid-presence-v11-stable",
        "single_authoritative_animation_loop": True,
        "preserved_webgl_drawing_buffer": True,
        "opaque_hud_matched_surface": True,
        "webgl_context_recovery": True,
        "layout_changed": False,
        "palette_changed": False,
        "voice_pipeline_changed": False,
        "capability_surface_changed": False,
        "provider_independent": True,
        "formal_release_ready": False,
    }
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.packaged-runtime-hud-contract.v10"
        or type(entries) is not list
        or len(entries) != 8
        or manifest.get("semantics") != semantics
    ):
        raise PackagedRuntimeHudContractV10Error("packaged V10 contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise PackagedRuntimeHudContractV10Error("packaged V10 binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise PackagedRuntimeHudContractV10Error(
                f"packaged V10 input drifted: {entry['path']}"
            )
    return {
        "schema": manifest["schema"],
        "runtime_inputs": len(entries),
        "current_orb": semantics["current_orb"],
        "single_authoritative_animation_loop": True,
        "preserved_webgl_drawing_buffer": True,
        "opaque_hud_matched_surface": True,
        "formal_release_ready": False,
    }


__all__ = [
    "MANIFEST_RELATIVE",
    "PackagedRuntimeHudContractV10Error",
    "verify_packaged_runtime_hud_contract",
]
