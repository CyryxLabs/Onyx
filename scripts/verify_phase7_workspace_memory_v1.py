"""Reproduce the Phase 7 Workspace Memory V1 candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core import phase7_workspace_memory_v1 as candidate  # noqa: E402


MANIFEST = PROJECT / "docs/onyx/checkpoints/phase7-workspace-memory-v1/manifest.json"
SELECTION = (
    PROJECT
    / "docs/onyx/checkpoints/phase7-workspace-memory-v1/cumulative-selection.json"
)
MARKER = "P7_WORKSPACE_MEMORY_V1_OK"
SCHEMA = "onyx.phase7.workspace-memory.v1"
ARTIFACT_PATHS = (
    "core/phase7_workspace_memory_v1.py",
    "tests/test_phase7_workspace_memory_v1.py",
    "scripts/verify_phase7_workspace_memory_v1.py",
    "docs/onyx/adrs/ADR-0029-phase7-workspace-memory-v1.md",
    (
        "docs/onyx/checkpoints/phase7-workspace-memory-v1/"
        "PHASE7_WORKSPACE_MEMORY_V1_CHECKPOINT.md"
    ),
    ("docs/onyx/checkpoints/phase7-workspace-memory-v1/CAPABILITY_DELTA_SNAPSHOT.md"),
    ("docs/onyx/checkpoints/phase7-workspace-memory-v1/cumulative-selection.json"),
)


class Phase7WorkspaceMemoryV1VerificationError(RuntimeError):
    """The frozen Workspace Memory V1 candidate cannot reproduce."""


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase7WorkspaceMemoryV1VerificationError(
                    f"duplicate JSON key: {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase7WorkspaceMemoryV1VerificationError("JSON is unreadable") from exc
    if type(value) is not dict:
        raise Phase7WorkspaceMemoryV1VerificationError("JSON object required")
    return value


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Phase7WorkspaceMemoryV1VerificationError(
            f"artifact unavailable: {path.relative_to(PROJECT)}"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(records: dict[str, str]) -> str:
    rows = [f"{path}\0{digest}\n" for path, digest in records.items()]
    return hashlib.sha256("".join(sorted(rows)).encode("utf-8")).hexdigest()


def _verify_manifest() -> tuple[dict[str, Any], dict[str, str]]:
    manifest = _strict_json(MANIFEST)
    expected_keys = {
        "schema",
        "candidate",
        "created_at",
        "status",
        "feature_flag",
        "enabled_value",
        "default_off",
        "phase6_entry_root",
        "claims",
        "verification",
        "effects",
        "rollback",
        "limitations",
        "artifacts",
        "artifact_root_sha256",
    }
    if (
        set(manifest) != expected_keys
        or manifest.get("schema") != SCHEMA
        or manifest.get("candidate") != "phase7-workspace-memory-v1"
        or manifest.get("created_at") != "2026-07-23T15:43:03-04:00"
        or manifest.get("status") != "candidate_e1_e5_e6_pending"
        or manifest.get("feature_flag") != candidate.FEATURE_FLAG
        or manifest.get("enabled_value") != candidate.ENABLED_VALUE
        or manifest.get("default_off") is not True
    ):
        raise Phase7WorkspaceMemoryV1VerificationError("manifest identity drift")
    expected_claims = {
        "workspace_memory_v1_implemented": True,
        "pre_ranking_hard_filters": True,
        "read_only": True,
        "e1_e5_ready": True,
        "external_e6_accepted": False,
        "live_wiring": False,
        "phase7_exit": False,
        "company_graph_implemented": False,
        "founder_brief_implemented": False,
        "full_onyx_prd_complete": False,
    }
    if manifest.get("claims") != expected_claims:
        raise Phase7WorkspaceMemoryV1VerificationError("manifest overclaim")
    artifacts = manifest.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != len(ARTIFACT_PATHS):
        raise Phase7WorkspaceMemoryV1VerificationError("artifact closure drift")
    observed: dict[str, str] = {}
    for index, item in enumerate(artifacts):
        if (
            type(item) is not dict
            or set(item) != {"path", "bytes", "sha256"}
            or item.get("path") != ARTIFACT_PATHS[index]
            or type(item.get("bytes")) is not int
            or type(item.get("sha256")) is not str
        ):
            raise Phase7WorkspaceMemoryV1VerificationError("artifact record drift")
        path = PROJECT / item["path"]
        if path.stat().st_size != item["bytes"] or _digest(path) != item["sha256"]:
            raise Phase7WorkspaceMemoryV1VerificationError(
                f"artifact hash drift: {item['path']}"
            )
        observed[item["path"]] = item["sha256"]
    if manifest.get("artifact_root_sha256") != _root(observed):
        raise Phase7WorkspaceMemoryV1VerificationError("artifact root drift")
    return manifest, observed


def _verify_contract() -> None:
    candidate._verify_phase6_entry(PROJECT)
    if (
        candidate.create_workspace_memory_adapter_v1(
            gate=candidate.WorkspaceMemoryFeatureGateV1(False),
            project_root=PROJECT / "missing",
        )
        is not None
    ):
        raise Phase7WorkspaceMemoryV1VerificationError(
            "default-off factory constructed"
        )
    source = (PROJECT / "core/phase7_workspace_memory_v1.py").read_text(
        encoding="utf-8"
    )
    required = (
        '"SELECT * FROM memories WHERE id=?"',
        "?mode=ro",
        "PRAGMA query_only=ON",
        'content_trust="untrusted_data"',
        "MemoryStore changed during read-only snapshot",
        "workspace metadata changed during retrieval",
    )
    forbidden = (
        "SELECT * FROM memories LIMIT",
        "self._memory_store.search(",
        "self._memory_store.list(",
        "import requests",
        "import subprocess",
        "import socket",
    )
    if any(value not in source for value in required) or any(
        value in source for value in forbidden
    ):
        raise Phase7WorkspaceMemoryV1VerificationError("source invariant drift")
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "scripts/launch_onyx_live_v13.pyw",
    ):
        if candidate.FEATURE_FLAG in (PROJECT / relative).read_text(encoding="utf-8"):
            raise Phase7WorkspaceMemoryV1VerificationError(
                f"candidate leaked into live surface: {relative}"
            )
    matrix = (PROJECT / "docs/onyx/CAPABILITY_MATRIX.md").read_text(encoding="utf-8")
    if (
        "## Phase 7 Workspace Memory V1 E1-E5 candidate (E6 pending)" not in matrix
        or "Company Graph | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED`" not in matrix
    ):
        raise Phase7WorkspaceMemoryV1VerificationError("capability delta is absent")


def _verify_selection(run_tests: bool) -> dict[str, object]:
    selection = _strict_json(SELECTION)
    expected = {
        "passed": 77,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
        "subtests_passed": 73,
        "test_files": 5,
    }
    tests = selection.get("tests")
    if (
        selection.get("schema")
        != "onyx.phase7.workspace-memory.v1.cumulative-selection"
        or selection.get("execution") != "one-test-file-per-fresh-python-process"
        or selection.get("expected") != expected
        or selection.get("explained_skips")
        != [
            {
                "path": "tests/test_workspace_registry_audit.py",
                "reason": "FIFO creation is unavailable on Windows",
            }
        ]
        or type(tests) is not list
        or len(tests) != 5
    ):
        raise Phase7WorkspaceMemoryV1VerificationError("selection contract drift")
    if run_tests:
        for index, item in enumerate(tests, start=1):
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    item["path"],
                    "-q",
                    "-rs",
                    "--disable-warnings",
                    "--basetemp",
                    f".pytest-phase7-workspace-memory-v1-verify-{index}",
                ],
                cwd=PROJECT,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            passed = re.search(r"(\d+) passed", process.stdout)
            skipped = re.search(r"(\d+) skipped", process.stdout)
            subtests = re.search(r"(\d+) subtests passed", process.stdout)
            observed_skipped = int(skipped.group(1)) if skipped else 0
            observed_subtests = int(subtests.group(1)) if subtests else 0
            if (
                process.returncode != 0
                or passed is None
                or int(passed.group(1)) != item["passed"]
                or observed_skipped != item["skipped"]
                or observed_subtests != item["subtests_passed"]
                or " failed" in process.stdout
                or " error" in process.stdout.casefold()
            ):
                raise Phase7WorkspaceMemoryV1VerificationError(
                    f"selected test failed: {item['path']}"
                )
            if item["skipped"] == 1 and (
                "FIFO creation is unavailable on this platform" not in process.stdout
            ):
                raise Phase7WorkspaceMemoryV1VerificationError(
                    "platform skip reason drift"
                )
    return expected


def verify(*, run_tests: bool = False) -> dict[str, object]:
    manifest, observed = _verify_manifest()
    _verify_contract()
    selection = _verify_selection(run_tests)
    if manifest.get("verification") != {
        "test_files": 5,
        "passed": 77,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
        "explained_platform_skips": 1,
        "subtests_passed": 73,
        "ruff_lint": "passed",
        "ruff_format": "passed",
        "py_compile": "passed",
    } or manifest.get("effects") != {
        "persistent_writes": 0,
        "network_calls": 0,
        "provider_calls": 0,
        "process_calls": 0,
        "live_calls": 0,
        "legacy_search_calls": 0,
        "legacy_list_calls": 0,
    }:
        raise Phase7WorkspaceMemoryV1VerificationError(
            "verification/effects contract drift"
        )
    return {
        "candidate": "phase7-workspace-memory-v1",
        "artifacts": len(observed),
        "artifact_root_sha256": manifest["artifact_root_sha256"],
        "phase6_entry_roots": len(candidate.PHASE6_EXIT_ROOTS),
        "selection": selection,
        "tests_executed": run_tests,
        "default_off": True,
        "read_only": True,
        "pre_ranking_hard_filters": True,
        "external_e6_accepted": False,
        "live_wiring": False,
        "phase7_exit": False,
        "company_graph_implemented": False,
        "founder_brief_implemented": False,
        "persistent_writes": 0,
        "network_calls": 0,
        "provider_calls": 0,
        "process_calls": 0,
        "live_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args()
    result = verify(run_tests=args.run_tests)
    print(f"{MARKER} {json.dumps(result, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
