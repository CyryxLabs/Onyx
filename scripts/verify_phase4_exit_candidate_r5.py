"""Verify the evidence-only Phase 4 E1-E5 R5 successor.

Trust flows from an external E6 registration of the R5 source-manifest digest
to that manifest, then to the R5 artifact manifest and finally to the bundle
and reused R4 outputs.  This verifier never creates an external registration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts import verify_p44_scope_r11 as r11


R11_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P44-R11-001.sha256"
R5_SOURCE_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P4-E1E5-R5-001.sha256"
R5_ARTIFACT_MANIFEST = PROJECT / "docs/onyx/VE-ARTIFACTS-P4-E1E5-R5-001.sha256"
R5_SOURCE_PATHS = frozenset(
    {
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VE-ARTIFACTS-P4-E1E5-R5-001.sha256",
        "docs/onyx/VE-SCOPE-P44-R11-001.sha256",
        "docs/onyx/checkpoints/phase4-e1-e5/PHASE4_E1_E5_CHECKPOINT_R5.md",
        "scripts/verify_phase4_exit_candidate_r4.py",
        "scripts/verify_phase4_exit_candidate_r5.py",
        "tests/phase4_e1e5_r4_selection.txt",
        "tests/test_phase4_exit_candidate_r4.py",
        "tests/test_phase4_exit_candidate_r5.py",
    }
)
R5_ARTIFACT_PATHS = frozenset(
    {
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-e1-e5-r5.bundle.json",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r4-pytest.log",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r4-safety.junit.xml",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r4-source.json",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r4-static.log",
    }
)
_LINE = re.compile(r"([0-9a-f]{64}) \*([^\r\n]+)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_records(manifest: Path) -> dict[str, str]:
    raw = manifest.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise RuntimeError("manifest encoding/newlines are not canonical")
    records: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        match = _LINE.fullmatch(line)
        if match is None or match.group(2) in records:
            raise RuntimeError("manifest line is malformed or duplicated")
        records[match.group(2)] = match.group(1)
    if list(records) != sorted(records):
        raise RuntimeError("manifest paths are not ordinally sorted")
    return records


def verify_manifest_at(
    root: Path, manifest: Path, expected_paths: frozenset[str]
) -> tuple[int, str]:
    records = manifest_records(manifest)
    if set(records) != set(expected_paths):
        missing = sorted(set(expected_paths) - set(records))
        extra = sorted(set(records) - set(expected_paths))
        raise RuntimeError(f"manifest path mismatch: missing={missing}, extra={extra}")
    for relative, expected in records.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"manifest digest mismatch: {relative}")
    return len(records), sha256(manifest)


def verify_two_level_dag(
    *,
    root: Path,
    source_manifest: Path,
    source_paths: frozenset[str],
    artifact_manifest: Path,
    artifact_paths: frozenset[str],
    external_source_sha256: str | None = None,
) -> dict[str, object]:
    actual_source_sha = sha256(source_manifest)
    if external_source_sha256 is not None and external_source_sha256 != actual_source_sha:
        raise RuntimeError("external source-manifest anchor mismatch")
    source_count, _ = verify_manifest_at(root, source_manifest, source_paths)
    artifact_count, _ = verify_manifest_at(root, artifact_manifest, artifact_paths)
    return {
        "source_manifest_files": source_count,
        "artifact_manifest_files": artifact_count,
        "source_manifest_sha256": actual_source_sha,
        "external_source_anchor_verified": external_source_sha256 is not None,
    }


def _verify_bundle_contract() -> dict[str, object]:
    bundle_path = PROJECT / "docs/onyx/checkpoints/phase4-e1-e5/phase4-e1-e5-r5.bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    dag = bundle["manifest_dag"]
    if bundle["e6_accepted"] or bundle["activation"] or bundle["phase5_unlocked"]:
        raise RuntimeError("R5 bundle cannot activate or accept itself")
    if dag["external_source_anchor_present"]:
        raise RuntimeError("R5 bundle cannot claim an absent external anchor")
    forbidden = {
        "bundle_sha256",
        "source_manifest_sha256",
        "artifact_manifest_sha256",
        "evidence_manifest_sha256",
    }
    if forbidden & set(dag):
        raise RuntimeError("R5 bundle claims a manifest or self hash")
    if dag["external_registration_must_store"] != "source_manifest_sha256":
        raise RuntimeError("R5 external anchor targets the wrong manifest")
    return {"evidence_id": bundle["evidence_id"], "e6_accepted": False}


def verify_frozen() -> dict[str, object]:
    r11_count, r11_sha = r11.verify(R11_MANIFEST)
    dag = verify_two_level_dag(
        root=PROJECT,
        source_manifest=R5_SOURCE_MANIFEST,
        source_paths=R5_SOURCE_PATHS,
        artifact_manifest=R5_ARTIFACT_MANIFEST,
        artifact_paths=R5_ARTIFACT_PATHS,
    )
    return {
        "activation": False,
        "bundle": _verify_bundle_contract(),
        "dag": dag,
        "e6_accepted": False,
        "external_source_anchor_present": False,
        "phase5_unlocked": False,
        "r11_files": r11_count,
        "r11_manifest_sha256": r11_sha,
        "reused_r4_junit_tests": 73,
        "status": "P4_EXIT_CANDIDATE_R5_FROZEN_OK",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_frozen()
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output is not None:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
