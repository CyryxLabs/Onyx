"""Authenticate the additive Cyryx humanoid-presence HUD over immutable V36."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V37-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "9b9a945b564c0a9bde8da7ba9cf1b924e228150abe47bc5a78af704c50ab50ed"
)
PREDECESSOR_ACCEPTANCE: Final = Path("core/onyx_hud_current_acceptance_v36.py")
PREDECESSOR_ACCEPTANCE_SHA256: Final = (
    "de3de40c70851c1fe830b0c4520a0dcbd6d44900a9b5151814240ebce9baa948"
)
PREDECESSOR_MANIFEST: Final = Path(
    "docs/onyx/acceptance/VE-HUD-CURRENT-V36-E6-001.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "b3fdd3d35b44b673f9a82921f1fd884065d9c6b1beeaa97755c989d9faadd257"
)


class CurrentHudAcceptanceV37Error(RuntimeError):
    """The V37 visual delta or immutable V36 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise CurrentHudAcceptanceV37Error("noncanonical V37 input path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentHudAcceptanceV37Error("V37 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentHudAcceptanceV37Error("V37 input is linked")
    return resolved


def verify_current_hud_acceptance(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_ACCEPTANCE, PREDECESSOR_ACCEPTANCE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise CurrentHudAcceptanceV37Error("immutable V36 predecessor drifted")
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise CurrentHudAcceptanceV37Error("V37 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentHudAcceptanceV37Error("V37 manifest invalid") from error
    semantics = {
        "palette_changed": False,
        "abstract_humanoid": True,
        "staged_materialisation": True,
        "staged_dissolution": True,
        "state_driven": True,
        "audio_responsive": True,
        "reduced_motion_static": True,
        "one_qml_root": True,
        "network_activity": False,
        "published": False,
    }
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.hud.current.v37.acceptance.v1"
        or manifest.get("decision") != "accepted-source"
        or manifest.get("current_root") != "qml/OnyxLiveShellV13.qml"
        or manifest.get("semantics") != semantics
        or type(entries) is not list
        or len(entries) != 9
    ):
        raise CurrentHudAcceptanceV37Error("V37 manifest contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise CurrentHudAcceptanceV37Error("V37 input binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise CurrentHudAcceptanceV37Error(
                f"V37 source input drifted: {entry['path']}"
            )
    return {
        "candidate": manifest["candidate"],
        "runtime_inputs": len(entries),
        "predecessor": "onyx-hud-v36-liquid-metal-001",
        "palette_changed": False,
        "published": False,
    }


__all__ = [
    "CurrentHudAcceptanceV37Error",
    "MANIFEST_RELATIVE",
    "verify_current_hud_acceptance",
]
