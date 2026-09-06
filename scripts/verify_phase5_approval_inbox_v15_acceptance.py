"""Verify the external E6 acceptance for the frozen Approval Inbox V15."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-P52-APPROVAL-INBOX-V15-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P52-APPROVAL-INBOX-V15-E6-001.sha256"
ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V15-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V15-001.sha256"
BUNDLE = "docs/onyx/checkpoints/phase5-approval-inbox-v15/phase5-approval-inbox-v15.bundle.json"
V14_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V14-001.sha256"
V14_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V14-001.sha256"
CAPABILITY_MATRIX = "docs/onyx/CAPABILITY_MATRIX.md"
VERIFICATION_EVIDENCE = "docs/onyx/VERIFICATION_EVIDENCE.md"
PARENT_WORKER = "scripts/verify_phase5_approval_inbox_v15_worker.py"

ROOT_SHA256 = "279052fbcaf3018f7fee6733e063e94c67e90e7ce62a2a2cdc7742b55470631f"
ARTIFACT_SHA256 = "a1a0f27d0f4edc370b7470a3b7e788cf87fb62cf398eab6b5532a1fb97ff60e0"
BUNDLE_SHA256 = "7334f3abb8345754eb1c027af5139023f3a624d4f4bfe52ad45f004442540734"
V14_ROOT_SHA256 = "fdf6139e1e9a82edf7cb8f853ad59ffd88173bdef5fae4a1a25af3a5b0a427c9"
V14_ARTIFACT_SHA256 = "88dd035f18f5975f8dea3882b31e0dab79082e68ce99fe53c4a05dc5431336f8"
PARENT_MARKER = "P52_APPROVAL_INBOX_V15_MANIFEST_OK"
ACCEPTANCE_MARKER = "P52_APPROVAL_INBOX_V15_ACCEPTANCE_OK"
_REPARSE_ATTRIBUTE = 0x400


class ApprovalInboxV15AcceptanceError(RuntimeError):
    """The external acceptance or one of its immutable anchors is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise ApprovalInboxV15AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise ApprovalInboxV15AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ApprovalInboxV15AcceptanceError("acceptance root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or root_resolved != root
    ):
        raise ApprovalInboxV15AcceptanceError("acceptance root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise ApprovalInboxV15AcceptanceError(
                f"acceptance ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise ApprovalInboxV15AcceptanceError(
                f"acceptance path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise ApprovalInboxV15AcceptanceError(
                f"acceptance path is unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & _REPARSE_ATTRIBUTE:
            raise ApprovalInboxV15AcceptanceError(
                f"acceptance path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise ApprovalInboxV15AcceptanceError(
                f"acceptance path leaves the project: {relative}"
            ) from exc
        if resolved.name != part:
            raise ApprovalInboxV15AcceptanceError(
                f"acceptance path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ApprovalInboxV15AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ApprovalInboxV15AcceptanceError(
            f"acceptance leaf is not a regular file: {relative}"
        )
    return current


def _bytes(project: Path, relative: str) -> bytes:
    try:
        return _regular_path(project, relative).read_bytes()
    except OSError as exc:
        raise ApprovalInboxV15AcceptanceError(
            f"cannot read acceptance path: {relative}"
        ) from exc


def _text(project: Path, relative: str) -> str:
    raw = _bytes(project, relative)
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApprovalInboxV15AcceptanceError(
            f"acceptance text is not UTF-8: {relative}"
        ) from exc
    if "\r" in value or not value.endswith("\n"):
        raise ApprovalInboxV15AcceptanceError(
            f"acceptance text is not canonical LF: {relative}"
        )
    return value


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    actual = _digest(project, relative)
    if actual != expected:
        raise ApprovalInboxV15AcceptanceError(
            f"acceptance anchor drifted: {relative}: expected {expected}, got {actual}"
        )


def _manifest_line(value: str) -> tuple[str, str]:
    lines = value.splitlines()
    if len(lines) != 1:
        raise ApprovalInboxV15AcceptanceError(
            "acceptance manifest must contain exactly one record"
        )
    line = lines[0]
    if len(line) < 67 or line[64:66] != "  ":
        raise ApprovalInboxV15AcceptanceError("acceptance manifest record is malformed")
    digest, relative = line[:64], line[66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise ApprovalInboxV15AcceptanceError("acceptance manifest digest is malformed")
    _canonical_relative(relative)
    return digest, relative


def _verify_record(project: Path) -> str:
    manifest_digest, manifest_path = _manifest_line(
        _text(project, ACCEPTANCE_MANIFEST)
    )
    if manifest_path != ACCEPTANCE_RECORD:
        raise ApprovalInboxV15AcceptanceError(
            "acceptance manifest points to an unexpected record"
        )
    record_digest = _digest(project, ACCEPTANCE_RECORD)
    if record_digest != manifest_digest:
        raise ApprovalInboxV15AcceptanceError(
            "external acceptance record does not match its manifest"
        )
    record = _text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED — Phase 5.2 only, default-off/read-only/non-authority implementation handoff",
        ROOT_SHA256,
        ARTIFACT_SHA256,
        BUNDLE_SHA256,
        "P0=0, P1=0, P2=0",
        "forced external\ninterruption",
        "approximately 479 MiB",
        "fixed 26-path live-surface scan",
        "concurrent-writer/TOCTOU\nsecurity boundary",
        "Phase 5 Runtime Core",
        "completion of the Onyx project or PRD",
    )
    missing = [item for item in required if item not in record]
    if missing:
        raise ApprovalInboxV15AcceptanceError(
            f"acceptance record is missing required binding: {missing[0]}"
        )
    return record_digest


def _verify_candidate_anchors(project: Path) -> None:
    _require_digest(project, ROOT_MANIFEST, ROOT_SHA256)
    _require_digest(project, ARTIFACT_MANIFEST, ARTIFACT_SHA256)
    _require_digest(project, BUNDLE, BUNDLE_SHA256)
    _require_digest(project, V14_ROOT_MANIFEST, V14_ROOT_SHA256)
    _require_digest(project, V14_ARTIFACT_MANIFEST, V14_ARTIFACT_SHA256)

    root = _text(project, ROOT_MANIFEST)
    if root != f"{ARTIFACT_SHA256}  {ARTIFACT_MANIFEST}\n":
        raise ApprovalInboxV15AcceptanceError(
            "V15 root manifest does not bind the exact artifact manifest"
        )
    artifacts = _text(project, ARTIFACT_MANIFEST)
    if f"{BUNDLE_SHA256}  {BUNDLE}\n" not in artifacts:
        raise ApprovalInboxV15AcceptanceError(
            "V15 artifact manifest does not bind the exact bundle"
        )
    forbidden = (
        CAPABILITY_MATRIX,
        VERIFICATION_EVIDENCE,
        ACCEPTANCE_RECORD,
        ACCEPTANCE_MANIFEST,
        "scripts/verify_phase5_approval_inbox_v15_acceptance.py",
        "tests/test_approval_inbox_v15_acceptance.py",
    )
    if any(relative in artifacts for relative in forbidden):
        raise ApprovalInboxV15AcceptanceError(
            "mutable/external acceptance path entered the frozen V15 DAG"
        )


def _verify_projections(project: Path) -> None:
    matrix = _text(project, CAPABILITY_MATRIX)
    evidence = _text(project, VERIFICATION_EVIDENCE)
    for label, value in (("capability matrix", matrix), ("verification evidence", evidence)):
        if ACCEPTANCE_ID not in value or ROOT_SHA256 not in value:
            raise ApprovalInboxV15AcceptanceError(
                f"{label} does not project the exact V15 acceptance"
            )
    if "Phase 5 remains incomplete" not in matrix or "Phase 5 remains incomplete" not in evidence:
        raise ApprovalInboxV15AcceptanceError(
            "mutable projections overstate Phase 5 completion"
        )


def _run_manifest_parent(project: Path) -> dict[str, object]:
    bundle = json.loads(_text(project, BUNDLE))
    executable = bundle.get("environment", {}).get("executable")
    if type(executable) is not str or not Path(executable).is_absolute():
        raise ApprovalInboxV15AcceptanceError(
            "V15 bundle does not bind an absolute reviewed Python executable"
        )
    worker = _regular_path(project, PARENT_WORKER)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [executable, "-I", "-S", "-B", str(worker), "--manifest-only"],
            cwd=project,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ApprovalInboxV15AcceptanceError(
            "V15 proportional parent verifier could not complete"
        ) from exc
    if completed.returncode != 0 or completed.stderr:
        raise ApprovalInboxV15AcceptanceError(
            "V15 proportional parent verifier failed after projection update"
        )
    expected = (
        f"{PARENT_MARKER} artifacts=142 live_files=26 root={ROOT_SHA256}"
    )
    lines = completed.stdout.splitlines()
    if lines != [expected]:
        raise ApprovalInboxV15AcceptanceError(
            "V15 proportional parent marker does not match the accepted candidate"
        )
    return {
        "artifacts": 142,
        "live_scan_files": 26,
        "root_sha256": ROOT_SHA256,
    }


def verify(project: Path = PROJECT, *, run_parent: bool = True) -> dict[str, object]:
    project = Path(project)
    record_sha256 = _verify_record(project)
    _verify_candidate_anchors(project)
    _verify_projections(project)
    parent = _run_manifest_parent(project) if run_parent else None
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "record_sha256": record_sha256,
        "root_sha256": ROOT_SHA256,
        "artifact_sha256": ARTIFACT_SHA256,
        "bundle_sha256": BUNDLE_SHA256,
        "parent": parent,
        "scope": "phase5.2-default-off-read-only-non-authority-handoff",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-parent", action="store_true")
    arguments = parser.parse_args()
    payload = verify(run_parent=not arguments.no_parent)
    print(ACCEPTANCE_MARKER + " " + json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
