"""Authenticate deferred Setup opening over immutable HUD V43."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V44-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "50c087a8a0c222d6417cdec6ce2c941b9327e303387e9fb0a68f3e73c1a53f10"
)
PREDECESSOR_ACCEPTANCE: Final = Path("core/onyx_hud_current_acceptance_v43.py")
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "eb2cfa477df6c0407bb5246edfd3948af9c55610e7674bce0deeeb32b7d69c2e"
)
PREDECESSOR_MANIFEST: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V43-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "5046fd657453179e530dbb8a5eb9b51780b3526b091503d363feaab5cd3dcdfb"
)


class CurrentHudAcceptanceV44Error(RuntimeError):
    """The V44 Setup-stability delta or immutable V43 authority drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CurrentHudAcceptanceV44Error("noncanonical V44 input path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentHudAcceptanceV44Error("V44 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentHudAcceptanceV44Error("V44 input is linked")
    return resolved


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_ACCEPTANCE, PREDECESSOR_ACCEPTANCE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise CurrentHudAcceptanceV44Error("immutable V43 predecessor drifted")
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise CurrentHudAcceptanceV44Error("V44 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentHudAcceptanceV44Error("V44 manifest invalid") from error
    semantics = {
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "palette_changed": False,
        "humanoid_anatomy_changed": False,
        "humanoid_runtime_changed": False,
        "voice_pipeline_changed": False,
        "voice_preference_contract_changed": False,
        "setup_callback_deferred": True,
        "setup_request_coalescing": True,
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
        manifest.get("schema") != "onyx.hud.current.v44.acceptance.v1"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != "qml/OnyxLiveShellV15.qml"
        or manifest.get("semantics") != semantics
        or type(entries) is not list
        or len(entries) != 10
    ):
        raise CurrentHudAcceptanceV44Error("V44 manifest contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise CurrentHudAcceptanceV44Error("V44 input binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise CurrentHudAcceptanceV44Error(
                f"V44 source input drifted: {entry['path']}"
            )
    return {
        "candidate": manifest["candidate"],
        "runtime_inputs": len(entries),
        "predecessor": "onyx-hud-v17-setup-voice-selection-001",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "setup_callback_deferred": True,
        "setup_request_coalescing": True,
        "published": False,
    }


__all__ = [
    "CurrentHudAcceptanceV44Error",
    "MANIFEST_RELATIVE",
    "MANIFEST_SHA256",
    "verify_current_hud_acceptance",
]
