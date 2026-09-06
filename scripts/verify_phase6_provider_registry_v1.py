"""Verify the isolated Provider Registry + Health route-plan V1 candidate."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "core/phase6_provider_registry_v1.py"
MANIFEST = ROOT / "docs/onyx/checkpoints/phase6-provider-registry-v1/manifest.json"
FROZEN = {
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "core/phase6_agentic_core_v1.py": "ab7a6cfec738c31b7beb66ac7a66584f892231ce8a3a2c9e81f30945123cc965",
    "core/phase6_agentic_core_v6.py": "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a",
    "core/phase6_live_integration_v2.py": "e3194a0d8e206d33218bc8291cbd518788e8dfb3931adfd2f067908655d409b5",
    "core/phase6_gemini_live_compat_v1.py": "3fb18363c237c573c717472bb9b2d6b3891dccc6236be7f698ee0833b9a55df5",
    "core/phase6_live_wiring_v1.py": "a658f430c10bb992724ad7bbd2ddae94b3c83f8893608fe724b241302b55d55f",
    "core/onyx_live_activation_v9.py": "deb26314ef3871cb12fc8e3cee936f88e385122fad242c830580421ccb22a9d2",
}
FORBIDDEN_IMPORTS = {
    "aiohttp",
    "google.genai",
    "httpx",
    "openai",
    "requests",
    "socket",
}
FORBIDDEN_CALLS = {"connect", "generate_content", "invoke", "send"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_root(items: list[dict[str, object]]) -> str:
    payload = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(items, key=lambda item: str(item["path"]))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_ast(source: str) -> None:
    tree = ast.parse(source)
    imported_core_types = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "core.phase6_agentic_core_v1"
        for alias in node.names
    }
    assert {
        "ModelDescriptorV1",
        "RouteRequestV1",
        "ModelRouterV1",
    } <= imported_core_types
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not FORBIDDEN_IMPORTS & imported
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not FORBIDDEN_CALLS & called_attributes
    route_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "plan_route"
    ]
    assert len(route_nodes) == 1
    route_source = ast.get_source_segment(source, route_nodes[0])
    assert route_source is not None
    privacy = route_source.index('"privacy_hard_filter"')
    workspace = route_source.index('"workspace_hard_filter"')
    modality = route_source.index('"modality_hard_filter"')
    local = route_source.index('"local_hard_filter"')
    structured = route_source.index('"structured_hard_filter"')
    budget = route_source.index('"budget_hard_filter"')
    health = route_source.index('excluded["health_unavailable"]')
    router = route_source.index("_MODEL_ROUTER_TYPE(")
    assert (
        privacy < workspace < modality < local < structured < budget < health < router
    )
    assert "_authentication_key_digest" in source
    assert "set(self._health) != set(self._health_snapshots)" in source


def verify() -> dict[str, object]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == "OnyxPhase6ProviderRegistry.v1"
    assert data["candidate"] == "phase6-provider-registry-candidate-001"
    assert data["status"] == "candidate_default_off_not_live"
    assert data["activation"]["exact"] == "ONYX_PHASE6_PROVIDER_REGISTRY_V1=true"
    assert data["activation"]["live_wiring"] is False
    assert data["verification"]["network_calls"] == 0
    assert data["verification"]["e6"] == "not_performed"
    assert data["contracts"]["exact_agentic_core_types"] == [
        "ModelDescriptorV1",
        "RouteRequestV1",
        "ModelRouterV1",
    ]
    assert data["contracts"]["sensitive_remote_fallback"] is False
    assert data["contracts"]["provider_invocation"] is False
    for path, expected in FROZEN.items():
        assert digest(ROOT / path) == expected
        assert data["frozen_anchors"][path] == expected
    for item in data["artifacts"]:
        path = ROOT / item["path"]
        assert path.stat().st_size == item["bytes"]
        assert digest(path) == item["sha256"]
    assert data["artifact_root_algorithm"] == "sha256-sorted-path-nul-digest-lf-v1"
    assert artifact_root(data["artifacts"]) == data["artifact_root_sha256"]
    _verify_ast(MODULE.read_text(encoding="utf-8"))
    result = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            ".pytest-provider-registry-v1-verify",
            "tests/test_phase6_provider_registry_v1.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0 and "22 passed" in result.stdout
    return {
        "artifacts": len(data["artifacts"]),
        "e6": False,
        "live": False,
        "network_calls": 0,
    }


if __name__ == "__main__":
    print("P6_PROVIDER_REGISTRY_V1_OK", json.dumps(verify(), sort_keys=True))
