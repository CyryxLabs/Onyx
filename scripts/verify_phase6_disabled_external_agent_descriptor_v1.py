"""Verify the isolated Phase 6 Disabled External-Agent Descriptor V1."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve(strict=True).parents[1]
MODULE = "core/phase6_disabled_external_agent_descriptor_v1.py"
TESTS = "tests/test_phase6_disabled_external_agent_descriptor_v1.py"
ADR = "docs/onyx/adrs/ADR-0026-phase6-disabled-external-agent-descriptor-v1.md"
CHECKPOINT = (
    "docs/onyx/checkpoints/phase6-disabled-external-agent-descriptor-v1/"
    "PHASE6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1_CHECKPOINT.md"
)
MANIFEST = (
    "docs/onyx/checkpoints/phase6-disabled-external-agent-descriptor-v1/"
    "manifest.json"
)
VERIFIER = "scripts/verify_phase6_disabled_external_agent_descriptor_v1.py"
EXPECTED_ARTIFACTS = {MODULE, TESTS, ADR, CHECKPOINT, VERIFIER}
MARKER = "P6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1_OK"
COMPONENT_ROOTS = {
    (
        "capability_nexus_v32",
        (
            "docs/onyx/checkpoints/phase5-capability-nexus-v32/"
            "phase5-capability-nexus-v32.bundle.json"
        ),
    ): "84ffc850a14782ae3f4182973acc50a2765df7f6143977a81daf5423c6706c6f",
    (
        "capability_nexus_v32",
        "docs/onyx/acceptance/VE-P53-CAPABILITY-NEXUS-V32-E6-001.md",
    ): "b75ccb2b4bc58a4c4d72445d46eb66e550636cbb0deb02ecef304c8327f9d1dc",
    (
        "provider_registry_v1",
        "docs/onyx/checkpoints/phase6-provider-registry-v1/manifest.json",
    ): "7a3191607037f6210ae145b5477bbaeff5bfdaa7c756257d4775c1f30c0a10c6",
    (
        "provider_registry_v1",
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.md",
    ): "ca7f0760723c4f6ad5d2a8716248c75c695e58cdb3e9b6917a3d027443aefabd",
    (
        "provider_registry_v1",
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.manifest.json",
    ): "4a2c69076a1e6b07f606d30733b357f7c50c08193ff90a250d351637f0c0d070",
}
FORBIDDEN_IMPORTS = {
    "aiohttp",
    "asyncio",
    "http",
    "httpx",
    "openai",
    "requests",
    "socket",
    "subprocess",
    "urllib",
    "webbrowser",
}
FORBIDDEN_CALLS = {
    "connect",
    "create_connection",
    "Popen",
    "post",
    "request",
    "run",
    "send",
    "start",
    "urlopen",
}


def digest(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def artifact_root(items: list[dict[str, object]]) -> str:
    payload = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(items, key=lambda item: str(item["path"]))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _imports(tree: ast.AST) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module)
    return values


def _verify_candidate_ast(source: str) -> None:
    tree = ast.parse(source)
    assert not (_imports(tree) & FORBIDDEN_IMPORTS)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not (calls & FORBIDDEN_CALLS)
    required = (
        'FEATURE_FLAG: Final = "ONYX_PHASE6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1"',
        'CANDIDATE: Final = "phase6-disabled-external-agent-descriptor-candidate-001"',
        'ACCESS_REASON: Final = "no_accepted_installed_authenticated_adapter"',
        "class DisabledExternalAgentDescriptorV1",
        "class DisabledExternalAgentDescriptorCatalogV1",
        "class ExternalAgentDescriptorIdentityV1",
        "class DisabledExternalAgentReceiptV1",
        "CapabilityStatusV32.BLOCKED_BY_ACCESS",
        "AdapterStatusV1.BLOCKED_BY_ACCESS",
        "NO_SESSION_CANCEL_IS_FINAL",
        "AUTHENTICATED_BLOCKED_PROJECTION",
        "credential_alias=None",
        "required_scopes=()",
        "metadata=()",
        "provider_calls: int = 0",
        "process_calls: int = 0",
        "network_calls: int = 0",
        "live_calls: int = 0",
    )
    assert all(value in source for value in required)
    assert "create_provider_registry_v1" not in source
    assert "ModelRouterV1" not in source


def _verify_descriptor_fields(source: str) -> None:
    tree = ast.parse(source)
    descriptor = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "DisabledExternalAgentDescriptorV1"
    )
    forbidden = ("command", "executable", "path", "environment", "env", "credential")
    public_names = {
        node.name
        for node in descriptor.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(decorator, ast.Name) and decorator.id == "property"
            for decorator in node.decorator_list
        )
    }
    assert all(
        not any(name == token or name.startswith(f"{token}_") for token in forbidden)
        for name in public_names
    )


def _live_files() -> list[Path]:
    values = [ROOT / "main.py", ROOT / "ui.py"]
    for root_name in ("dashboard", "runtime", "packaging", "qml"):
        root = ROOT / root_name
        if root.is_dir():
            values.extend(path for path in root.rglob("*") if path.is_file())
    scripts = ROOT / "scripts"
    values.extend(path for path in scripts.glob("launch_*") if path.is_file())
    return sorted(set(values))


def verify() -> dict[str, object]:
    data = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    assert data["schema"] == "OnyxPhase6DisabledExternalAgentDescriptor.v1"
    assert (
        data["candidate"]
        == "phase6-disabled-external-agent-descriptor-candidate-001"
    )
    assert data["status"] == "candidate_default_off_not_live"
    assert data["activation"] == {
        "flag": "ONYX_PHASE6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1",
        "enabled_value": "true",
        "exact": "ONYX_PHASE6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1=true",
        "default": "off",
        "factory_only": True,
        "live_wiring": False,
    }
    assert data["artifact_root_algorithm"] == "sha256-sorted-path-nul-digest-lf-v1"
    entries = data["artifacts"]
    assert {item["path"] for item in entries} == EXPECTED_ARTIFACTS
    assert len(entries) == 5
    for item in entries:
        path = ROOT / str(item["path"])
        assert path.stat().st_size == item["bytes"]
        assert digest(str(item["path"])) == item["sha256"]
    assert artifact_root(entries) == data["artifact_root_sha256"]

    recorded_roots = {
        (item["component"], item["path"]): item["sha256"]
        for item in data["component_acceptance_roots"]
    }
    assert recorded_roots == COMPONENT_ROOTS
    for (_component, relative), expected in COMPONENT_ROOTS.items():
        assert digest(relative) == expected

    contracts = data["contracts"]
    assert contracts["health"] == "blocked_by_access"
    assert contracts["access_reason"] == (
        "no_accepted_installed_authenticated_adapter"
    )
    assert contracts["required_scopes"] == []
    assert contracts["granted_scopes"] == []
    assert contracts["authentication"] == "absent"
    assert contracts["credential_alias"] is None
    assert contracts["public_executable_fields"] == []
    assert contracts["provider_calls"] == 0
    assert contracts["process_calls"] == 0
    assert contracts["network_calls"] == 0
    assert contracts["live_calls"] == 0
    assert contracts["exact_replay"] is True
    assert contracts["authenticated_receipts"] is True
    assert data["verification"]["focused"] == "40 passed"
    assert data["verification"]["e6"] == "not_performed"
    assert data["verification"]["live_activation"] is False

    source = (ROOT / MODULE).read_text(encoding="utf-8")
    _verify_candidate_ast(source)
    _verify_descriptor_fields(source)
    checked = 0
    for path in _live_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        checked += 1
        assert "phase6_disabled_external_agent_descriptor_v1" not in text
        assert "ONYX_PHASE6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1" not in text

    result = subprocess.run(
        [
            str(ROOT / ".venv" / "Scripts" / "python.exe"),
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(ROOT / "phase6-disabled-external-agent-descriptor-verifier"),
            str(ROOT / TESTS),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "40 passed" in result.stdout
    return {
        "candidate": data["candidate"],
        "artifact_root_sha256": data["artifact_root_sha256"],
        "component_acceptance_roots": len(COMPONENT_ROOTS),
        "live_files_checked": checked,
        "focused": "40 passed",
        "provider_calls": 0,
        "process_calls": 0,
        "network_calls": 0,
        "live_calls": 0,
        "e6": "not_performed",
        "marker": MARKER,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
