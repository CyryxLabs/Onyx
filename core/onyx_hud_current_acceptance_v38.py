"""Authenticate global pointer and camera-gesture attention over immutable V37."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V38-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "0c6d6e103829a1a7bf88e20baa23285bb5d24cbd6ac67b2ff6cecadd4887ffa2"
)
PREDECESSOR_ACCEPTANCE: Final = Path("core/onyx_hud_current_acceptance_v37.py")
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "21e621e4d5cd2e3383030836f7f751f7f6a9fa8bcb0a3abb4aad76a69e0ea55c"
)
PREDECESSOR_MANIFEST: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V37-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "9b9a945b564c0a9bde8da7ba9cf1b924e228150abe47bc5a78af704c50ab50ed"
)


class CurrentHudAcceptanceV38Error(RuntimeError):
    """The V38 attention delta or immutable V37 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CurrentHudAcceptanceV38Error("noncanonical V38 input path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentHudAcceptanceV38Error("V38 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentHudAcceptanceV38Error("V38 input is linked")
    return resolved


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_ACCEPTANCE, PREDECESSOR_ACCEPTANCE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise CurrentHudAcceptanceV38Error("immutable V37 predecessor drifted")
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise CurrentHudAcceptanceV38Error("V38 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentHudAcceptanceV38Error("V38 manifest invalid") from error
    semantics = {
        "palette_changed": False,
        "abstract_humanoid": True,
        "global_pointer_attention": True,
        "camera_gesture_attention": True,
        "camera_identity_processing": False,
        "second_camera_capture": False,
        "audio_pipeline_changed": False,
        "reduced_motion_static": True,
        "network_activity": False,
        "published": False,
    }
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.hud.current.v38.acceptance.v1"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != "qml/OnyxLiveShellV13.qml"
        or manifest.get("semantics") != semantics
        or type(entries) is not list
        or len(entries) != 11
    ):
        raise CurrentHudAcceptanceV38Error("V38 manifest contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise CurrentHudAcceptanceV38Error("V38 input binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise CurrentHudAcceptanceV38Error(
                f"V38 source input drifted: {entry['path']}"
            )
    return {
        "candidate": manifest["candidate"],
        "runtime_inputs": len(entries),
        "predecessor": "onyx-hud-v14-humanoid-presence-001",
        "global_pointer_attention": True,
        "camera_gesture_attention": True,
        "published": False,
    }


__all__ = [
    "CurrentHudAcceptanceV38Error",
    "MANIFEST_RELATIVE",
    "verify_current_hud_acceptance",
]
