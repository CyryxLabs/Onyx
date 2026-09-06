"""Authenticate the additive living liquid-metal HUD over immutable V35."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final

MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V36-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "b3fdd3d35b44b673f9a82921f1fd884065d9c6b1beeaa97755c989d9faadd257"
)
PREDECESSOR_ACCEPTANCE: Final = Path("core/onyx_hud_current_acceptance_v35.py")
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "6e0262b48f2cfeeda1cc597b836f4afa915ac53d93f88195fb566363494ac9b3"
)
PREDECESSOR_MANIFEST: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V35-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "4fa14ef8a287c5c3ebd8c98e4fda1bf8685b524c6f2f8c9039ae0c9406ec48d4"
)


class CurrentHudAcceptanceV36Error(RuntimeError):
    """The V36 visual delta or immutable V35 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CurrentHudAcceptanceV36Error("noncanonical V36 input path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentHudAcceptanceV36Error("V36 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentHudAcceptanceV36Error("V36 input is linked")
    return resolved


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_ACCEPTANCE, PREDECESSOR_ACCEPTANCE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise CurrentHudAcceptanceV36Error("immutable V35 predecessor drifted")
    try:
        manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
        if _sha256(manifest_path) != MANIFEST_SHA256:
            raise CurrentHudAcceptanceV36Error("V36 manifest drifted")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except CurrentHudAcceptanceV36Error:
        raise
    except Exception as error:
        raise CurrentHudAcceptanceV36Error(
            "V36 predecessor or manifest unavailable"
        ) from error
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "onyx.hud.current.v36.acceptance.v1"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != "qml/OnyxLiveShellV12.qml"
        or manifest.get("semantics")
        != {
            "palette_changed": False,
            "living_liquid_metal": True,
            "state_driven": True,
            "audio_responsive": True,
            "reduced_motion_static": True,
            "one_qml_root": True,
            "network_activity": False,
            "published": False,
        }
        or type(manifest.get("runtime_inputs")) is not list
        or len(manifest["runtime_inputs"]) != 8
    ):
        raise CurrentHudAcceptanceV36Error("V36 manifest contract drifted")
    for entry in manifest["runtime_inputs"]:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise CurrentHudAcceptanceV36Error("V36 input binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise CurrentHudAcceptanceV36Error(
                f"V36 source input drifted: {entry['path']}"
            )
    return {
        "candidate": manifest["candidate"],
        "runtime_inputs": len(manifest["runtime_inputs"]),
        "predecessor": "onyx-hud-v35-1.1.10-packaged-runtime-v4-001",
        "palette_changed": False,
        "published": False,
    }


__all__ = [
    "CurrentHudAcceptanceV36Error",
    "MANIFEST_RELATIVE",
    "verify_current_hud_acceptance",
]
