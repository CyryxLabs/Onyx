"""Reproduce the Phase 7 Founder Command V1 candidate."""

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

from core import phase7_founder_command_v1 as candidate  # noqa: E402


MANIFEST = (
    PROJECT / "docs/onyx/checkpoints/phase7-founder-command-v1/manifest.json"
)
SELECTION = (
    PROJECT
    / "docs/onyx/checkpoints/phase7-founder-command-v1/"
    "cumulative-selection.json"
)
MARKER = "P7_FOUNDER_COMMAND_V1_OK"
SCHEMA = "onyx.phase7.founder-command.v1"
ARTIFACT_PATHS = (
    "core/phase7_founder_command_v1.py",
    "tests/test_phase7_founder_command_v1.py",
    "scripts/verify_phase7_founder_command_v1.py",
    "docs/onyx/adrs/ADR-0032-phase7-founder-command-v1.md",
    (
        "docs/onyx/checkpoints/phase7-founder-command-v1/"
        "PHASE7_FOUNDER_COMMAND_V1_CHECKPOINT.md"
    ),
    (
        "docs/onyx/checkpoints/phase7-founder-command-v1/"
        "CAPABILITY_DELTA_SNAPSHOT.md"
    ),
    (
        "docs/onyx/checkpoints/phase7-founder-command-v1/"
        "cumulative-selection.json"
    ),
)


class Phase7FounderCommandV1VerificationError(RuntimeError):
    """The frozen Founder Command candidate cannot reproduce."""


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise Phase7FounderCommandV1VerificationError(
                    f"duplicate JSON key: {key}"
                )
            value[key] = item
        return value

    def reject_constant(_value: str) -> object:
        raise Phase7FounderCommandV1VerificationError(
            "non-finite JSON number"
        )

    try:
        parsed = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase7FounderCommandV1VerificationError(
            "JSON is unreadable"
        ) from exc
    if type(parsed) is not dict:
        raise Phase7FounderCommandV1VerificationError(
            "JSON object required"
        )
    return parsed


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Phase7FounderCommandV1VerificationError(
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
        "company_graph_entry_root",
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
        or manifest.get("candidate") != "phase7-founder-command-v1"
        or manifest.get("created_at") != "2026-07-23T18:30:00-04:00"
        or manifest.get("status") != "candidate_e1_e5_e6_pending"
        or manifest.get("feature_flag") != candidate.FEATURE_FLAG
        or manifest.get("enabled_value") != candidate.ENABLED_VALUE
        or manifest.get("default_off") is not True
    ):
        raise Phase7FounderCommandV1VerificationError(
            "manifest identity drift"
        )
    entry = manifest.get("company_graph_entry_root")
    if (
        type(entry) is not dict
        or entry
        != {
            "acceptance_id": (
                "VE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001"
            ),
            "candidate_manifest_sha256": (
                "fa5fea91caf6914e559cbc22420841b602eeace0153653dc57591fb0070f23f3"
            ),
            "artifact_root_sha256": (
                "d9efc2186412abbf95a1cd03b901c5f797bcb7c50e6b3a6d256211dd2eeac1c3"
            ),
            "decision": "accepted",
        }
    ):
        raise Phase7FounderCommandV1VerificationError(
            "Company Graph entry root drift"
        )
    expected_claims = {
        "daily_founder_brief": True,
        "weekly_operating_review": True,
        "portfolio_view": True,
        "blocker_dependency_report": True,
        "decision_queue": True,
        "revenue_opportunity_queue": True,
        "risk_register": True,
        "what_changed_delta": True,
        "recommended_top_three_actions": True,
        "semantic_freshness_analysis": True,
        "declared_contradiction_preservation": True,
        "structured_status_conflict_detection": True,
        "general_nlp_contradiction_discovery": False,
        "invented_revenue_or_traction": False,
        "persistent_writes": False,
        "e1_e5_ready": True,
        "external_e6_accepted": False,
        "live_wiring": False,
        "runtime_authority_added": False,
        "phase7_exit": False,
        "full_onyx_prd_complete": False,
    }
    if manifest.get("claims") != expected_claims:
        raise Phase7FounderCommandV1VerificationError(
            "manifest claim drift or overclaim"
        )
    artifacts = manifest.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != len(ARTIFACT_PATHS):
        raise Phase7FounderCommandV1VerificationError(
            "artifact closure drift"
        )
    observed: dict[str, str] = {}
    for index, item in enumerate(artifacts):
        if (
            type(item) is not dict
            or set(item) != {"path", "bytes", "sha256"}
            or item.get("path") != ARTIFACT_PATHS[index]
            or type(item.get("bytes")) is not int
            or type(item.get("sha256")) is not str
        ):
            raise Phase7FounderCommandV1VerificationError(
                "artifact record drift"
            )
        path = PROJECT / item["path"]
        if path.stat().st_size != item["bytes"] or _digest(path) != item["sha256"]:
            raise Phase7FounderCommandV1VerificationError(
                f"artifact hash drift: {item['path']}"
            )
        observed[item["path"]] = item["sha256"]
    if manifest.get("artifact_root_sha256") != _root(observed):
        raise Phase7FounderCommandV1VerificationError(
            "artifact root drift"
        )
    return manifest, observed


def _verify_contract() -> None:
    candidate._verify_graph_entry(PROJECT)
    if (
        candidate.create_founder_command_generator_v1(
            gate=candidate.FounderCommandFeatureGateV1(False),
            project_root=PROJECT / "missing",
        )
        is not None
    ):
        raise Phase7FounderCommandV1VerificationError(
            "default-off factory constructed"
        )
    source = (PROJECT / "core/phase7_founder_command_v1.py").read_text(
        encoding="utf-8"
    )
    required = (
        "self._projector.project(",
        "_projection_sha256(",
        "def _brief_sha256(",
        '"potential_undeclared"',
        "previous brief integrity drift",
        "No source-grounded revenue opportunity was supplied",
        '"recommended_top_actions"',
        'content_trust="untrusted_data"',
        "read_only=True",
        "General open-text/NLP contradiction",
    )
    forbidden = (
        "import requests",
        "import subprocess",
        "import socket",
        "import webbrowser",
        "urlopen(",
        "requests.",
        "ArtifactService",
        'execute("INSERT',
        'execute("UPDATE',
        'execute("DELETE',
        "llm_client",
        "live_model",
        "dispatch(",
    )
    if any(value not in source for value in required) or any(
        value in source for value in forbidden
    ):
        raise Phase7FounderCommandV1VerificationError(
            "Founder Command source invariant drift"
        )
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "scripts/launch_onyx_live_v13.pyw",
    ):
        if candidate.FEATURE_FLAG in (
            PROJECT / relative
        ).read_text(encoding="utf-8"):
            raise Phase7FounderCommandV1VerificationError(
                f"candidate leaked into live surface: {relative}"
            )
    matrix = (PROJECT / "docs/onyx/CAPABILITY_MATRIX.md").read_text(
        encoding="utf-8"
    )
    if (
        "## Phase 7 Founder Command V1 E1-E5 candidate (E6 pending)"
        not in matrix
        or "General NLP contradiction discovery | absent | absent"
        not in matrix
    ):
        raise Phase7FounderCommandV1VerificationError(
            "capability delta is absent"
        )


def _verify_selection(run_tests: bool) -> dict[str, object]:
    selection = _strict_json(SELECTION)
    expected = {
        "test_files": 8,
        "passed": 168,
        "failed": 0,
        "errors": 0,
        "skipped": 8,
        "subtests_passed": 65,
    }
    tests = selection.get("tests")
    if (
        selection.get("schema")
        != "onyx.phase7.founder-command.v1.cumulative-selection"
        or selection.get("execution")
        != "one-test-file-per-fresh-python-process"
        or selection.get("expected") != expected
        or type(tests) is not list
        or len(tests) != expected["test_files"]
    ):
        raise Phase7FounderCommandV1VerificationError(
            "selection contract drift"
        )
    totals = {
        key: sum(int(item[key]) for item in tests)
        for key in ("passed", "skipped", "subtests_passed")
    }
    if totals != {
        "passed": expected["passed"],
        "skipped": expected["skipped"],
        "subtests_passed": expected["subtests_passed"],
    }:
        raise Phase7FounderCommandV1VerificationError(
            "selection totals drift"
        )
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
                    f".pytest-phase7-founder-command-v1-verify-{index}",
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
                raise Phase7FounderCommandV1VerificationError(
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
