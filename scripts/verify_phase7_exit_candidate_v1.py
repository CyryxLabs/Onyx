"""Reproduce the aggregate Phase 7 Exit Candidate V1."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT / "docs/onyx/checkpoints/phase7-exit-candidate-v1/manifest.json"
COVERAGE = PROJECT / "docs/onyx/checkpoints/phase7-exit-candidate-v1/coverage-map.json"
SELECTION = (
    PROJECT / "docs/onyx/checkpoints/phase7-exit-candidate-v1/cumulative-selection.json"
)
MARKER = "P7_EXIT_CANDIDATE_V1_OK"
ARTIFACTS = (
    "scripts/verify_phase7_exit_candidate_v1.py",
    "docs/onyx/adrs/ADR-0035-phase7-exit-candidate-v1.md",
    "docs/onyx/checkpoints/phase7-exit-candidate-v1/PHASE7_EXIT_CANDIDATE_V1_CHECKPOINT.md",
    "docs/onyx/checkpoints/phase7-exit-candidate-v1/coverage-map.json",
    "docs/onyx/checkpoints/phase7-exit-candidate-v1/cumulative-selection.json",
)
ROOT_PATHS = {
    "workspace_memory": (
        "docs/onyx/checkpoints/phase7-workspace-memory-v1/manifest.json",
        "docs/onyx/acceptance/VE-P7-WORKSPACE-MEMORY-V1-E6-001.md",
        "docs/onyx/acceptance/VE-P7-WORKSPACE-MEMORY-V1-E6-001.manifest.json",
        "docs/onyx/VE-ACCEPTANCE-P7-WORKSPACE-MEMORY-V1-E6-001.sha256",
    ),
    "workspace_aliases": (
        "docs/onyx/checkpoints/phase7-workspace-aliases-v1/manifest.json",
        "docs/onyx/acceptance/VE-P7-WORKSPACE-ALIASES-V1-E6-001.md",
        "docs/onyx/acceptance/VE-P7-WORKSPACE-ALIASES-V1-E6-001.manifest.json",
        "docs/onyx/VE-ACCEPTANCE-P7-WORKSPACE-ALIASES-V1-E6-001.sha256",
    ),
    "approved_sources_company_graph": (
        "docs/onyx/checkpoints/phase7-approved-sources-company-graph-v1/manifest.json",
        "docs/onyx/acceptance/VE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001.md",
        "docs/onyx/acceptance/VE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001.manifest.json",
        "docs/onyx/VE-ACCEPTANCE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001.sha256",
    ),
    "founder_command": (
        "docs/onyx/checkpoints/phase7-founder-command-v1/manifest.json",
        "docs/onyx/acceptance/VE-P7-FOUNDER-COMMAND-V1-E6-001.md",
        "docs/onyx/acceptance/VE-P7-FOUNDER-COMMAND-V1-E6-001.manifest.json",
        "docs/onyx/VE-ACCEPTANCE-P7-FOUNDER-COMMAND-V1-E6-001.sha256",
    ),
    "layered_memory": (
        "docs/onyx/checkpoints/phase7-layered-memory-v1/manifest.json",
        "docs/onyx/acceptance/VE-P7-LAYERED-MEMORY-V1-E6-001.md",
        "docs/onyx/acceptance/VE-P7-LAYERED-MEMORY-V1-E6-001.manifest.json",
        "docs/onyx/VE-ACCEPTANCE-P7-LAYERED-MEMORY-V1-E6-001.sha256",
    ),
    "document_ingestion": (
        "docs/onyx/checkpoints/phase7-document-ingestion-v1/manifest.json",
        "docs/onyx/acceptance/VE-P7-DOCUMENT-INGESTION-V1-E6-001.md",
        "docs/onyx/acceptance/VE-P7-DOCUMENT-INGESTION-V1-E6-001.manifest.json",
        "docs/onyx/VE-ACCEPTANCE-P7-DOCUMENT-INGESTION-V1-E6-001.sha256",
    ),
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
    if (
        manifest.get("schema") != "onyx.phase7.exit-candidate.v1"
        or manifest.get("status") != "candidate_e1_e5_e6_pending"
        or coverage.get("phase") != 7
        or coverage.get("claims", {}).get("phase7_default_off_implementation_complete")
        is not True
        or coverage.get("claims", {}).get("full_onyx_prd_complete") is not False
    ):
        raise VerificationError("exit identity or claim drift")
    accepted = coverage.get("accepted_roots")
    if type(accepted) is not dict:
        raise VerificationError("accepted roots unavailable")
    for name, paths in ROOT_PATHS.items():
        if accepted.get(name) != [_digest(PROJECT / path) for path in paths]:
            raise VerificationError(f"accepted root drift: {name}")
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
        "test_files": 12,
        "passed": 240,
        "failed": 0,
        "errors": 0,
        "skipped": 8,
        "subtests_passed": 80,
    }
    tests = selection.get("tests")
    if (
        selection.get("expected") != expected
        or type(tests) is not list
        or len(tests) != 12
    ):
        raise VerificationError("selection drift")
    if run_tests:
        temporary = PROJECT / "runtime/test-tmp/phase7-exit-v1-verify"
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
                    f"selection failed: {item['path']}\n{process.stdout}\n{process.stderr}"
                )
    return {
        "candidate": "phase7-exit-candidate-v1",
        "artifact_root_sha256": manifest["artifact_root_sha256"],
        "accepted_roots": 24,
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
