"""Packaged authority for non-visual conversation projection over immutable V16."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v17.manifest.json"
)
MANIFEST_SHA256: Final = (
    "2bc9dfebcca92da8bdcbe6efe2bfea222b7b3ea960cb72aae73f093bfc6b18f1"
)
PREDECESSOR_MODULE: Final = Path("core/onyx_packaged_runtime_hud_contract_v16.py")
PREDECESSOR_MODULE_SHA256: Final = (
    "fb94910cdc651ed2b6f5dcd6c2e62d27148b2cc2afc0a731d43951e11eead787"
)
PREDECESSOR_MANIFEST: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v16.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "01e96adc0b7dd4d3296d24895d322b600a80834e5a966ac33c71193e6264ef9d"
)


class PackagedRuntimeHudContractV17Error(RuntimeError):
    """The packaged V17 contract or immutable V16 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise PackagedRuntimeHudContractV17Error(
            "noncanonical packaged V17 path"
        )
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PackagedRuntimeHudContractV17Error(
            "packaged V17 input unavailable"
        ) from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise PackagedRuntimeHudContractV17Error("packaged V17 input is linked")
    return resolved


def verify_packaged_runtime_hud_contract(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_MODULE, PREDECESSOR_MODULE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise PackagedRuntimeHudContractV17Error(
                "immutable packaged V16 predecessor drifted"
            )
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise PackagedRuntimeHudContractV17Error("packaged V17 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackagedRuntimeHudContractV17Error(
            "packaged V17 manifest invalid"
        ) from error
    semantics = {
        "current_presence": "humanoid-presence-v13-transparent",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "palette_changed": False,
        "humanoid_runtime_changed": False,
        "conversation_projection_changed": True,
        "voice_pipeline_changed": False,
        "voice_preference_contract_changed": False,
        "setup_callback_deferred": True,
        "setup_request_coalescing": True,
        "configured_setup_dismissible": True,
        "first_boot_setup_mandatory": True,
        "frozen_shortcut_arguments_empty": True,
        "last_real_frame_continuity": True,
        "double_buffered_qml_backing": True,
        "validated_presentation_buffer": True,
        "transparent_compositor_surface": True,
        "provider_independent": True,
        "formal_release_ready": False,
    }
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.packaged-runtime-hud-contract.v17"
        or type(entries) is not list
        or len(entries) != 10
        or manifest.get("semantics") != semantics
    ):
        raise PackagedRuntimeHudContractV17Error(
            "packaged V17 contract drifted"
        )
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise PackagedRuntimeHudContractV17Error(
                "packaged V17 binding drifted"
            )
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise PackagedRuntimeHudContractV17Error(
                f"packaged V17 input drifted: {entry['path']}"
            )
    return {
        "schema": manifest["schema"],
        "runtime_inputs": len(entries),
        "current_presence": semantics["current_presence"],
        "live_renderer": semantics["live_renderer"],
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "frozen_shortcut_arguments_empty": True,
        "configured_setup_dismissible": True,
        "first_boot_setup_mandatory": True,
        "formal_release_ready": False,
    }


__all__ = [
    "MANIFEST_RELATIVE",
    "MANIFEST_SHA256",
    "PackagedRuntimeHudContractV17Error",
    "verify_packaged_runtime_hud_contract",
]
