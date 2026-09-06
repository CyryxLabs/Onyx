"""Verify the external E6 acceptance for the frozen Capability Nexus V32."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-P53-CAPABILITY-NEXUS-V32-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P53-CAPABILITY-NEXUS-V32-E6-001.sha256"
ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V32-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V32-001.sha256"
BUNDLE = "docs/onyx/checkpoints/phase5-capability-nexus-v32/phase5-capability-nexus-v32.bundle.json"
V31_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V31-001.sha256"
V31_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V31-001.sha256"
CAPABILITY_MATRIX = "docs/onyx/CAPABILITY_MATRIX.md"
VERIFICATION_EVIDENCE = "docs/onyx/VERIFICATION_EVIDENCE.md"
PARENT = "scripts/verify_phase5_capability_nexus_v32.py"

ROOT_SHA256 = "86cc174fb212f51c56b59cb9043c8cb59e765307eea2c32a7a44857f6112bfa3"
ARTIFACT_SHA256 = "3d32ebf989f198534377d35c0ffc8c1f3abf10c8aa001f24406c355bafff0249"
BUNDLE_SHA256 = "84ffc850a14782ae3f4182973acc50a2765df7f6143977a81daf5423c6706c6f"
V31_ROOT_SHA256 = "1fe65cb6c5e238c7b1066c72dbcab9d5967e3c8fc9d9055aa56cc30d0e4b888d"
V31_ARTIFACT_SHA256 = "e332c904fac7fe9f53cd976210637fbb1a3b8aa74d55e828c95aa9ca448bc3ed"
PARENT_MARKER = "P53_CAPABILITY_NEXUS_V32_EVIDENCE_OK"
ACCEPTANCE_MARKER = "P53_CAPABILITY_NEXUS_V32_ACCEPTANCE_OK"
_REPARSE_ATTRIBUTE = 0x400


class CapabilityNexusV32AcceptanceError(RuntimeError):
    """The external acceptance or one of its immutable anchors is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative:
        raise CapabilityNexusV32AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(part in {"", ".", ".."} for part in parsed.parts):
        raise CapabilityNexusV32AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    current = root
    for index, part in enumerate(parts):
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise CapabilityNexusV32AcceptanceError(f"acceptance path is unavailable: {relative}") from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or attributes & _REPARSE_ATTRIBUTE:
            raise CapabilityNexusV32AcceptanceError(f"acceptance path uses a link/reparse point: {relative}")
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise CapabilityNexusV32AcceptanceError(f"acceptance ancestor is not a directory: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise CapabilityNexusV32AcceptanceError(f"acceptance leaf is not a regular file: {relative}")
    return current


def _bytes(project: Path, relative: str) -> bytes:
    try:
        return _regular_path(project, relative).read_bytes()
    except OSError as exc:
        raise CapabilityNexusV32AcceptanceError(f"cannot read acceptance path: {relative}") from exc


def _text(project: Path, relative: str) -> str:
    raw = _bytes(project, relative)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CapabilityNexusV32AcceptanceError(f"acceptance text is not UTF-8: {relative}") from exc
    if "\r" in text or not text.endswith("\n"):
        raise CapabilityNexusV32AcceptanceError(f"acceptance text is not canonical LF: {relative}")
    return text


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    actual = _digest(project, relative)
    if actual != expected:
        raise CapabilityNexusV32AcceptanceError(
            f"acceptance anchor drifted: {relative}: expected {expected}, got {actual}"
        )


def _manifest_line(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if len(lines) != 1:
        raise CapabilityNexusV32AcceptanceError("acceptance manifest must contain exactly one record")
    line = lines[0]
    if len(line) < 67 or line[64:66] != "  ":
        raise CapabilityNexusV32AcceptanceError("acceptance manifest record is malformed")
    digest, relative = line[:64], line[66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise CapabilityNexusV32AcceptanceError("acceptance manifest digest is malformed")
    _canonical_relative(relative)
    return digest, relative


def _verify_record(project: Path) -> str:
    manifest_digest, manifest_path = _manifest_line(_text(project, ACCEPTANCE_MANIFEST))
    if manifest_path != ACCEPTANCE_RECORD:
        raise CapabilityNexusV32AcceptanceError("acceptance manifest points to an unexpected record")
    record_digest = _digest(project, ACCEPTANCE_RECORD)
    if record_digest != manifest_digest:
        raise CapabilityNexusV32AcceptanceError("external acceptance record does not match its manifest")
    record = _text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED — Phase 5.3 only, default-off/shadow-only implementation handoff",
        ROOT_SHA256,
        ARTIFACT_SHA256,
        BUNDLE_SHA256,
        "P0=0, P1=0, P2=0",
        "stable-filesystem-state metadata precheck",
        "concurrent-writer/TOCTOU security boundary",
        "300-second deadline applies only to the offline evidence verifier",
        "P3 maintainability advisory",
        "complete Phase 5 exit",
    )
    missing = [value for value in required if value not in record]
    if missing:
        raise CapabilityNexusV32AcceptanceError(f"acceptance record is missing required binding: {missing[0]}")
    return record_digest


def _verify_candidate_anchors(project: Path) -> None:
    _require_digest(project, ROOT_MANIFEST, ROOT_SHA256)
    _require_digest(project, ARTIFACT_MANIFEST, ARTIFACT_SHA256)
    _require_digest(project, BUNDLE, BUNDLE_SHA256)
    _require_digest(project, V31_ROOT_MANIFEST, V31_ROOT_SHA256)
    _require_digest(project, V31_ARTIFACT_MANIFEST, V31_ARTIFACT_SHA256)

    root = _text(project, ROOT_MANIFEST)
    if root != f"{ARTIFACT_SHA256}  {ARTIFACT_MANIFEST}\n":
        raise CapabilityNexusV32AcceptanceError("V32 root manifest does not bind the exact artifact manifest")
    artifacts = _text(project, ARTIFACT_MANIFEST)
    if f"{BUNDLE_SHA256}  {BUNDLE}\n" not in artifacts:
        raise CapabilityNexusV32AcceptanceError("V32 artifact manifest does not bind the exact bundle")
    forbidden = (
        CAPABILITY_MATRIX,
        VERIFICATION_EVIDENCE,
        ACCEPTANCE_RECORD,
        ACCEPTANCE_MANIFEST,
        "scripts/verify_phase5_capability_nexus_v32_acceptance.py",
        "tests/test_capability_nexus_v32_acceptance.py",
    )
    if any(value in artifacts for value in forbidden):
        raise CapabilityNexusV32AcceptanceError("mutable/external acceptance path entered the frozen V32 DAG")


def _verify_projections(project: Path) -> None:
    matrix = _text(project, CAPABILITY_MATRIX)
    evidence = _text(project, VERIFICATION_EVIDENCE)
    for label, value in (("capability matrix", matrix), ("verification evidence", evidence)):
        if ACCEPTANCE_ID not in value or ROOT_SHA256 not in value:
            raise CapabilityNexusV32AcceptanceError(f"{label} does not project the exact V32 acceptance")
    if "Phase 5 remains incomplete" not in matrix or "Phase 5 remains incomplete" not in evidence:
        raise CapabilityNexusV32AcceptanceError("mutable projections overstate Phase 5 completion")


def _run_parent(project: Path) -> dict[str, object]:
    parent = _regular_path(project, PARENT)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, str(parent)],
            cwd=project,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=310,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CapabilityNexusV32AcceptanceError("V32 parent verifier could not complete") from exc
    if completed.returncode != 0 or completed.stderr:
        raise CapabilityNexusV32AcceptanceError("V32 parent verifier failed after projection update")
    lines = completed.stdout.splitlines()
    prefix = PARENT_MARKER + " "
    if len(lines) != 1 or not lines[0].startswith(prefix):
        raise CapabilityNexusV32AcceptanceError("V32 parent marker is missing or contaminated")
    try:
        payload = json.loads(lines[0][len(prefix) :])
    except json.JSONDecodeError as exc:
        raise CapabilityNexusV32AcceptanceError("V32 parent marker payload is invalid") from exc
    expected = {
        "artifacts": 496,
        "focused_passed": 2021,
        "live_scan_files": 111,
        "root_sha256": ROOT_SHA256,
    }
    if payload != expected:
        raise CapabilityNexusV32AcceptanceError("V32 parent marker does not match the accepted candidate")
    return payload


def verify(project: Path = PROJECT, *, run_parent: bool = True) -> dict[str, object]:
    project = Path(project)
    record_sha256 = _verify_record(project)
    _verify_candidate_anchors(project)
    _verify_projections(project)
    parent = _run_parent(project) if run_parent else None
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "record_sha256": record_sha256,
        "root_sha256": ROOT_SHA256,
        "artifact_sha256": ARTIFACT_SHA256,
        "bundle_sha256": BUNDLE_SHA256,
        "parent": parent,
        "scope": "phase5.3-default-off-shadow-only-handoff",
    }


def main() -> int:
    print(ACCEPTANCE_MARKER + " " + json.dumps(verify(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
