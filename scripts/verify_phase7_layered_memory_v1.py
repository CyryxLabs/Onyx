"""Reproduce the Phase 7 Layered Memory V1 candidate."""

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

from core import phase7_layered_memory_v1 as candidate  # noqa: E402

MANIFEST = PROJECT / "docs/onyx/checkpoints/phase7-layered-memory-v1/manifest.json"
SELECTION = (
    PROJECT / "docs/onyx/checkpoints/phase7-layered-memory-v1/"
    "cumulative-selection.json"
)
MARKER = "P7_LAYERED_MEMORY_V1_OK"
SCHEMA = "onyx.phase7.layered-memory.v1"
ARTIFACT_PATHS = (
    "core/phase7_layered_memory_v1.py",
    "tests/test_phase7_layered_memory_v1.py",
    "scripts/verify_phase7_layered_memory_v1.py",
    "docs/onyx/adrs/ADR-0033-phase7-layered-memory-v1.md",
    (
        "docs/onyx/checkpoints/phase7-layered-memory-v1/"
        "PHASE7_LAYERED_MEMORY_V1_CHECKPOINT.md"
    ),
    ("docs/onyx/checkpoints/phase7-layered-memory-v1/" "CAPABILITY_DELTA_SNAPSHOT.md"),
    ("docs/onyx/checkpoints/phase7-layered-memory-v1/" "cumulative-selection.json"),
)


class Phase7LayeredMemoryV1VerificationError(RuntimeError):
    """The frozen layered-memory candidate cannot reproduce."""


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise Phase7LayeredMemoryV1VerificationError(
                    f"duplicate JSON key: {key}"
                )
            value[key] = item
        return value

    def reject_constant(_value: str) -> object:
        raise Phase7LayeredMemoryV1VerificationError("non-finite JSON number")

    try:
        parsed = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase7LayeredMemoryV1VerificationError("JSON is unreadable") from exc
    if type(parsed) is not dict:
        raise Phase7LayeredMemoryV1VerificationError("JSON object required")
    return parsed


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Phase7LayeredMemoryV1VerificationError(
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
        "workspace_memory_entry_root",
        "layers",
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
        or manifest.get("candidate") != "phase7-layered-memory-v1"
        or manifest.get("created_at") != "2026-07-23T18:15:00-04:00"
        or manifest.get("status") != "candidate_e1_e5_e6_pending"
        or manifest.get("feature_flag") != candidate.FEATURE_FLAG
        or manifest.get("enabled_value") != candidate.ENABLED_VALUE
        or manifest.get("default_off") is not True
        or manifest.get("layers") != list(candidate.LAYERS)
    ):
        raise Phase7LayeredMemoryV1VerificationError("manifest identity drift")
    entry = manifest.get("workspace_memory_entry_root")
    if type(entry) is not dict or entry != {
        "acceptance_id": "VE-P7-WORKSPACE-MEMORY-V1-E6-001",
        "candidate_manifest_sha256": (
            "59ed88abd6967a73f3050d1215fed0c278b21b5c6e5335814abe8267576c9cd7"
        ),
        "decision": "accepted",
    }:
        raise Phase7LayeredMemoryV1VerificationError(
            "Workspace Memory entry root drift"
        )
    expected_claims = {
        "seven_typed_layers": True,
        "workspace_principal_isolation": True,
        "pre_ranking_hard_filters": True,
        "hmac_integrity": True,
        "normalized_deduplication": True,
        "explicit_entity_resolution": True,
        "correction": True,
        "supersession": True,
        "contradiction_preservation": True,
        "freshness_validity": True,
        "retention_tombstones": True,
        "principal_export_delete": True,
        "source_deletion": True,
        "poisoning_defenses": True,
        "instruction_authority": False,
        "global_vector_index": False,
        "general_nlp_entity_extraction": False,
        "accepted_workspace_memory_modified": False,
        "e1_e5_ready": True,
        "external_e6_accepted": False,
        "live_wiring": False,
        "runtime_authority_added": False,
        "phase7_exit": False,
        "full_onyx_prd_complete": False,
    }
    if manifest.get("claims") != expected_claims:
        raise Phase7LayeredMemoryV1VerificationError(
            "manifest claim drift or overclaim"
        )
    artifacts = manifest.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != len(ARTIFACT_PATHS):
        raise Phase7LayeredMemoryV1VerificationError("artifact closure drift")
    observed: dict[str, str] = {}
    for index, item in enumerate(artifacts):
        if (
            type(item) is not dict
            or set(item) != {"path", "bytes", "sha256"}
            or item.get("path") != ARTIFACT_PATHS[index]
            or type(item.get("bytes")) is not int
            or type(item.get("sha256")) is not str
        ):
            raise Phase7LayeredMemoryV1VerificationError("artifact record drift")
        path = PROJECT / item["path"]
        if path.stat().st_size != item["bytes"] or _digest(path) != item["sha256"]:
            raise Phase7LayeredMemoryV1VerificationError(
                f"artifact hash drift: {item['path']}"
            )
        observed[item["path"]] = item["sha256"]
    if manifest.get("artifact_root_sha256") != _root(observed):
        raise Phase7LayeredMemoryV1VerificationError("artifact root drift")
    return manifest, observed


def _verify_contract() -> None:
    candidate._verify_entry(PROJECT)
    if (
        candidate.create_layered_memory_catalog_v1(
            gate=candidate.LayeredMemoryFeatureGateV1(False),
            project_root=PROJECT / "missing",
        )
        is not None
    ):
        raise Phase7LayeredMemoryV1VerificationError("default-off factory constructed")
    source = (PROJECT / "core/phase7_layered_memory_v1.py").read_text(encoding="utf-8")
    required = (
        '"session_working"',
        '"episodic_mission"',
        '"semantic_institutional"',
        '"decision"',
        '"procedural"',
        '"preference"',
        '"temporal_status"',
        "new entity value requires explicit correction",
        "Authorization, lifecycle, source, validity, sensitivity and freshness",
        '"content_trust": "untrusted_data"',
        '"instructions_authority": False',
        "secret-like content is not eligible",
        "source_deleted:",
        "retention_expired",
    )
    forbidden = (
        "import requests",
        "import httpx",
        "import socket",
        "import subprocess",
        "import webbrowser",
        "urlopen(",
        "requests.",
        "MemoryStore(",
        "vector_index",
        "llm_client",
        "live_model",
        "dispatch(",
    )
    if any(value not in source for value in required) or any(
        value in source for value in forbidden
    ):
        raise Phase7LayeredMemoryV1VerificationError(
            "layered-memory source invariant drift"
        )
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "scripts/launch_onyx_live_v13.pyw",
    ):
        if candidate.FEATURE_FLAG in (PROJECT / relative).read_text(encoding="utf-8"):
            raise Phase7LayeredMemoryV1VerificationError(
                f"candidate leaked into live surface: {relative}"
            )
    accepted = (PROJECT / "core/phase7_workspace_memory_v1.py").read_bytes()
    if (
        hashlib.sha256(accepted).hexdigest()
        != "290e8f1b4d1d71fb30f98b5d5da928962cfa4ab69e273fe4dbdeaebbd851a66e"
    ):
        raise Phase7LayeredMemoryV1VerificationError(
            "accepted Workspace Memory implementation drift"
        )


def _verify_selection(run_tests: bool) -> dict[str, object]:
    selection = _strict_json(SELECTION)
    expected = {
        "test_files": 9,
        "passed": 161,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
        "subtests_passed": 77,
    }
    tests = selection.get("tests")
    if (
        selection.get("schema") != "onyx.phase7.layered-memory.v1.cumulative-selection"
        or selection.get("execution") != "one-test-file-per-fresh-python-process"
        or selection.get("expected") != expected
        or type(tests) is not list
        or len(tests) != expected["test_files"]
    ):
        raise Phase7LayeredMemoryV1VerificationError("selection contract drift")
    totals = {
        key: sum(int(item[key]) for item in tests)
        for key in ("passed", "skipped", "subtests_passed")
    }
    if totals != {
        "passed": expected["passed"],
        "skipped": expected["skipped"],
        "subtests_passed": expected["subtests_passed"],
    }:
        raise Phase7LayeredMemoryV1VerificationError("selection totals drift")
    if run_tests:
        temporary_root = PROJECT / "runtime/test-tmp/phase7-layered-memory-v1-verify"
        temporary_root.mkdir(parents=True, exist_ok=True)
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
                    str(temporary_root / str(index)),
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
            ):
                raise Phase7LayeredMemoryV1VerificationError(
                    f"selection failed: {item['path']}\n"
                    f"{process.stdout}\n{process.stderr}"
                )
    return expected


def verify(*, run_tests: bool = True) -> dict[str, object]:
    manifest, artifacts = _verify_manifest()
    _verify_contract()
    results = _verify_selection(run_tests)
    return {
        "candidate": manifest["candidate"],
        "artifact_root_sha256": manifest["artifact_root_sha256"],
        "artifacts": len(artifacts),
        "results": results,
        "marker": MARKER,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-tests", action="store_true")
    args = parser.parse_args()
    result = verify(run_tests=not args.no_tests)
    print(json.dumps(result, sort_keys=True))
    print(MARKER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
