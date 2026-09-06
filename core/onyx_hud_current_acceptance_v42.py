"""Authenticate the compositor-continuity humanoid over immutable HUD V41."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V42-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "1f5568cb5331cfcd5fc56bfbf02bc3b631a7351bc244ec85f7892bee80d419f5"
)
PREDECESSOR_ACCEPTANCE: Final = Path("core/onyx_hud_current_acceptance_v41.py")
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "13ba1e2cb427b06da5245383514681c44db2d00e4e9ffbe19cb14fdc57efa729"
)
PREDECESSOR_MANIFEST: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V41-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "e5a9cfd05f9efdba8fa029c89d707e2977a284e3d1daae769aa76c56397b812e"
)


class CurrentHudAcceptanceV42Error(RuntimeError):
    """The V42 continuity delta or immutable V41 authority drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CurrentHudAcceptanceV42Error("noncanonical V42 input path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentHudAcceptanceV42Error("V42 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentHudAcceptanceV42Error("V42 input is linked")
    return resolved


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_ACCEPTANCE, PREDECESSOR_ACCEPTANCE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise CurrentHudAcceptanceV42Error("immutable V41 predecessor drifted")
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise CurrentHudAcceptanceV42Error("V42 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentHudAcceptanceV42Error("V42 manifest invalid") from error
    semantics = {
        "layout_changed": False,
        "palette_changed": False,
        "humanoid_anatomy_changed": False,
        "voice_pipeline_changed": False,
        "capability_surface_changed": False,
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
        manifest.get("schema") != "onyx.hud.current.v42.acceptance.v1"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != "qml/OnyxLiveShellV15.qml"
        or manifest.get("semantics") != semantics
        or type(entries) is not list
        or len(entries) != 9
    ):
        raise CurrentHudAcceptanceV42Error("V42 manifest contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise CurrentHudAcceptanceV42Error("V42 input binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise CurrentHudAcceptanceV42Error(
                f"V42 source input drifted: {entry['path']}"
            )
    return {
        "candidate": manifest["candidate"],
        "runtime_inputs": len(entries),
        "predecessor": "onyx-hud-v15-temporally-stable-humanoid-001",
        "live_renderer": "three.js-webgl",
        "last_real_frame_continuity": True,
        "double_buffered_qml_backing": True,
        "published": False,
    }


__all__ = [
    "CurrentHudAcceptanceV42Error",
    "MANIFEST_RELATIVE",
    "verify_current_hud_acceptance",
]
