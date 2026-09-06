"""Verify the isolated Phase 6 Local/Text Compatibility V1 candidate."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve(strict=True).parents[1]
MODULE = "core/phase6_local_text_compat_v1.py"
TESTS = "tests/test_phase6_local_text_compat_v1.py"
ADR = "docs/onyx/adrs/ADR-0025-phase6-local-text-compat-v1.md"
CHECKPOINT = (
    "docs/onyx/checkpoints/phase6-local-text-compat-v1/"
    "PHASE6_LOCAL_TEXT_COMPAT_V1_CHECKPOINT.md"
)
MANIFEST = "docs/onyx/checkpoints/phase6-local-text-compat-v1/manifest.json"
VERIFIER = "scripts/verify_phase6_local_text_compat_v1.py"
EXPECTED_ARTIFACTS = {MODULE, TESTS, ADR, CHECKPOINT, VERIFIER}
MARKER = "P6_LOCAL_TEXT_COMPAT_V1_OK"
FROZEN = {
    "core/llm_client.py": (
        "e5c0f805e0d10a07e38054316fb9c6423409190cfa0f48bc39694e65c6a4e417"
    )
}
FORBIDDEN_IMPORTS = {
    "aiohttp",
    "http.client",
    "httpx",
    "openai",
    "requests",
    "socket",
    "urllib.request",
}
FORBIDDEN_CALLS = {
    "connect",
    "create_connection",
    "post",
    "request",
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
    imports = _imports(tree)
    assert not (FORBIDDEN_IMPORTS & imports), (
        "network/provider import entered candidate"
    )
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not (FORBIDDEN_CALLS & calls), "network-style call entered candidate"
    imports_from_core = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "core"
        for alias in node.names
    }
    assert imports_from_core == {"llm_client"}
    required = (
        'FEATURE_FLAG: Final = "ONYX_PHASE6_LOCAL_TEXT_COMPAT_V1"',
        'CANDIDATE: Final = "phase6-local-text-compat-candidate-001"',
        "class LocalTextCompatibilityV1",
        "class LocalTextInstallationV1",
        "class LocalTextTransportV1",
        "class LocalTextPrivacyDenied",
        "class LocalTextUnavailable",
        "class LocalTextTimeout",
        "class LocalTextCancelled",
        "class LocalTextBudgetExceeded",
        "only loopback local text endpoints are permitted",
        "another local text adapter owns llm_client",
        "llm_client drift detected during exact rollback",
        "local text stream timed out",
        "local text stream unavailable",
        "_onyx_local_text_compat_v1_owner",
        'values.get(FEATURE_FLAG) != "true"',
    )
    assert all(value in source for value in required)


def _verify_host_ast() -> None:
    source = (ROOT / "core/llm_client.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"call_llm", "call_llm_text", "call_llm_stream", "_stream_openai"} <= set(
        functions
    )
    assert [argument.arg for argument in functions["call_llm"].args.args] == [
        "messages",
        "tools",
        "timeout",
    ]
    assert [argument.arg for argument in functions["call_llm_text"].args.args] == [
        "prompt",
        "system",
        "model",
        "timeout",
    ]
    assert [argument.arg for argument in functions["call_llm_stream"].args.args] == [
        "messages",
        "tools",
        "timeout",
    ]
    required = (
        'f"{url}/v1/chat/completions"',
        'f"{url}/api/chat"',
        '"max_tokens": 150',
        '"max_tokens": 600',
        '"num_predict": 150',
        '"num_predict": 600',
        '"tool_choice"] = "auto"',
        '{"type": "sentence", "text": sentence}',
        '"type":       "done"',
    )
    assert all(value in source for value in required)


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
    assert data["schema"] == "OnyxPhase6LocalTextCompatibility.v1"
    assert data["candidate"] == "phase6-local-text-compat-candidate-001"
    assert data["status"] == "candidate_default_off_not_live"
    assert data["activation"] == {
        "flag": "ONYX_PHASE6_LOCAL_TEXT_COMPAT_V1",
        "enabled_value": "true",
        "exact": "ONYX_PHASE6_LOCAL_TEXT_COMPAT_V1=true",
        "default": "off",
        "factory_only": True,
        "explicit_install_required": True,
        "live_wiring": False,
    }
    assert data["artifact_root_algorithm"] == "sha256-sorted-path-nul-digest-lf-v1"
    entries = data["artifacts"]
    assert {item["path"] for item in entries} == EXPECTED_ARTIFACTS
    assert len(entries) == 5
    for item in entries:
        path = ROOT / item["path"]
        assert path.stat().st_size == item["bytes"]
        assert digest(item["path"]) == item["sha256"]
    assert artifact_root(entries) == data["artifact_root_sha256"]
    assert data["frozen_anchors"] == FROZEN
    assert all(digest(relative) == expected for relative, expected in FROZEN.items())

    contracts = data["contracts"]
    assert contracts["providers"] == ["ollama", "openai_compatible"]
    assert contracts["host_surfaces"] == [
        "call_llm",
        "call_llm_text",
        "call_llm_stream",
    ]
    assert contracts["network_calls"] == 0
    assert contracts["real_provider_calls"] == 0
    assert contracts["transport"] == "factory_injected_only"
    assert contracts["privacy"] == "http_loopback_only"
    assert contracts["silent_cross_routing"] is False
    assert contracts["exact_rollback"] is True
    assert contracts["llm_client_bytes_changed"] is False
    assert contracts["timeouts_cancellation_budgets"] is True
    assert contracts["timeout_enforcement"] == "injected_transport"
    assert contracts["blocking_cancellation"] == "cooperative"
    assert contracts["lazy_stream_failure_mapping"] is True
    assert contracts["owner_drift_restoration"] is True
    assert contracts["streaming_nonstreaming"] is True
    assert contracts["tool_call_parity"] is True
    assert data["verification"]["focused"] == "31 passed"
    assert data["verification"]["e6"] == "not_performed"
    assert data["verification"]["live_activation"] is False

    _verify_candidate_ast((ROOT / MODULE).read_text(encoding="utf-8"))
    _verify_host_ast()
    checked = 0
    for path in _live_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        checked += 1
        assert "phase6_local_text_compat_v1" not in text
        assert "ONYX_PHASE6_LOCAL_TEXT_COMPAT_V1" not in text

    result = subprocess.run(
        [
            str(ROOT / ".venv" / "Scripts" / "python.exe"),
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            str(ROOT / TESTS),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "31 passed" in result.stdout
    return {
        "candidate": data["candidate"],
        "artifact_root_sha256": data["artifact_root_sha256"],
        "live_files_checked": checked,
        "focused": "31 passed",
        "network_calls": 0,
        "e6": "not_performed",
        "marker": MARKER,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
