"""Additive exact packaged-runtime contract for the governed capability host."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

MANIFEST_RELATIVE = Path("core/onyx_packaged_runtime_hud_contract_v2.manifest.json")
REQUIRED_HOST_PORTS = frozenset({
    "core/capability_composition_v1.py", "core/capability_ports/__init__.py",
    "core/capability_ports/argos_v1.py", "core/capability_ports/google_workspace_v1.py",
    "core/capability_ports/graph_v1.py", "core/capability_ports/plugin_v1.py",
    "core/capability_ports/social_v1.py", "core/capability_ports/unified_router_v1.py",
    "core/governed_capability_host_v1.py", "scripts/onyx_capabilities_cli.py",
})


class PackagedRuntimeHudContractV2Error(RuntimeError):
    """The V2 packaged runtime closure is unavailable or drifted."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise PackagedRuntimeHudContractV2Error("noncanonical packaged path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise PackagedRuntimeHudContractV2Error(f"packaged runtime input unavailable: {relative}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PackagedRuntimeHudContractV2Error(f"packaged runtime input escapes stage: {relative}") from exc
    if resolved != candidate.absolute():
        raise PackagedRuntimeHudContractV2Error(f"packaged runtime input is linked: {relative}")
    return resolved


def _root(records: list[dict[str, str]]) -> str:
    material = "".join(f"{item['path']}\0{item['sha256']}\n" for item in sorted(records, key=lambda item: item["path"])).encode()
    return hashlib.sha256(material).hexdigest()


def verify_packaged_runtime_hud_contract_v2(stage: Path) -> dict[str, object]:
    root = Path(stage).resolve(strict=True)
    manifest = json.loads(_file(root, MANIFEST_RELATIVE.as_posix()).read_text(encoding="utf-8"))
    if set(manifest) != {"schema", "predecessor", "required_files", "required_host_ports", "artifact_root_sha256", "semantics"} or manifest.get("schema") != "onyx.packaged-runtime-hud.v2":
        raise PackagedRuntimeHudContractV2Error("packaged V2 manifest contract drift")
    records = manifest["required_files"]
    if type(records) is not list or any(type(item) is not dict or set(item) != {"path", "sha256"} for item in records):
        raise PackagedRuntimeHudContractV2Error("packaged V2 membership drift")
    paths = {item["path"] for item in records}
    if any("tests" in PurePosixPath(path).parts for path in paths) or paths & {"main.py", "ui.py", "packaging/onyx.spec"}:
        raise PackagedRuntimeHudContractV2Error("development or checkout fallback entered V2")
    if manifest.get("required_host_ports") != sorted(REQUIRED_HOST_PORTS) or not REQUIRED_HOST_PORTS <= paths:
        raise PackagedRuntimeHudContractV2Error("governed host ports are incomplete")
    for item in records:
        if _sha(_file(root, item["path"])) != item["sha256"]:
            raise PackagedRuntimeHudContractV2Error(f"packaged V2 input drift: {item['path']}")
    if _root(records) != manifest.get("artifact_root_sha256"):
        raise PackagedRuntimeHudContractV2Error("packaged V2 artifact root drift")
    bootstrap = _file(root, "scripts/bootstrap_onyx.pyw").read_text(encoding="utf-8")
    cli = _file(root, "scripts/onyx_capabilities_cli.py").read_text(encoding="utf-8")
    for anchor in ('getattr(sys, "_MEIPASS"', 'sys.argv[1:] == ["--capabilities-smoke-v1"]', "provider, or launch a child process", "provider_dispatch"):
        if anchor not in bootstrap + cli:
            raise PackagedRuntimeHudContractV2Error("capability smoke boundary drift")
    if '"provider_dispatch": False' not in cli:
        raise PackagedRuntimeHudContractV2Error("provider-free capability smoke drift")
    return {"schema": manifest["schema"], "required_files": len(records), "artifact_root_sha256": manifest["artifact_root_sha256"], "tests_in_runtime": False, "checkout_fallback": False, "provider_dispatch": False}


__all__ = ["MANIFEST_RELATIVE", "PackagedRuntimeHudContractV2Error", "REQUIRED_HOST_PORTS", "verify_packaged_runtime_hud_contract_v2"]
