"""Packaged authority for the Cyryx humanoid-presence HUD successor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v6.manifest.json"
)
MANIFEST_SHA256: Final = (
    "9fe601cc6449be0d08d3811bcafd4a5d8313eb14d51a1a0d6b82724b75bc372e"
)
PREDECESSOR_MODULE: Final = Path("core/onyx_packaged_runtime_hud_contract_v5.py")
PREDECESSOR_MODULE_SHA256: Final = (
    "03a68b3342036193e946269360ea102968afbc1e5d4926e38eaebe8800dff652"
)
PREDECESSOR_MANIFEST: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v5.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "ef037a65fcc154432a428f0766a2253200fb202f889e0041fd36a9d616fdf8ef"
)


class PackagedRuntimeHudContractV6Error(RuntimeError):
    """The packaged V6 contract or immutable V5 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if pure.is_absolute() or pure.as_posix() != relative or ".." in pure.parts:
        raise PackagedRuntimeHudContractV6Error("noncanonical packaged V6 path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PackagedRuntimeHudContractV6Error("packaged V6 input unavailable") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise PackagedRuntimeHudContractV6Error("packaged V6 input is linked")
    return resolved


def verify_packaged_runtime_hud_contract(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_MODULE, PREDECESSOR_MODULE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise PackagedRuntimeHudContractV6Error(
                "immutable packaged V5 predecessor drifted"
            )
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise PackagedRuntimeHudContractV6Error("packaged V6 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackagedRuntimeHudContractV6Error("packaged V6 manifest invalid") from error
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.packaged-runtime-hud-contract.v6"
        or type(entries) is not list
        or len(entries) != 11
        or manifest.get("semantics")
        != {
            "current_orb": "humanoid-presence-v10",
            "staged_living_motion": True,
            "provider_independent": True,
            "formal_release_ready": False,
        }
    ):
        raise PackagedRuntimeHudContractV6Error("packaged V6 contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise PackagedRuntimeHudContractV6Error("packaged V6 binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise PackagedRuntimeHudContractV6Error(
                f"packaged V6 input drifted: {entry['path']}"
            )
    return {
        "schema": manifest["schema"],
        "runtime_inputs": len(entries),
        "current_orb": manifest["semantics"]["current_orb"],
        "formal_release_ready": False,
    }


__all__ = [
    "MANIFEST_RELATIVE",
    "PackagedRuntimeHudContractV6Error",
    "verify_packaged_runtime_hud_contract",
]
