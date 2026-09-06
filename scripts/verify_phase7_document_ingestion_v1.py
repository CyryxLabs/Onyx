"""Reproduce the Phase 7 Document Ingestion V1 candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from core import phase7_document_ingestion_v1 as candidate  # noqa: E402

MANIFEST = PROJECT / "docs/onyx/checkpoints/phase7-document-ingestion-v1/manifest.json"
SELECTION = (
    PROJECT
    / "docs/onyx/checkpoints/phase7-document-ingestion-v1/cumulative-selection.json"
)
MARKER = "P7_DOCUMENT_INGESTION_V1_OK"
ARTIFACT_PATHS = (
    "core/phase7_document_ingestion_v1.py",
    "tests/test_phase7_document_ingestion_v1.py",
    "requirements.txt",
    "scripts/verify_phase7_document_ingestion_v1.py",
    "docs/onyx/adrs/ADR-0034-phase7-document-ingestion-v1.md",
    "docs/onyx/checkpoints/phase7-document-ingestion-v1/PHASE7_DOCUMENT_INGESTION_V1_CHECKPOINT.md",
    "docs/onyx/checkpoints/phase7-document-ingestion-v1/CAPABILITY_DELTA_SNAPSHOT.md",
    "docs/onyx/checkpoints/phase7-document-ingestion-v1/cumulative-selection.json",
)


class VerificationError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise VerificationError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if type(value) is not dict:
        raise VerificationError("JSON object required")
    return value


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise VerificationError("artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(records: dict[str, str]) -> str:
    return hashlib.sha256(
        "".join(
            sorted(f"{path}\0{digest}\n" for path, digest in records.items())
        ).encode()
    ).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    manifest = _json(MANIFEST)
    if (
        manifest.get("schema") != "onyx.phase7.document-ingestion.v1"
        or manifest.get("candidate") != "phase7-document-ingestion-v1"
        or manifest.get("feature_flag") != candidate.FEATURE_FLAG
        or manifest.get("default_off") is not True
        or manifest.get("status") != "candidate_e1_e5_e6_pending"
    ):
        raise VerificationError("manifest identity drift")
    artifacts = manifest.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != len(ARTIFACT_PATHS):
        raise VerificationError("artifact closure drift")
    observed: dict[str, str] = {}
    for expected_path, item in zip(ARTIFACT_PATHS, artifacts, strict=True):
        if type(item) is not dict or item.get("path") != expected_path:
            raise VerificationError("artifact order drift")
        path = PROJECT / expected_path
        digest = _digest(path)
        if item.get("sha256") != digest or item.get("bytes") != path.stat().st_size:
            raise VerificationError("artifact hash drift")
        observed[expected_path] = digest
    if manifest.get("artifact_root_sha256") != _root(observed):
        raise VerificationError("artifact root drift")
    candidate._verify_entries(PROJECT)
    if (
        candidate.create_governed_document_ingestor_v1(
            gate=candidate.DocumentIngestionFeatureGateV1(False),
            project_root=PROJECT / "missing",
        )
        is not None
    ):
        raise VerificationError("default-off factory constructed")
    source = (PROJECT / "core/phase7_document_ingestion_v1.py").read_text(
        encoding="utf-8"
    )
    for required in (
        '"application/pdf"',
        '"docx"',
        '"spreadsheet"',
        '"presentation"',
        '"ocr_block"',
        "compare_versions",
        "statement grounding drift",
        '"untrusted_data"',
        "instructions_authority",
    ):
        if required not in source:
            raise VerificationError("source invariant drift")
    for forbidden in (
        "import requests",
        "import socket",
        "import subprocess",
        "genai.Client",
        "dispatch(",
    ):
        if forbidden in source:
            raise VerificationError("side-effect invariant drift")
    selection = _json(SELECTION)
    expected = {
        "test_files": 10,
        "passed": 178,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
        "subtests_passed": 77,
    }
    tests = selection.get("tests")
    if (
        selection.get("expected") != expected
        or type(tests) is not list
        or len(tests) != 10
    ):
        raise VerificationError("selection drift")
    if run_tests:
        temporary = PROJECT / "runtime/test-tmp/phase7-document-ingestion-v1-verify"
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
        "candidate": manifest["candidate"],
        "artifact_root_sha256": manifest["artifact_root_sha256"],
        "artifacts": len(artifacts),
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
