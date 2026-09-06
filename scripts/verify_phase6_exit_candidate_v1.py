"""Reproduce the evidence-only Phase 6 Exit Candidate V1."""

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

from core import phase6_exit_candidate_v1 as candidate  # noqa: E402


MANIFEST = PROJECT / "docs/onyx/checkpoints/phase6-exit-candidate-v1/manifest.json"
CHECKPOINT = (
    PROJECT / "docs/onyx/checkpoints/phase6-exit-candidate-v1/"
    "PHASE6_EXIT_CANDIDATE_V1_CHECKPOINT.md"
)
SELECTION = (
    PROJECT / "docs/onyx/checkpoints/phase6-exit-candidate-v1/cumulative-selection.json"
)
MARKER = "P6_EXIT_CANDIDATE_V1_OK"
SCHEMA = "onyx.phase6.exit-candidate.v1"
ROOT_ALGORITHM = "sha256-sorted-path-nul-digest-lf-v1"
ARTIFACT_PATHS = (
    "core/phase6_exit_candidate_v1.py",
    "tests/test_phase6_exit_candidate_v1.py",
    "scripts/verify_phase6_exit_candidate_v1.py",
    "docs/onyx/adrs/ADR-0028-phase6-exit-candidate-v1.md",
    (
        "docs/onyx/checkpoints/phase6-exit-candidate-v1/"
        "PHASE6_EXIT_CANDIDATE_V1_CHECKPOINT.md"
    ),
    ("docs/onyx/checkpoints/phase6-exit-candidate-v1/cumulative-selection.json"),
    ("docs/onyx/checkpoints/phase6-exit-candidate-v1/CAPABILITY_DELTA_SNAPSHOT.md"),
)
FORBIDDEN_LIVE_SURFACES = (
    "main.py",
    "ui.py",
    "dashboard/server.py",
    "scripts/launch_onyx_live_v13.pyw",
)


class Phase6ExitCandidateV1VerificationError(RuntimeError):
    """The frozen candidate cannot be reproduced exactly."""


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase6ExitCandidateV1VerificationError(
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
        raise Phase6ExitCandidateV1VerificationError(
            f"unreadable JSON: {path.relative_to(PROJECT)}"
        ) from exc
    if type(value) is not dict:
        raise Phase6ExitCandidateV1VerificationError("JSON object required")
    return value


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Phase6ExitCandidateV1VerificationError(
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
        "claims",
        "environment",
        "component_acceptance_root",
        "verification",
        "rollback",
        "limitations",
        "artifacts",
        "artifact_root_sha256",
    }
    if (
        set(manifest) != expected_keys
        or manifest.get("schema") != SCHEMA
        or manifest.get("candidate") != candidate.CANDIDATE
        or manifest.get("created_at") != "2026-07-23T15:07:30-04:00"
        or manifest.get("status") != "candidate_e1_e5_e6_pending"
        or manifest.get("feature_flag") != candidate.FEATURE_FLAG
        or manifest.get("enabled_value") != candidate.ENABLED_VALUE
        or manifest.get("default_off") is not True
    ):
        raise Phase6ExitCandidateV1VerificationError("manifest identity drift")
    expected_claims = {
        "e1_e5_ready": True,
        "ready_for_external_gate": True,
        "external_e6_accepted": False,
        "phase6_exit": False,
        "phase7_unlocked": False,
        "runtime_authority_added": False,
        "permanent_provider_availability": False,
        "external_agent_authority": False,
        "cross_route_authority": False,
        "additional_provider_authority": False,
    }
    if manifest.get("claims") != expected_claims:
        raise Phase6ExitCandidateV1VerificationError("manifest overclaim")
    artifacts = manifest.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != len(ARTIFACT_PATHS):
        raise Phase6ExitCandidateV1VerificationError("artifact closure drift")
    observed: dict[str, str] = {}
    for index, record in enumerate(artifacts):
        if (
            type(record) is not dict
            or set(record) != {"path", "bytes", "sha256"}
            or record.get("path") != ARTIFACT_PATHS[index]
            or type(record.get("bytes")) is not int
            or type(record.get("sha256")) is not str
        ):
            raise Phase6ExitCandidateV1VerificationError(
                "artifact record contract drift"
            )
        relative = record["path"]
        path = PROJECT / relative
        if path.stat().st_size != record["bytes"]:
            raise Phase6ExitCandidateV1VerificationError(
                f"artifact byte-count drift: {relative}"
            )
        actual = _digest(path)
        if actual != record["sha256"]:
            raise Phase6ExitCandidateV1VerificationError(
                f"artifact hash drift: {relative}"
            )
        observed[relative] = actual
    if manifest.get("artifact_root_sha256") != _root(observed) or manifest.get(
        "component_acceptance_root"
    ) != {
        "algorithm": ROOT_ALGORITHM,
        "count": len(candidate.EVIDENCE_ROOTS),
        "sha256": _root({root.path: root.sha256 for root in candidate.EVIDENCE_ROOTS}),
    }:
        raise Phase6ExitCandidateV1VerificationError("aggregate root drift")
    return manifest, observed


def _verify_candidate_contract() -> dict[str, object]:
    if (
        candidate.create_phase6_exit_candidate_v1(
            gate=candidate.Phase6ExitFeatureGateV1(False),
            project_root=PROJECT / "deliberately-missing",
        )
        is not None
    ):
        raise Phase6ExitCandidateV1VerificationError("default-off constructed")
    report = candidate.create_phase6_exit_candidate_v1(
        gate=candidate.Phase6ExitFeatureGateV1(True),
        project_root=PROJECT,
    )
    if report is None:
        raise Phase6ExitCandidateV1VerificationError("candidate did not construct")
    payload = {name: getattr(report, name) for name in report.__dataclass_fields__}
    expected_false = (
        "external_e6_accepted",
        "phase6_exit",
        "phase7_unlocked",
        "runtime_authority_added",
        "permanent_provider_availability",
        "external_agent_authority",
        "cross_route_authority",
        "additional_provider_authority",
    )
    if (
        payload["component_acceptances"] != 8
        or payload["evidence_roots"] != len(candidate.EVIDENCE_ROOTS)
        or payload["e1_e5_ready"] is not True
        or payload["ready_for_external_gate"] is not True
        or payload["live_observation_only"] is not True
        or any(payload[name] is not False for name in expected_false)
        or any(payload[name] != 0 for name in candidate.CALL_COUNTER_KEYS)
    ):
        raise Phase6ExitCandidateV1VerificationError("candidate report drift")
    for relative in FORBIDDEN_LIVE_SURFACES:
        if candidate.FEATURE_FLAG in (PROJECT / relative).read_text(encoding="utf-8"):
            raise Phase6ExitCandidateV1VerificationError(
                f"candidate leaked into live surface: {relative}"
            )
    return payload


def _verify_selection(run_tests: bool) -> dict[str, object]:
    selection = _strict_json(SELECTION)
    expected = selection.get("expected")
    tests = selection.get("tests")
    if (
        selection.get("schema") != "onyx.phase6.exit-candidate.v1.cumulative-selection"
        or selection.get("execution") != "one-test-file-per-fresh-python-process"
        or expected
        != {
            "passed": 294,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "test_files": 14,
        }
        or type(tests) is not list
        or len(tests) != 14
    ):
        raise Phase6ExitCandidateV1VerificationError("selection contract drift")
    if len({item.get("path") for item in tests if type(item) is dict}) != 14:
        raise Phase6ExitCandidateV1VerificationError("selection membership drift")
    if sum(item.get("passed", -1) for item in tests) != 294:
        raise Phase6ExitCandidateV1VerificationError("selection pass count drift")
    if run_tests:
        for index, item in enumerate(tests, start=1):
            if (
                type(item) is not dict
                or set(item) != {"path", "passed"}
                or type(item["path"]) is not str
                or type(item["passed"]) is not int
                or not (PROJECT / item["path"]).is_file()
            ):
                raise Phase6ExitCandidateV1VerificationError(
                    "selection item contract drift"
                )
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    item["path"],
                    "-q",
                    "--disable-warnings",
                    "--basetemp",
                    f".pytest-phase6-exit-v1-verify-{index}",
                ],
                cwd=PROJECT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            match = re.search(r"(\d+) passed", process.stdout)
            if (
                process.returncode != 0
                or match is None
                or int(match.group(1)) != item["passed"]
                or " failed" in process.stdout
                or " error" in process.stdout.casefold()
                or " skipped" in process.stdout
            ):
                raise Phase6ExitCandidateV1VerificationError(
                    f"selected test failed: {item['path']}"
                )
    return expected


def verify(*, run_tests: bool = False) -> dict[str, object]:
    manifest, observed = _verify_manifest()
    report = _verify_candidate_contract()
    selection = _verify_selection(run_tests)
    verification = manifest.get("verification")
    rollback = manifest.get("rollback")
    if (
        verification
        != {
            "selected_test_files": 14,
            "passed": 294,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "ruff_lint": "passed",
            "ruff_format": "passed",
            "py_compile": "passed",
        }
        or rollback
        != {
            "kind": "evidence-only",
            "runtime_state_created": False,
            "application_restart_required": False,
            "disable_flag_restores_pre_candidate_runtime": True,
        }
        or not CHECKPOINT.is_file()
    ):
        raise Phase6ExitCandidateV1VerificationError(
            "verification or rollback contract drift"
        )
    return {
        "candidate": candidate.CANDIDATE,
        "artifacts": len(observed),
        "artifact_root_sha256": manifest["artifact_root_sha256"],
        "component_acceptance_root_sha256": manifest["component_acceptance_root"][
            "sha256"
        ],
        "component_acceptances": report["component_acceptances"],
        "evidence_roots": report["evidence_roots"],
        "selection": selection,
        "tests_executed": run_tests,
        "e1_e5_ready": True,
        "ready_for_external_gate": True,
        "external_e6_accepted": False,
        "phase6_exit": False,
        "phase7_unlocked": False,
        "runtime_authority_added": False,
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
