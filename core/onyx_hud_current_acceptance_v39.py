"""Authenticate stable multimodal humanoid attention over immutable V38."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V39-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "61058ff6f9aff57a86e9480620d88df4a85beabd685c4100ffb8cdb376deb8b2"
)
PREDECESSOR_ACCEPTANCE: Final = Path("core/onyx_hud_current_acceptance_v38.py")
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "b78d61feab5a86e1f646055192b825936ccf5136e41f6cfe3b4fda39c9cdcbf3"
)
PREDECESSOR_MANIFEST: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V38-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "0c6d6e103829a1a7bf88e20baa23285bb5d24cbd6ac67b2ff6cecadd4887ffa2"
)


class CurrentHudAcceptanceV39Error(RuntimeError):
    """The V39 stability delta or immutable V38 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CurrentHudAcceptanceV39Error("noncanonical V39 input path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentHudAcceptanceV39Error("V39 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentHudAcceptanceV39Error("V39 input is linked")
    return resolved


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_ACCEPTANCE, PREDECESSOR_ACCEPTANCE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise CurrentHudAcceptanceV39Error("immutable V38 predecessor drifted")
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise CurrentHudAcceptanceV39Error("V39 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentHudAcceptanceV39Error("V39 manifest invalid") from error
    semantics = {
        "palette_changed": False,
        "abstract_humanoid": True,
        "three_js_runtime": True,
        "source_image_rendering": False,
        "global_pointer_attention": True,
        "camera_gesture_attention": True,
        "attention_bridge_coalesced": True,
        "intermittent_flicker_guard": True,
        "governed_native_close": True,
        "camera_identity_processing": False,
        "second_camera_capture": False,
        "audio_pipeline_changed": False,
        "reduced_motion_static": True,
        "network_activity": False,
        "published": False,
    }
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.hud.current.v39.acceptance.v1"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != "qml/OnyxLiveShellV13.qml"
        or manifest.get("semantics") != semantics
        or type(entries) is not list
        or len(entries) != 13
    ):
        raise CurrentHudAcceptanceV39Error("V39 manifest contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise CurrentHudAcceptanceV39Error("V39 input binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise CurrentHudAcceptanceV39Error(
                f"V39 source input drifted: {entry['path']}"
            )
    return {
        "candidate": manifest["candidate"],
        "runtime_inputs": len(entries),
        "predecessor": "onyx-hud-v14-multimodal-attention-001",
        "global_pointer_attention": True,
        "camera_gesture_attention": True,
        "attention_bridge_coalesced": True,
        "intermittent_flicker_guard": True,
        "governed_native_close": True,
        "published": False,
    }


__all__ = [
    "CurrentHudAcceptanceV39Error",
    "MANIFEST_RELATIVE",
    "verify_current_hud_acceptance",
]
