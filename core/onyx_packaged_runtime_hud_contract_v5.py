"""Packaged authority for the living liquid-metal HUD successor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Final


MANIFEST_RELATIVE: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v5.manifest.json"
)
MANIFEST_SHA256: Final = (
    "ef037a65fcc154432a428f0766a2253200fb202f889e0041fd36a9d616fdf8ef"
)
PREDECESSOR_MODULE: Final = Path("core/onyx_packaged_runtime_hud_contract_v4.py")
PREDECESSOR_MODULE_SHA256: Final = (
    "6efae9777ce5e5b34f4ae59620a96ee564847ce950cc9e26bd823a5349c2ff0a"
)
PREDECESSOR_MANIFEST: Final = Path(
    "core/onyx_packaged_runtime_hud_contract_v4.manifest.json"
)
PREDECESSOR_MANIFEST_SHA256: Final = (
    "4e9eabce9ba24a21496b8514bf1a8a3c0ddf26ce82d90eb0bbc1b597a9764e8e"
)


class PackagedRuntimeHudContractV5Error(RuntimeError):
    """The packaged V5 contract or immutable V4 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: object) -> Path:
    pure = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if pure.is_absolute() or pure.as_posix() != relative or ".." in pure.parts:
        raise PackagedRuntimeHudContractV5Error("noncanonical packaged V5 path")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise PackagedRuntimeHudContractV5Error(
            "packaged V5 input unavailable"
        ) from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise PackagedRuntimeHudContractV5Error("packaged V5 input is linked")
    return resolved


def verify_packaged_runtime_hud_contract(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    for relative, digest in (
        (PREDECESSOR_MODULE, PREDECESSOR_MODULE_SHA256),
        (PREDECESSOR_MANIFEST, PREDECESSOR_MANIFEST_SHA256),
    ):
        if _sha256(_file(root, relative.as_posix())) != digest:
            raise PackagedRuntimeHudContractV5Error(
                "immutable packaged V4 predecessor drifted"
            )
    manifest_path = _file(root, MANIFEST_RELATIVE.as_posix())
    if _sha256(manifest_path) != MANIFEST_SHA256:
        raise PackagedRuntimeHudContractV5Error("packaged V5 manifest drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackagedRuntimeHudContractV5Error(
            "packaged V5 manifest invalid"
        ) from error
    entries = manifest.get("runtime_inputs") if type(manifest) is dict else None
    if (
        manifest.get("schema") != "onyx.packaged-runtime-hud-contract.v5"
        or type(entries) is not list
        or len(entries) != 9
        or manifest.get("semantics", {}).get("formal_release_ready") is not False
    ):
        raise PackagedRuntimeHudContractV5Error("packaged V5 contract drifted")
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise PackagedRuntimeHudContractV5Error("packaged V5 binding drifted")
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise PackagedRuntimeHudContractV5Error(
                f"packaged V5 input drifted: {entry['path']}"
            )
    return {
        "schema": manifest["schema"],
        "runtime_inputs": len(entries),
        "current_orb": manifest["semantics"]["current_orb"],
        "formal_release_ready": False,
    }


__all__ = [
    "MANIFEST_RELATIVE",
    "PackagedRuntimeHudContractV5Error",
    "verify_packaged_runtime_hud_contract",
]
