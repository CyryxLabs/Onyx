"""Verify isolated provider-free Research and Independent Verifier Cells V1."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve(strict=True).parents[1]
MODULE = "core/phase6_research_cells_v1.py"
TESTS = "tests/test_phase6_research_cells_v1.py"
ADR = "docs/onyx/adrs/ADR-0023-phase6-research-cells-v1.md"
CHECKPOINT = (
    "docs/onyx/checkpoints/phase6-research-cells-v1/"
    "PHASE6_RESEARCH_CELLS_V1_CHECKPOINT.md"
)
VERIFIER = "scripts/verify_phase6_research_cells_v1.py"
MANIFEST = "docs/onyx/checkpoints/phase6-research-cells-v1/manifest.json"
MARKER = "P6_RESEARCH_CELLS_V1_OK"
EXPECTED_ARTIFACTS = {MODULE, TESTS, ADR, CHECKPOINT, VERIFIER}
FROZEN = {
    "core/phase6_agentic_core_v1.py": (
        "ab7a6cfec738c31b7beb66ac7a66584f892231ce8a3a2c9e81f30945123cc965"
    ),
    "core/phase6_agentic_core_v6.py": (
        "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a"
    ),
    "docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json": (
        "cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15"
    ),
    "docs/onyx/acceptance/VE-P6-AGENTIC-CORE-V6-E6-001.md": (
        "5a42068983942c1bf163fc7b8fddaf8ce336cb5a253a228e319943cc04d8d23d"
    ),
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
    "dashboard/server.py": (
        "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1"
    ),
    "core/phase6_live_wiring_v1.py": (
        "a658f430c10bb992724ad7bbd2ddae94b3c83f8893608fe724b241302b55d55f"
    ),
    "core/onyx_live_activation_v9.py": (
        "deb26314ef3871cb12fc8e3cee936f88e385122fad242c830580421ccb22a9d2"
    ),
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


def digest(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def artifact_root(items: list[dict[str, object]]) -> str:
    payload = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(items, key=lambda item: str(item["path"]))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_ast(source: str) -> None:
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    if FORBIDDEN_IMPORTS & imports:
        raise AssertionError("provider or network import entered candidate")
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    if FORBIDDEN_CALLS & calls:
        raise AssertionError("provider or network call entered candidate")
    core_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        in {
            "core.phase6_agentic_core_v1",
            "core.phase6_agentic_core_v6",
        }
        for alias in node.names
    }
    assert {
        "AgenticCoreV6",
        "AgenticStateStoreV6",
        "WorkspaceScopeV1",
        "RESEARCH_OPERATOR_V1",
        "VERIFIER_OPERATOR_V1",
    } <= core_imports
    public = {
        node.name: tuple(argument.arg for argument in node.args.args)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name in {"research", "verify", "finalize"}
    }
    assert public
    assert all("instruction" not in arguments for arguments in public.values())
    required = (
        'FEATURE_FLAG: Final = "ONYX_PHASE6_RESEARCH_CELLS_V1"',
        "class ProviderFreeResearchCellV1",
        "class IndependentVerifierCellV1",
        "class ResearchVerifierPipelineV1",
        "candidate_not_certified",
        "content_is_data_never_instruction",
        "create_evidence_bundle_v1",
        "forged evidence bundle denied",
        "unsupported_claim",
        "claim_projection_drift",
        "contradiction",
        "stale_evidence",
        "receipt replay map drift denied",
        "research candidate item or byte budget exhausted",
        "with self._lock",
        "pipeline finalization requires independent acceptance",
        "hmac.compare_digest",
        "research operation cancelled",
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
    assert data["schema"] == "OnyxPhase6ResearchCells.v1"
    assert data["candidate"] == "phase6-research-cells-candidate-001"
    assert data["status"] == "candidate_default_off_not_live"
    assert data["activation"] == {
        "flag": "ONYX_PHASE6_RESEARCH_CELLS_V1",
        "enabled_value": "true",
        "exact": "ONYX_PHASE6_RESEARCH_CELLS_V1=true",
        "default": "off",
        "factory_only": True,
        "live_wiring": False,
    }
    assert data["artifact_root_algorithm"] == ("sha256-sorted-path-nul-digest-lf-v1")
    entries = data["artifacts"]
    assert {item["path"] for item in entries} == EXPECTED_ARTIFACTS
    assert len(entries) == 5
    for item in entries:
        path = ROOT / item["path"]
        assert path.stat().st_size == item["bytes"]
        assert digest(item["path"]) == item["sha256"]
    assert artifact_root(entries) == data["artifact_root_sha256"]
    assert data["frozen_anchors"] == FROZEN
    for relative, expected in FROZEN.items():
        assert digest(relative) == expected

    contracts = data["contracts"]
    assert contracts["exact_agentic_core"] == [
        "AgenticCoreV6",
        "AgenticStateStoreV6",
        "WorkspaceScopeV1",
        "RESEARCH_OPERATOR_V1",
        "VERIFIER_OPERATOR_V1",
    ]
    assert contracts["research_self_certifies"] is False
    assert contracts["verifier_generates_facts"] is False
    assert contracts["finalize_requires_independent_accept"] is True
    assert contracts["provider_invocation"] is False
    assert contracts["network_calls"] == 0
    assert contracts["receipt_authentication"] == "HMAC-SHA-256"
    assert contracts["source_and_bundle_hmac"] is True
    assert contracts["exact_claim_citation_projection"] is True
    assert contracts["candidate_item_byte_bounds"] is True
    assert contracts["atomic_replay_conflict"] is True
    assert contracts["receipt_map_key_binding"] is True
    assert contracts["replay"] == "idempotent_same_input_deny_conflict"
    assert data["verification"]["focused"] == "22 passed"
    assert data["verification"]["cumulative"] == "178 passed"
    assert data["verification"]["e6"] == "not_performed"
    assert data["verification"]["live_activation"] is False

    source = (ROOT / MODULE).read_text(encoding="utf-8")
    _verify_ast(source)
    checked = 0
    for path in _live_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        checked += 1
        assert "phase6_research_cells_v1" not in text
        assert "ONYX_PHASE6_RESEARCH_CELLS_V1" not in text

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
            ".pytest-phase6-research-cells-v1-verify",
            TESTS,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0 and "22 passed" in result.stdout
    return {
        "artifacts": 5,
        "frozen_anchors": len(FROZEN),
        "focused_passed": 22,
        "live_files_checked": checked,
        "network_calls": 0,
        "live": False,
        "e6": False,
    }


if __name__ == "__main__":
    print(MARKER, json.dumps(verify(), sort_keys=True))
