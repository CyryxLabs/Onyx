"""Authenticate Setup voice selection over immutable HUD V42."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V43-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "5046fd657453179e530dbb8a5eb9b51780b3526b091503d363feaab5cd3dcdfb"
)
PREDECESSOR_ACCEPTANCE: Final = Path("core/onyx_hud_current_acceptance_v42.py")
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "2530008b13134d279dced31d16aa65f7a57e1b9c72f80d892dcfb4d4f42f6289"
)
PREDECESSOR_MANIFEST: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V42-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "1f5568cb5331cfcd5fc56bfbf02bc3b631a7351bc244ec85f7892bee80d419f5"
)


class CurrentHudAcceptanceV43Error(RuntimeError):
    """The V43 Setup delta or immutable V42 authority drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CurrentHudAcceptanceV43Error("noncanonical V43 input path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentHudAcceptanceV43Error("V43 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentHudAcceptanceV43Error("V43 input is linked")
    return resolved


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_ACCEPTANCE, PREDECESSOR_ACCEPTANCE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise CurrentHudAcceptanceV43Error("immutable V42 predecessor drifted")
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise CurrentHudAcceptanceV43Error("V43 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentHudAcceptanceV43Error("V43 manifest invalid") from error
    semantics = {
        "primary_layout_changed": False,
        "setup_surface_changed": True,
        "voice_selection_surface_changed": True,
        "palette_changed": False,
        "humanoid_anatomy_changed": False,
        "humanoid_runtime_changed": False,
        "voice_pipeline_changed": False,
        "voice_preference_contract_changed": False,
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
        manifest.get("schema") != "onyx.hud.current.v43.acceptance.v1"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != "qml/OnyxLiveShellV15.qml"
        or manifest.get("semantics") != semantics
        or type(entries) is not list
        or len(entries) != 10
    ):
        raise CurrentHudAcceptanceV43Error("V43 manifest contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise CurrentHudAcceptanceV43Error("V43 input binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise CurrentHudAcceptanceV43Error(
                f"V43 source input drifted: {entry['path']}"
            )
    return {
        "candidate": manifest["candidate"],
        "runtime_inputs": len(entries),
        "predecessor": "onyx-hud-v16-compositor-continuity-humanoid-001",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": True,
        "voice_selection_surface_changed": True,
        "published": False,
    }


__all__ = [
    "CurrentHudAcceptanceV43Error",
    "MANIFEST_RELATIVE",
    "verify_current_hud_acceptance",
]
