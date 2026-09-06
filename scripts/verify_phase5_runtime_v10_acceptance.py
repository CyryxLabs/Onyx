"""Verify the external E6 acceptance for the frozen Runtime Core V10."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-P5-RUNTIME-V10-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P5-RUNTIME-V10-E6-001.sha256"
CORE = "core/phase5_runtime_v10.py"
TESTS = "tests/test_phase5_runtime_v10.py"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/phase5-runtime-v10/manifest.json"
CHECKPOINT = (
    "docs/onyx/checkpoints/phase5-runtime-v10/"
    "PHASE5_RUNTIME_V10_CHECKPOINT.md"
)
CAPABILITY_MATRIX = "docs/onyx/CAPABILITY_MATRIX.md"
VERIFICATION_EVIDENCE = "docs/onyx/VERIFICATION_EVIDENCE.md"

CORE_SHA256 = "f80fd636e145e669cc1ea76cfc024fcc5d385451cc1ef8624f7c9d8e0ac3f439"
TESTS_SHA256 = "b2a6d9524d2d5d1b85af3325462f7bd28793180cee0ea4295d6600750615cfff"
MANIFEST_SHA256 = "1cc83a994194b3ecb87bf43a91db4219cf480d48da7821e7057eb4e068ca01cb"
CHECKPOINT_SHA256 = "7f31d7ddda750f35c7b56e0af2e3569e068229f8a236e783936c28c2fff55f0d"
ACCEPTANCE_MARKER = "P5_RUNTIME_V10_ACCEPTANCE_OK"
_REPARSE_ATTRIBUTE = 0x400


class RuntimeV10AcceptanceError(RuntimeError):
    """The external acceptance or one of its immutable anchors is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise RuntimeV10AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise RuntimeV10AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeV10AcceptanceError("acceptance root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or root_resolved != root
    ):
        raise RuntimeV10AcceptanceError("acceptance root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise RuntimeV10AcceptanceError(
                f"acceptance ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise RuntimeV10AcceptanceError(
                f"acceptance path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise RuntimeV10AcceptanceError(
                f"acceptance path is unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & _REPARSE_ATTRIBUTE:
            raise RuntimeV10AcceptanceError(
                f"acceptance path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise RuntimeV10AcceptanceError(
                f"acceptance path leaves the project: {relative}"
            ) from exc
        if resolved.name != part:
            raise RuntimeV10AcceptanceError(
                f"acceptance path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeV10AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise RuntimeV10AcceptanceError(
            f"acceptance leaf is not a regular file: {relative}"
        )
    return current


def _bytes(project: Path, relative: str) -> bytes:
    try:
        return _regular_path(project, relative).read_bytes()
    except OSError as exc:
        raise RuntimeV10AcceptanceError(
            f"cannot read acceptance path: {relative}"
        ) from exc


def _text(project: Path, relative: str) -> str:
    raw = _bytes(project, relative)
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeV10AcceptanceError(
            f"acceptance text is not UTF-8: {relative}"
        ) from exc
    if "\r" in value or not value.endswith("\n"):
        raise RuntimeV10AcceptanceError(
            f"acceptance text is not canonical LF: {relative}"
        )
    return value


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    actual = _digest(project, relative)
    if actual != expected:
        raise RuntimeV10AcceptanceError(
            f"acceptance anchor drifted: {relative}: expected {expected}, got {actual}"
        )


def _manifest_line(value: str) -> tuple[str, str]:
    lines = value.splitlines()
    if len(lines) != 1:
        raise RuntimeV10AcceptanceError(
            "acceptance manifest must contain exactly one record"
        )
    line = lines[0]
    if len(line) < 67 or line[64:66] != "  ":
        raise RuntimeV10AcceptanceError("acceptance manifest record is malformed")
    digest, relative = line[:64], line[66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeV10AcceptanceError("acceptance manifest digest is malformed")
    _canonical_relative(relative)
    return digest, relative


def _verify_record(project: Path) -> str:
    manifest_digest, manifest_path = _manifest_line(
        _text(project, ACCEPTANCE_MANIFEST)
    )
    if manifest_path != ACCEPTANCE_RECORD:
        raise RuntimeV10AcceptanceError(
            "acceptance manifest points to an unexpected record"
        )
    record_digest = _digest(project, ACCEPTANCE_RECORD)
    if record_digest != manifest_digest:
        raise RuntimeV10AcceptanceError(
            "external acceptance record does not match its manifest"
        )
    record = _text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED — Runtime Core V10 only, isolated/default-off implementation handoff",
        CORE_SHA256,
        TESTS_SHA256,
        MANIFEST_SHA256,
        CHECKPOINT_SHA256,
        "P0=0, P1=0, P2=0, P3=0",
        "external-root/process limitation is resolved",
        "P3 monolith advisory retained",
        "V10 remains isolated, default-off and unwired",
        "Phase 5 remains incomplete",
    )
    missing = [item for item in required if item not in record]
    if missing:
        raise RuntimeV10AcceptanceError(
            f"acceptance record is missing required binding: {missing[0]}"
        )
    return record_digest


def _verify_candidate_anchors(project: Path) -> dict[str, int]:
    anchors = (
        (CORE, CORE_SHA256),
        (TESTS, TESTS_SHA256),
        (CANDIDATE_MANIFEST, MANIFEST_SHA256),
        (CHECKPOINT, CHECKPOINT_SHA256),
    )
    for relative, expected in anchors:
        _require_digest(project, relative, expected)

    try:
        manifest = json.loads(_text(project, CANDIDATE_MANIFEST))
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeV10AcceptanceError("candidate manifest is invalid") from exc
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "onyx.phase5.runtime-candidate-bundle.v1"
        or manifest.get("candidate") != "phase5-runtime-v10"
        or manifest.get("isolated") is not True
        or manifest.get("default_off") is not True
        or manifest.get("live_wired") is not False
    ):
        raise RuntimeV10AcceptanceError(
            "candidate manifest does not retain the frozen default-off contract"
        )
    current = manifest.get("files")
    historical = manifest.get("historical_files")
    if type(current) is not list or type(historical) is not list:
        raise RuntimeV10AcceptanceError("candidate manifest closure is malformed")
    expected_current = {
        CORE: CORE_SHA256,
        TESTS: TESTS_SHA256,
    }
    actual_current: dict[str, str] = {}
    seen: set[str] = set()
    for entry in current + historical:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise RuntimeV10AcceptanceError("candidate manifest entry is malformed")
        relative, expected = entry.get("path"), entry.get("sha256")
        if type(relative) is not str or type(expected) is not str:
            raise RuntimeV10AcceptanceError("candidate manifest entry types are invalid")
        _canonical_relative(relative)
        if relative in seen:
            raise RuntimeV10AcceptanceError("candidate manifest path is duplicated")
        seen.add(relative)
        _require_digest(project, relative, expected)
        if entry in current:
            actual_current[relative] = expected
    if actual_current != expected_current or len(historical) != 18:
        raise RuntimeV10AcceptanceError("candidate manifest closure is incomplete")

    checkpoint = _text(project, CHECKPOINT)
    required_checkpoint = (
        "isolated and default-off",
        "not an external acceptance record",
        CORE_SHA256,
        TESTS_SHA256,
        "External functional, integrity, and quality review is still required",
    )
    if any(item not in checkpoint for item in required_checkpoint):
        raise RuntimeV10AcceptanceError("checkpoint lost a frozen candidate binding")
    forbidden = (
        ACCEPTANCE_ID,
        ACCEPTANCE_RECORD,
        ACCEPTANCE_MANIFEST,
        "scripts/verify_phase5_runtime_v10_acceptance.py",
        "tests/test_phase5_runtime_v10_acceptance.py",
    )
    if any(item in _text(project, CANDIDATE_MANIFEST) for item in forbidden):
        raise RuntimeV10AcceptanceError(
            "external acceptance path entered the frozen candidate root"
        )
    return {"current_files": len(current), "historical_files": len(historical)}


def _verify_projections(project: Path) -> None:
    for label, relative in (
        ("capability matrix", CAPABILITY_MATRIX),
        ("verification evidence", VERIFICATION_EVIDENCE),
    ):
        value = _text(project, relative)
        if ACCEPTANCE_ID not in value or MANIFEST_SHA256 not in value:
            raise RuntimeV10AcceptanceError(
                f"{label} does not project the exact Runtime V10 acceptance"
            )
        if "Phase 5 remains incomplete" not in value:
            raise RuntimeV10AcceptanceError(
                f"{label} overstates Phase 5 completion"
            )


def _verify_unwired(project: Path) -> int:
    live_paths = ["main.py", "ui.py"]
    allowed_suffixes = {".py", ".pyw", ".ps1", ".iss", ".js", ".html", ".qml"}
    for root_name in ("dashboard", "scripts", "packaging", "core"):
        root = project / root_name
        if root.is_dir():
            live_paths.extend(
                path.relative_to(project).as_posix()
                for path in sorted(root.rglob("*"))
                if path.is_file()
                and path.suffix.lower() in allowed_suffixes
                and path.relative_to(project).as_posix()
                not in {CORE, "scripts/verify_phase5_runtime_v10_acceptance.py"}
            )
    needles = ("phase5_runtime_v10", "ONYX_PHASE5_RUNTIME_V10")
    def scan_text(relative: str) -> str:
        try:
            return _bytes(project, relative).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeV10AcceptanceError(
                f"live surface is not UTF-8: {relative}"
            ) from exc

    wired = [
        relative
        for relative in live_paths
        if any(needle in scan_text(relative) for needle in needles)
    ]
    if wired:
        raise RuntimeV10AcceptanceError(
            f"Runtime V10 entered a live surface: {wired[0]}"
        )
    return len(live_paths)


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    record_sha256 = _verify_record(project)
    closure = _verify_candidate_anchors(project)
    _verify_projections(project)
    live_files = _verify_unwired(project)
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "record_sha256": record_sha256,
        "core_sha256": CORE_SHA256,
        "tests_sha256": TESTS_SHA256,
        "manifest_sha256": MANIFEST_SHA256,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "closure": closure,
        "live_files_checked": live_files,
        "scope": "runtime-v10-isolated-default-off-unwired-handoff",
    }


def main() -> int:
    payload = verify()
    print(
        ACCEPTANCE_MARKER
        + " "
        + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
