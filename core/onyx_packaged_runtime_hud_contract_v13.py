"""Packaged authority for deferred Setup stability over immutable V12."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v13.manifest.json"
)
MANIFEST_SHA256: Final = (
    "2d9fbea50794406ea396d2abe79817419e9554eb90af2acd1172e5602ad2e940"
)
PREDECESSOR_MODULE: Final = Path("core/onyx_packaged_runtime_hud_contract_v12.py")
PREDECESSOR_MODULE_SHA256: Final = (
    "9e7d1311cd4b08ff28488baf2212c21dd97f4c9126ea1f905099be0dd533e7fa"
)
PREDECESSOR_MANIFEST: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v12.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "d0bf6c1969f5951aede9d7b562655299a0cda8784039cc7b1b22d3312ab72867"
)


class PackagedRuntimeHudContractV13Error(RuntimeError):
    """The packaged V13 contract or immutable V12 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise PackagedRuntimeHudContractV13Error("noncanonical packaged V13 path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PackagedRuntimeHudContractV13Error(
            "packaged V13 input unavailable"
        ) from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise PackagedRuntimeHudContractV13Error("packaged V13 input is linked")
    return resolved


def verify_packaged_runtime_hud_contract(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_MODULE, PREDECESSOR_MODULE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise PackagedRuntimeHudContractV13Error(
                "immutable packaged V12 predecessor drifted"
            )
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise PackagedRuntimeHudContractV13Error("packaged V13 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackagedRuntimeHudContractV13Error(
            "packaged V13 manifest invalid"
        ) from error
    semantics = {
        "current_presence": "humanoid-presence-v12-continuity",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "palette_changed": False,
        "humanoid_runtime_changed": False,
        "voice_pipeline_changed": False,
        "voice_preference_contract_changed": False,
        "setup_callback_deferred": True,
        "setup_request_coalescing": True,
        "last_real_frame_continuity": True,
        "double_buffered_qml_backing": True,
        "validated_presentation_buffer": True,
        "transparent_compositor_surface": True,
        "provider_independent": True,
        "formal_release_ready": False,
    }
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.packaged-runtime-hud-contract.v13"
        or type(entries) is not list
        or len(entries) != 10
        or manifest.get("semantics") != semantics
    ):
        raise PackagedRuntimeHudContractV13Error("packaged V13 contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise PackagedRuntimeHudContractV13Error("packaged V13 binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise PackagedRuntimeHudContractV13Error(
                f"packaged V13 input drifted: {entry['path']}"
            )
    return {
        "schema": manifest["schema"],
        "runtime_inputs": len(entries),
        "current_presence": semantics["current_presence"],
        "live_renderer": semantics["live_renderer"],
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "setup_callback_deferred": True,
        "setup_request_coalescing": True,
        "formal_release_ready": False,
    }


__all__ = [
    "MANIFEST_RELATIVE",
    "MANIFEST_SHA256",
    "PackagedRuntimeHudContractV13Error",
    "verify_packaged_runtime_hud_contract",
]
