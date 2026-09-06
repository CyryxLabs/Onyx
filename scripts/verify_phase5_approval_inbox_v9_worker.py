from __future__ import annotations

import argparse
import ast
import hashlib
import hmac
import json
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).absolute().parents[1]
ARTIFACTS = ROOT / "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V9-001.sha256"
SOURCE = ROOT / "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V9-001.sha256"
BUNDLE = (
    ROOT
    / "docs/onyx/checkpoints/phase5-approval-inbox-v9/phase5-approval-inbox-v9.bundle.json"
)
PROJECTIONS = (
    ROOT / "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections.json"
)
FOCUSED = ("tests/test_approval_inbox_v9.py",)
COMBINED = tuple(f"tests/test_approval_inbox_v{version}.py" for version in range(1, 10))
REGRESSIONS = (
    "tests/test_regressions.py",
    "tests/test_missions.py",
    "tests/test_mission_tools.py",
)
EXPECTED_PUBLIC = {
    "ApprovalInboxFeatureGateV9",
    "MonotonicInboxClockV9",
    "DeterministicInboxClockV9",
    "HostInboxItemV9",
    "HostInboxSnapshotV9",
    "HostInboxSourceV9",
    "InboxQueryV9",
    "ApprovalReviewItemV9",
    "InboxPageV9",
    "CalmBatchPreviewV9",
    "ReviewSelectionHandoffV9",
    "ApprovalInboxProjectionV9",
}
FORBIDDEN_CORE_IMPORTS = (
    "approval_inbox_v1",
    "approval_inbox_v2",
    "approval_inbox_v3",
    "approval_inbox_v4",
    "approval_inbox_v5",
    "approval_inbox_v6",
    "approval_inbox_v7",
    "approval_inbox_v8",
    "session_grants",
    "capability_nexus",
)
EXPECTED_LIVE_FILES = 26


class PathIntegrityError(RuntimeError):
    pass


def _safe_path_at(
    root: Path, relative: str, *, require_directory: bool = False
) -> Path:
    pure = PurePosixPath(relative)
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
        or pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise PathIntegrityError(f"noncanonical-path:{relative!r}")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    root = root.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as error:
        raise PathIntegrityError(f"missing-root:{relative}") from error
    if (
        stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & reparse
        or str(root) != str(root_resolved)
    ):
        raise PathIntegrityError(f"reparse-or-aliased-root:{relative}")
    current = root
    for part in pure.parts:
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as error:
            raise PathIntegrityError(f"unreadable-ancestor:{relative}") from error
        if part not in entries:
            raise PathIntegrityError(f"missing-or-case-mismatch:{relative}")
        current = entries[part]
        try:
            info = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as error:
            raise PathIntegrityError(f"missing-component:{relative}") from error
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & reparse
        ):
            raise PathIntegrityError(f"reparse-component:{relative}")
        try:
            resolved.relative_to(root_resolved)
        except ValueError as error:
            raise PathIntegrityError(f"outside-root:{relative}") from error
        if resolved.name != part:
            raise PathIntegrityError(f"case-or-name-alias:{relative}")
    if require_directory:
        if not current.is_dir():
            raise PathIntegrityError(f"not-directory:{relative}")
    elif not current.is_file():
        raise PathIntegrityError(f"not-file:{relative}")
    return current


def sha(path: Path) -> str:
    try:
        relative = path.absolute().relative_to(ROOT.absolute()).as_posix()
        guarded = _safe_path_at(ROOT, relative)
    except (ValueError, PathIntegrityError) as error:
        fail(f"authority-path:{error}")
    return hashlib.sha256(guarded.read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"P52_APPROVAL_INBOX_V9_EVIDENCE_FAIL {message}")


def safe_path(relative: str) -> Path:
    try:
        return _safe_path_at(ROOT, relative)
    except PathIntegrityError as error:
        fail(f"authority-path:{error}")


def read_manifest(path: Path) -> dict[str, str]:
    try:
        relative = path.absolute().relative_to(ROOT.absolute()).as_posix()
    except ValueError:
        fail(f"manifest-outside-root:{path}")
    path = safe_path(relative)
    result: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  ([!-~]+)", line)
        if match is None:
            fail(f"malformed-manifest:{path.name}:{number}")
        digest, relative = match.groups()
        if relative in result:
            fail(f"duplicate-manifest-path:{relative}")
        result[relative] = digest
    if not result:
        fail(f"empty-manifest:{path.name}")
    return result


def verify_manifests() -> tuple[dict[str, object], int]:
    source = read_manifest(SOURCE)
    expected_source = {ARTIFACTS.relative_to(ROOT).as_posix(): sha(ARTIFACTS)}
    if source != expected_source:
        fail("source-root-relation")
    artifacts = read_manifest(ARTIFACTS)
    for relative, expected in artifacts.items():
        actual = sha(safe_path(relative))
        if not hmac.compare_digest(actual, expected):
            fail(f"artifact-drift:{relative}")
    bundle = json.loads(
        safe_path(BUNDLE.relative_to(ROOT).as_posix()).read_text(encoding="utf-8")
    )
    if (
        type(bundle) is not dict
        or bundle.get("contract") != "Phase52ApprovalInboxEvidence.v9"
    ):
        fail("bundle-contract")
    files = bundle.get("files")
    if type(files) is not dict:
        fail("bundle-files")
    for relative, expected in files.items():
        if type(relative) is not str or type(expected) is not str:
            fail("bundle-file-entry")
        if sha(safe_path(relative)) != expected:
            fail(f"bundle-file-drift:{relative}")
        if artifacts.get(relative) != expected:
            fail(f"bundle-artifact-disagreement:{relative}")
    return bundle, len(artifacts)


def verify_projection_snapshots() -> None:
    mapping = json.loads(
        safe_path(PROJECTIONS.relative_to(ROOT).as_posix()).read_text(encoding="utf-8")
    )
    if mapping.get("contract") != "ContentAddressedMutableProjections.v1":
        fail("projection-map-contract")
    exact_sources = {
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VERIFICATION_EVIDENCE.md",
    }
    entries = mapping.get("projections")
    if (
        type(entries) is not list
        or {entry.get("source") for entry in entries} != exact_sources
    ):
        fail("projection-map-sources")
    artifacts = read_manifest(ARTIFACTS)
    if exact_sources.intersection(artifacts):
        fail("mutable-live-projection-in-artifacts")
    for entry in entries:
        source = entry.get("source")
        snapshot = entry.get("snapshot")
        digest = entry.get("sha256")
        if not all(type(value) is str for value in (source, snapshot, digest)):
            fail("projection-map-entry")
        path = safe_path(snapshot)
        if sha(path) != digest or artifacts.get(snapshot) != digest:
            fail(f"projection-snapshot-drift:{source}")


def verify_core_shape() -> None:
    path = safe_path("core/approval_inbox_v9.py")
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    public = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    }
    if not EXPECTED_PUBLIC.issubset(public):
        fail("missing-public-contract")
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    if any(fragment in name for name in imports for fragment in FORBIDDEN_CORE_IMPORTS):
        fail("forbidden-predecessor-import")
    projection = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ApprovalInboxProjectionV9"
    )
    methods = {
        node.name
        for node in projection.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden = {
        "approve",
        "deny",
        "revoke",
        "grant",
        "dispatch",
        "execute",
        "persist",
        "save",
        "write",
    }
    if methods.intersection(forbidden):
        fail("authority-method-present")
    required_literals = (
        'APPROVAL_INBOX_V9_FLAG = "ONYX_APPROVAL_INBOX_V9"',
        'DISABLED = "DISABLED"',
        'READY = "READY"',
        'STALE = "STALE"',
        'REVOKED = "REVOKED"',
        'INTEGRITY_LATCHED = "INTEGRITY_LATCHED"',
        "default=False, init=False",
        "future-approval-must-re-resolve-all-host-action-fields",
    )
    for literal in required_literals:
        if literal not in text:
            fail(f"missing-core-invariant:{literal}")


def verify_no_live_reachability() -> int:
    flattened = ["main.py", "ui.py", "scripts/launch_onyx.pyw"]
    for folder in ("actions", "dashboard"):
        try:
            directory = _safe_path_at(ROOT, folder, require_directory=True)
        except PathIntegrityError as error:
            fail(f"authority-path:{error}")
        for path in directory.glob("*.py"):
            flattened.append(path.relative_to(ROOT).as_posix())
    scanned = 0
    for relative in flattened:
        path = safe_path(relative)
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="strict")
        if "approval_inbox_v9" in text or "ONYX_APPROVAL_INBOX_V9" in text:
            fail(f"live-reachability:{path.relative_to(ROOT).as_posix()}")
        ast.parse(text)
    if scanned != EXPECTED_LIVE_FILES:
        fail(f"live-cardinality:{scanned}:{EXPECTED_LIVE_FILES}")
    return scanned


def run(command: list[str]) -> str:
    for argument in command[1:]:
        if type(argument) is str and not argument.startswith("-") and "/" in argument:
            safe_path(argument)
    process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    if process.returncode:
        print(process.stdout)
        fail(f"command:{' '.join(command)}")
    return process.stdout


def passed_count(output: str) -> int:
    matches = re.findall(r"(\d+) passed", output)
    if not matches:
        fail("pytest-count-missing")
    return int(matches[-1])


def verify_fresh(bundle: dict[str, object]) -> tuple[int, int, int, int]:
    python = sys.executable
    focused_output = run(
        [python, "-m", "pytest", *FOCUSED, "-q", "-p", "no:cacheprovider"]
    )
    combined_output = run(
        [python, "-m", "pytest", *COMBINED, "-q", "-p", "no:cacheprovider"]
    )
    regression_output = run(
        [python, "-m", "pytest", *REGRESSIONS, "-q", "-p", "no:cacheprovider"]
    )
    focused = passed_count(focused_output)
    combined = passed_count(combined_output)
    regressions = passed_count(regression_output)
    subtests = sum(
        int(value) for value in re.findall(r"(\d+) subtests passed", regression_output)
    )
    expected = bundle.get("counts")
    if type(expected) is not dict or (
        focused != expected.get("focused_passed")
        or combined != expected.get("combined_passed")
        or regressions != expected.get("regression_passed")
        or subtests != expected.get("regression_subtests")
    ):
        fail(f"fresh-counts:{focused}:{combined}:{regressions}:{subtests}")
    static_commands = (
        [
            python,
            "-m",
            "py_compile",
            "core/approval_inbox_v9.py",
            "tests/test_approval_inbox_v9.py",
            "scripts/build_phase5_approval_inbox_v9_evidence.py",
        ],
        [
            python,
            "-m",
            "ruff",
            "check",
            "core/approval_inbox_v9.py",
            "tests/test_approval_inbox_v9.py",
            "scripts/build_phase5_approval_inbox_v9_evidence.py",
            "scripts/verify_phase5_approval_inbox_v9.py",
            "scripts/verify_phase5_approval_inbox_v9_worker.py",
            "scripts/check_phase5_approval_inbox_v9_whitespace.py",
        ],
        [
            python,
            "-m",
            "ruff",
            "format",
            "--check",
            "core/approval_inbox_v9.py",
            "tests/test_approval_inbox_v9.py",
            "scripts/build_phase5_approval_inbox_v9_evidence.py",
            "scripts/verify_phase5_approval_inbox_v9.py",
            "scripts/verify_phase5_approval_inbox_v9_worker.py",
            "scripts/check_phase5_approval_inbox_v9_whitespace.py",
        ],
        [python, "scripts/check_phase5_approval_inbox_v9_whitespace.py"],
        [
            "git",
            "diff",
            "--check",
            "--",
            "core/approval_inbox_v9.py",
            "tests/test_approval_inbox_v9.py",
            "scripts/build_phase5_approval_inbox_v9_evidence.py",
            "scripts/verify_phase5_approval_inbox_v9.py",
            "scripts/verify_phase5_approval_inbox_v9_worker.py",
            "scripts/check_phase5_approval_inbox_v9_whitespace.py",
        ],
    )
    for command in static_commands:
        run(list(command))
    return focused, combined, regressions, subtests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-only", action="store_true")
    arguments = parser.parse_args()
    bundle, artifacts = verify_manifests()
    verify_projection_snapshots()
    verify_core_shape()
    live_files = verify_no_live_reachability()
    if bundle.get("live_scan_files") != EXPECTED_LIVE_FILES:
        fail(f"bundle-live-cardinality:{bundle.get('live_scan_files')}")
    if arguments.manifest_only:
        print(
            f"P52_APPROVAL_INBOX_V9_MANIFEST_OK artifacts={artifacts} "
            f"live_files={live_files} root={sha(SOURCE)}"
        )
        return 0
    focused, combined, regressions, subtests = verify_fresh(bundle)
    print(
        "P52_APPROVAL_INBOX_V9_EVIDENCE_OK "
        f"focused={focused} combined={combined} regressions={regressions} "
        f"subtests={subtests} artifacts={artifacts} live_files={live_files} "
        f"root={sha(SOURCE)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
