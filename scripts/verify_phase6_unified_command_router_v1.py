"""Verify the isolated Phase 6 Unified Command Router V1 candidate."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.phase6_unified_command_router_v1 import (  # noqa: E402
    COMPONENT_ACCEPTANCE_ROOTS,
)


MODULE = ROOT / "core/phase6_unified_command_router_v1.py"
MANIFEST = ROOT / "docs/onyx/checkpoints/phase6-unified-command-router-v1/manifest.json"
FOCUSED = ("tests/test_phase6_unified_command_router_v1.py",)
CUMULATIVE = (
    "tests/test_phase6_agentic_core_v6.py",
    "tests/test_phase6_provider_registry_v1.py",
    "tests/test_phase6_research_cells_v1.py",
    "tests/test_phase6_local_mcp_v1.py",
    "tests/test_phase6_local_mcp_v1_c002_reacceptance.py",
    "tests/test_phase6_live_integration_v2.py",
    *FOCUSED,
)
FORBIDDEN_IMPORTS = {
    "aiohttp",
    "google.genai",
    "httpx",
    "openai",
    "requests",
    "socket",
    "subprocess",
}
FORBIDDEN_OPERATIONAL_CALLS = {
    "call_catalog",
    "execute_local_catalog_plan",
    "generate_text",
    "invoke",
    "Popen",
    "submit",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_root(items: list[dict[str, object]]) -> str:
    payload = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(items, key=lambda item: str(item["path"]))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _function_source(tree: ast.Module, source: str, name: str) -> str:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(matches) == 1
    result = ast.get_source_segment(source, matches[0])
    assert result is not None
    return result


def _verify_ast(source: str) -> None:
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not FORBIDDEN_IMPORTS & imports
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not FORBIDDEN_OPERATIONAL_CALLS & calls

    plan_source = _function_source(tree, source, "plan")
    hard_gate = plan_source.index("self._hard_gate")
    attest = plan_source.index("self._attest")
    route = plan_source.index("self._route_")
    assert hard_gate < attest < route

    hard_source = _function_source(tree, source, "_hard_gate")
    cancelled = hard_source.index("command.cancelled")
    identity = hard_source.index("command.identity")
    privacy = hard_source.index("_DATA_RANK[command.data_class]")
    deadline = hard_source.index("command.deadline_at_ms")
    evidence = hard_source.index("command.evidence_bundle")
    assert cancelled < identity < privacy < deadline < evidence

    user_command = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "UserCommandV1"
    )
    fields = {
        node.target.id
        for node in user_command.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert {
        "identity",
        "workspace_id",
        "data_class",
        "modality",
        "budget",
        "deadline_at_ms",
        "cancelled",
        "intent",
        "input_digest",
    } <= fields
    assert not {"prompt", "content", "instructions", "provider", "tool"} & fields
    assert "COMPONENT_ACCEPTANCE_ROOTS" in source
    assert "ProviderRoutePlanV1" in source
    assert "EvidenceBundleV1" in source
    assert "LocalCatalogMCPRequestV1" in source
    assert "Phase6LiveIntegrationV2" in source


def _run_pytest(paths: tuple[str, ...], basetemp: str, expected: str) -> None:
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
            basetemp,
            *paths,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout


def verify() -> dict[str, object]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == "OnyxPhase6UnifiedCommandRouter.v1"
    assert data["candidate"] == "phase6-unified-command-router-candidate-002"
    assert data["status"] == "candidate-ready-external-gate"
    assert data["activation"]["exact"] == "ONYX_PHASE6_UNIFIED_COMMAND_ROUTER_V1=true"
    assert data["activation"]["live_wiring"] is False
    assert data["verification"]["e6"] == "not_performed"
    assert data["verification"]["network_calls"] == 0
    assert data["verification"]["process_calls"] == 0
    assert data["verification"]["provider_calls"] == 0
    assert data["verification"]["live_calls"] == 0
    assert (
        data["verification"]["dependency_reacceptance"]
        == "local_mcp_v1_c002_activation_v10_c003_accepted"
    )
    assert data["contracts"]["explicit_intents"] == [
        "local_catalog",
        "research_verify",
        "text_plan",
    ]
    assert data["contracts"]["provider_invocation"] is False
    assert data["contracts"]["mcp_process_open"] is False
    assert data["contracts"]["live_facade_invocation"] is False
    assert data["contracts"]["prompt_or_content_authority"] is False

    expected_roots = [
        {"component": component, "path": path, "sha256": sha256}
        for component, path, sha256 in COMPONENT_ACCEPTANCE_ROOTS
    ]
    assert data["component_acceptance_roots"] == expected_roots
    for item in expected_roots:
        assert digest(ROOT / item["path"]) == item["sha256"]

    for path, expected in data["frozen_live_anchors"].items():
        assert digest(ROOT / path) == expected
    for item in data["artifacts"]:
        path = ROOT / item["path"]
        assert path.stat().st_size == item["bytes"]
        assert digest(path) == item["sha256"]
    assert data["artifact_root_algorithm"] == "sha256-sorted-path-nul-digest-lf-v1"
    assert artifact_root(data["artifacts"]) == data["artifact_root_sha256"]
    _verify_ast(MODULE.read_text(encoding="utf-8"))
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        assert "phase6_unified_command_router_v1" not in (ROOT / relative).read_text(
            encoding="utf-8"
        )

    _run_pytest(
        FOCUSED,
        ".pytest-unified-command-router-v1-verify-focused",
        "27 passed",
    )
    _run_pytest(
        CUMULATIVE,
        ".pytest-unified-command-router-v1-verify-cumulative",
        "154 passed",
    )
    return {
        "artifacts": len(data["artifacts"]),
        "component_roots": len(expected_roots),
        "focused": 27,
        "cumulative": 154,
        "e6": False,
        "live": False,
        "network_calls": 0,
        "process_calls": 0,
        "provider_calls": 0,
        "live_calls": 0,
        "dependency_reacceptance": True,
    }


if __name__ == "__main__":
    print(
        "P6_UNIFIED_COMMAND_ROUTER_V1_OK",
        json.dumps(verify(), sort_keys=True),
    )
