"""Authenticate the temporally stable humanoid over immutable HUD V40."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V41-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "e5a9cfd05f9efdba8fa029c89d707e2977a284e3d1daae769aa76c56397b812e"
)
PREDECESSOR_ACCEPTANCE: Final = Path("core/onyx_hud_current_acceptance_v40.py")
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "0862ea941ea587ef198838f05c7dfb46853af237fd29aee307e59432ccf19420"
)
PREDECESSOR_MANIFEST: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V40-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "aa49c24d7ee001f67a2e3e44969c140d4e93ada4d34508f46e2ed17a44bcd39e"
)


class CurrentHudAcceptanceV41Error(RuntimeError):
    """The V41 stability delta or immutable V40 authority drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CurrentHudAcceptanceV41Error("noncanonical V41 input path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentHudAcceptanceV41Error("V41 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentHudAcceptanceV41Error("V41 input is linked")
    return resolved


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_ACCEPTANCE, PREDECESSOR_ACCEPTANCE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise CurrentHudAcceptanceV41Error("immutable V40 predecessor drifted")
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise CurrentHudAcceptanceV41Error("V41 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentHudAcceptanceV41Error("V41 manifest invalid") from error
    semantics = {
        "layout_changed": False,
        "palette_changed": False,
        "humanoid_anatomy_changed": False,
        "voice_pipeline_changed": False,
        "capability_surface_changed": False,
        "single_authoritative_animation_loop": True,
        "preserved_webgl_drawing_buffer": True,
        "opaque_hud_matched_surface": True,
        "webgl_context_recovery": True,
        "temporal_ready_tested": True,
        "temporal_listening_tested": True,
        "temporal_speaking_tested": True,
        "global_pointer_attention": True,
        "camera_gesture_attention": True,
        "camera_frame_retention": False,
        "reduced_motion_static": True,
        "network_activity": False,
        "published": False,
    }
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.hud.current.v41.acceptance.v1"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != "qml/OnyxLiveShellV14.qml"
        or manifest.get("semantics") != semantics
        or type(entries) is not list
        or len(entries) != 11
    ):
        raise CurrentHudAcceptanceV41Error("V41 manifest contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise CurrentHudAcceptanceV41Error("V41 input binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise CurrentHudAcceptanceV41Error(
                f"V41 source input drifted: {entry['path']}"
            )
    return {
        "candidate": manifest["candidate"],
        "runtime_inputs": len(entries),
        "predecessor": "onyx-hud-v14-calibrated-multimodal-attention-001",
        "single_authoritative_animation_loop": True,
        "preserved_webgl_drawing_buffer": True,
        "opaque_hud_matched_surface": True,
        "temporal_states_tested": ["READY", "LISTENING", "SPEAKING"],
        "published": False,
    }


__all__ = [
    "CurrentHudAcceptanceV41Error",
    "MANIFEST_RELATIVE",
    "verify_current_hud_acceptance",
]
