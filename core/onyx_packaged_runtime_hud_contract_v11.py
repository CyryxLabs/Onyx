"""Packaged authority for the compositor-continuity humanoid over immutable V10."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v11.manifest.json"
)
MANIFEST_SHA256: Final = (
    "3823acc95510c81d7ddb6b67c65056fee65e895c346308785b8934ade85347cb"
)
PREDECESSOR_MODULE: Final = Path("core/onyx_packaged_runtime_hud_contract_v10.py")
PREDECESSOR_MODULE_SHA256: Final = (
    "52828ba3d3a03cc2052af12fc64e727b46f232af42627546f569503eea9d3b5b"
)
PREDECESSOR_MANIFEST: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v10.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "9e05366f95ebffb28eba0e433457950e72dc0464b75edaff9fe1dcc53f061c54"
)


class PackagedRuntimeHudContractV11Error(RuntimeError):
    """The packaged V11 contract or immutable V10 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise PackagedRuntimeHudContractV11Error("noncanonical packaged V11 path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PackagedRuntimeHudContractV11Error(
            "packaged V11 input unavailable"
        ) from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise PackagedRuntimeHudContractV11Error("packaged V11 input is linked")
    return resolved


def verify_packaged_runtime_hud_contract(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_MODULE, PREDECESSOR_MODULE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise PackagedRuntimeHudContractV11Error(
                "immutable packaged V10 predecessor drifted"
            )
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise PackagedRuntimeHudContractV11Error("packaged V11 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackagedRuntimeHudContractV11Error(
            "packaged V11 manifest invalid"
        ) from error
    semantics = {
        "current_orb": "humanoid-presence-v12-continuity",
        "live_renderer": "three.js-webgl",
        "last_real_frame_continuity": True,
        "double_buffered_qml_backing": True,
        "validated_presentation_buffer": True,
        "transparent_compositor_surface": True,
        "layout_changed": False,
        "palette_changed": False,
        "voice_pipeline_changed": False,
        "capability_surface_changed": False,
        "provider_independent": True,
        "formal_release_ready": False,
    }
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.packaged-runtime-hud-contract.v11"
        or type(entries) is not list
        or len(entries) != 9
        or manifest.get("semantics") != semantics
    ):
        raise PackagedRuntimeHudContractV11Error("packaged V11 contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise PackagedRuntimeHudContractV11Error("packaged V11 binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise PackagedRuntimeHudContractV11Error(
                f"packaged V11 input drifted: {entry['path']}"
            )
    return {
        "schema": manifest["schema"],
        "runtime_inputs": len(entries),
        "current_orb": semantics["current_orb"],
        "live_renderer": semantics["live_renderer"],
        "last_real_frame_continuity": True,
        "double_buffered_qml_backing": True,
        "formal_release_ready": False,
    }


__all__ = [
    "MANIFEST_RELATIVE",
    "PackagedRuntimeHudContractV11Error",
    "verify_packaged_runtime_hud_contract",
]
