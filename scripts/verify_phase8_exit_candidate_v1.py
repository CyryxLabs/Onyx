"""Reproduce the aggregate Phase 8 Exit Candidate V1."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
BASE = PROJECT / "docs/onyx/checkpoints/phase8-exit-candidate-v1"
MANIFEST = BASE / "manifest.json"
COVERAGE = BASE / "coverage-map.json"
SELECTION = BASE / "cumulative-selection.json"
MARKER = "P8_EXIT_CANDIDATE_V1_OK"
ARTIFACTS = (
    "scripts/verify_phase8_exit_candidate_v1.py",
    "docs/onyx/adrs/ADR-0044-phase8-exit-candidate-v1.md",
    "docs/onyx/checkpoints/phase8-exit-candidate-v1/PHASE8_EXIT_CANDIDATE_V1_CHECKPOINT.md",
    "docs/onyx/checkpoints/phase8-exit-candidate-v1/coverage-map.json",
    "docs/onyx/checkpoints/phase8-exit-candidate-v1/cumulative-selection.json",
)


def _tuple(slug: str, acceptance_id: str) -> tuple[str, str, str, str]:
    return (
        f"docs/onyx/checkpoints/phase8-microsoft-graph-{slug}-v1/manifest.json",
        f"docs/onyx/acceptance/{acceptance_id}.md",
        f"docs/onyx/acceptance/{acceptance_id}.manifest.json",
        f"docs/onyx/VE-ACCEPTANCE-{acceptance_id[3:]}.sha256",
    )


ACCEPTANCE_IDS = {
    "oauth": "VE-P8-MICROSOFT-GRAPH-OAUTH-V1-E6-001",
    "read": "VE-P8-MICROSOFT-GRAPH-READ-V1-E6-001",
    "live_read_e2e": "VE-P8-MICROSOFT-GRAPH-LIVE-READ-E2E-V1-E6-001",
    "calendar": "VE-P8-MICROSOFT-GRAPH-CALENDAR-V1-E6-001",
    "mail": "VE-P8-MICROSOFT-GRAPH-MAIL-V1-E6-001",
    "tasks": "VE-P8-MICROSOFT-GRAPH-TASKS-V1-E6-001",
    "drive": "VE-P8-MICROSOFT-GRAPH-DRIVE-V1-E6-001",
}
_SLUGS = {"live_read_e2e": "live-read-e2e"}
ROOT_PATHS = {
    slice_key: _tuple(_SLUGS.get(slice_key, slice_key), acceptance_id)
    for slice_key, acceptance_id in ACCEPTANCE_IDS.items()
}
# Each Phase 8 PRD connector requirement -> the accepted slice that satisfies it.
REQUIREMENT_SLICE = {
    "oauth_delegated_least_scope": "oauth",
    "graph_read_brief_paging": "read",
    "live_read_e2e_contract": "live_read_e2e",
    "calendar_availability_and_exact_grant_create": "calendar",
    "mail_content_bound_draft_and_send": "mail",
    "tasks_and_notifications": "tasks",
    "drive_metadata_read": "drive",
}


class VerificationError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise VerificationError("JSON object required")
    return value


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise VerificationError("artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(values: dict[str, str]) -> str:
    return hashlib.sha256(
        "".join(
            sorted(f"{path}\0{digest}\n" for path, digest in values.items())
        ).encode()
    ).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    manifest, coverage, selection = _json(MANIFEST), _json(COVERAGE), _json(SELECTION)
    claims = coverage.get("claims")
    if (
        manifest.get("schema") != "onyx.phase8.exit-candidate.v1"
        or manifest.get("status") != "candidate_e1_e5_e6_pending"
        or coverage.get("phase") != 8
        or type(claims) is not dict
        or claims.get("phase8_connector_layer_default_off_implementation_complete")
        is not True
        or claims.get("one_provider_proven_before_generalizing") is not True
        or claims.get("live_wiring") is not False
        or claims.get("live_e2e_bound_in_aggregate") is not False
        or claims.get("phase9_started") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise VerificationError("exit identity or claim drift")

    # The requirement->evidence mapping is the reason this aggregate exists, so
    # it is machine-enforced: every accepted slice has exactly one requirement,
    # and each requirement cites exactly its slice's accepted VE identifier.
    expected_requirements = {
        requirement: [ACCEPTANCE_IDS[slice_key]]
        for requirement, slice_key in REQUIREMENT_SLICE.items()
    }
    if coverage.get("requirements") != expected_requirements:
        raise VerificationError("requirement to evidence mapping drift")
    if {slice_key for slice_key in REQUIREMENT_SLICE.values()} != set(ROOT_PATHS):
        raise VerificationError("requirement slice coverage drift")

    accepted = coverage.get("accepted_roots")
    if type(accepted) is not dict or len(accepted) != len(ROOT_PATHS):
        raise VerificationError("accepted roots unavailable")
    root_files = 0
    for name, paths in ROOT_PATHS.items():
        if accepted.get(name) != [_digest(PROJECT / path) for path in paths]:
            raise VerificationError(f"accepted root drift: {name}")
        root_files += len(paths)
    if manifest.get("accepted_component_roots") != root_files:
        raise VerificationError("accepted-root count drift")

    records: dict[str, str] = {}
    artifacts = manifest.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != len(ARTIFACTS):
        raise VerificationError("artifact closure drift")
    for expected_path, item in zip(ARTIFACTS, artifacts, strict=True):
        path = PROJECT / expected_path
        digest = _digest(path)
        if type(item) is not dict or item != {
            "path": expected_path,
            "bytes": path.stat().st_size,
            "sha256": digest,
        }:
            raise VerificationError("artifact hash drift")
        records[expected_path] = digest
    if manifest.get("artifact_root_sha256") != _root(records):
        raise VerificationError("artifact root drift")

    expected = {
        "test_files": 20,
        "passed": 421,
        "failed": 0,
        "errors": 0,
        "skipped": 8,
        "subtests_passed": 80,
    }
    tests = selection.get("tests")
    if (
        selection.get("expected") != expected
        or manifest.get("verification") != expected
        or type(tests) is not list
        or len(tests) != 20
    ):
        raise VerificationError("selection drift")
    if (
        sum(item["passed"] for item in tests) != expected["passed"]
        or sum(item["skipped"] for item in tests) != expected["skipped"]
        or sum(item["subtests_passed"] for item in tests) != expected["subtests_passed"]
    ):
        raise VerificationError("selection per-file sum drift")
    if run_tests:
        temporary = (
            PROJECT
            / "runtime/test-tmp/phase8-exit-v1-verify"
            / f"run-{secrets.token_hex(8)}"
        )
        temporary.mkdir(parents=True, exist_ok=True)
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
                    str(temporary / str(index)),
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
            if (
                process.returncode
                or passed is None
                or int(passed.group(1)) != item["passed"]
                or (int(skipped.group(1)) if skipped else 0) != item["skipped"]
                or (int(subtests.group(1)) if subtests else 0)
                != item["subtests_passed"]
            ):
                raise VerificationError(
                    f"selection failed: {item['path']}\n"
                    f"{process.stdout}\n{process.stderr}"
                )
    return {
        "candidate": "phase8-exit-candidate-v1",
        "artifact_root_sha256": manifest["artifact_root_sha256"],
        "accepted_component_roots": root_files,
        "results": expected,
        "marker": MARKER,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-tests", action="store_true")
    result = verify(run_tests=not parser.parse_args().no_tests)
    print(json.dumps(result, sort_keys=True))
    print(MARKER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
