"""Authenticate non-visual conversation projection over immutable HUD V47."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V48-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "a07f0bd02647995abae4bc103aeb989c6ae076ca1affdda058bd993cccf006ee"
)
PREDECESSOR_ACCEPTANCE: Final = Path("core/onyx_hud_current_acceptance_v47.py")
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "9801e50b08f98bbda9b44605e8328bf6c2cf1c99c7df95344bbb5cbcc67e6bc8"
)
PREDECESSOR_MANIFEST: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V47-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "6f7f593eff55461b645d9037ce39ee12a597c3088597783fc04a162c7df3aa9b"
)


class CurrentHudAcceptanceV48Error(RuntimeError):
    """The V48 shortcut delta or immutable V47 authority drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CurrentHudAcceptanceV48Error("noncanonical V48 input path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentHudAcceptanceV48Error("V48 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentHudAcceptanceV48Error("V48 input is linked")
    return resolved


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_ACCEPTANCE, PREDECESSOR_ACCEPTANCE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise CurrentHudAcceptanceV48Error("immutable V47 predecessor drifted")
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise CurrentHudAcceptanceV48Error("V48 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentHudAcceptanceV48Error("V48 manifest invalid") from error
    semantics = {
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "palette_changed": False,
        "humanoid_anatomy_changed": False,
        "humanoid_runtime_changed": False,
        "conversation_projection_changed": True,
        "voice_pipeline_changed": False,
        "voice_preference_contract_changed": False,
        "setup_callback_deferred": True,
        "setup_request_coalescing": True,
        "configured_setup_dismissible": True,
        "first_boot_setup_mandatory": True,
        "frozen_shortcut_arguments_empty": True,
        "live_renderer": "three.js-webgl",
        "last_real_frame_continuity": True,
        "double_buffered_qml_backing": True,
        "validated_presentation_buffer": True,
        "transparent_compositor_surface": True,
        "readiness_retry": True,
        "network_activity": False,
        "published": False,
    }
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.hud.current.v48.acceptance.v1"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != "qml/OnyxLiveShellV16.qml"
        or manifest.get("semantics") != semantics
        or type(entries) is not list
        or len(entries) != 10
    ):
        raise CurrentHudAcceptanceV48Error("V48 manifest contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise CurrentHudAcceptanceV48Error("V48 input binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise CurrentHudAcceptanceV48Error(
                f"V48 source input drifted: {entry['path']}"
            )
    return {
        "candidate": manifest["candidate"],
        "runtime_inputs": len(entries),
        "predecessor": "onyx-hud-transparent-humanoid-001",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "frozen_shortcut_arguments_empty": True,
        "configured_setup_dismissible": True,
        "first_boot_setup_mandatory": True,
        "published": False,
    }


__all__ = [
    "CurrentHudAcceptanceV48Error",
    "MANIFEST_RELATIVE",
    "MANIFEST_SHA256",
    "verify_current_hud_acceptance",
]
