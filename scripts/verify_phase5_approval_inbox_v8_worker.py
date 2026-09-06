from __future__ import annotations

import argparse
import ast
import hashlib
import hmac
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V8-001.sha256"
SOURCE = ROOT / "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V8-001.sha256"
BUNDLE = (
    ROOT
    / "docs/onyx/checkpoints/phase5-approval-inbox-v8/phase5-approval-inbox-v8.bundle.json"
)
PROJECTIONS = (
    ROOT / "docs/onyx/checkpoints/phase5-approval-inbox-v8/mutable-projections.json"
)
FOCUSED = ("tests/test_approval_inbox_v8.py",)
COMBINED = tuple(f"tests/test_approval_inbox_v{version}.py" for version in range(1, 9))
REGRESSIONS = (
    "tests/test_regressions.py",
    "tests/test_missions.py",
    "tests/test_mission_tools.py",
)
EXPECTED_PUBLIC = {
    "ApprovalInboxFeatureGateV8",
    "MonotonicInboxClockV8",
    "DeterministicInboxClockV8",
    "HostInboxItemV8",
    "HostInboxSnapshotV8",
    "HostInboxSourceV8",
    "InboxQueryV8",
    "ApprovalReviewItemV8",
    "InboxPageV8",
    "CalmBatchPreviewV8",
    "ReviewSelectionHandoffV8",
    "ApprovalInboxProjectionV8",
}
FORBIDDEN_CORE_IMPORTS = (
    "approval_inbox_v1",
    "approval_inbox_v2",
    "approval_inbox_v3",
    "approval_inbox_v4",
    "approval_inbox_v5",
    "approval_inbox_v6",
    "approval_inbox_v7",
    "session_grants",
    "capability_nexus",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"P52_APPROVAL_INBOX_V8_EVIDENCE_FAIL {message}")


def safe_path(relative: str) -> Path:
    if (
        not relative
        or "\\" in relative
        or relative.startswith("/")
        or ".." in relative.split("/")
    ):
        fail(f"noncanonical-path:{relative}")
    path = ROOT.joinpath(*relative.split("/"))
    try:
        path.relative_to(ROOT)
    except ValueError:
        fail(f"outside-root:{relative}")
    current = ROOT
    for part in relative.split("/"):
        names = {entry.name: entry for entry in current.iterdir()}
        if part not in names:
            fail(f"missing-or-case-mismatch:{relative}")
        current = names[part]
        if current.is_symlink():
            fail(f"symlink-authority:{relative}")
    if not path.is_file():
        fail(f"not-file:{relative}")
    return path


def read_manifest(path: Path) -> dict[str, str]:
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
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    if (
        type(bundle) is not dict
        or bundle.get("contract") != "Phase52ApprovalInboxEvidence.v8"
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
    mapping = json.loads(PROJECTIONS.read_text(encoding="utf-8"))
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
    path = ROOT / "core/approval_inbox_v8.py"
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
        if isinstance(node, ast.ClassDef) and node.name == "ApprovalInboxProjectionV8"
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
        'APPROVAL_INBOX_V8_FLAG = "ONYX_APPROVAL_INBOX_V8"',
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
    flattened = [ROOT / "main.py", ROOT / "ui.py", ROOT / "scripts/launch_onyx.pyw"]
    for folder in ("actions", "dashboard"):
        flattened.extend((ROOT / folder).glob("*.py"))
    scanned = 0
    for path in flattened:
        if not path.is_file():
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="strict")
        if "approval_inbox_v8" in text or "ONYX_APPROVAL_INBOX_V8" in text:
            fail(f"live-reachability:{path.relative_to(ROOT).as_posix()}")
        ast.parse(text)
    return scanned


def run(command: list[str]) -> str:
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
            "core/approval_inbox_v8.py",
            "tests/test_approval_inbox_v8.py",
            "scripts/build_phase5_approval_inbox_v8_evidence.py",
        ],
        [
            python,
            "-m",
            "ruff",
            "check",
            "core/approval_inbox_v8.py",
            "tests/test_approval_inbox_v8.py",
            "scripts/build_phase5_approval_inbox_v8_evidence.py",
            "scripts/verify_phase5_approval_inbox_v8.py",
            "scripts/verify_phase5_approval_inbox_v8_worker.py",
            "scripts/check_phase5_approval_inbox_v8_whitespace.py",
        ],
        [
            python,
            "-m",
            "ruff",
            "format",
            "--check",
            "core/approval_inbox_v8.py",
            "tests/test_approval_inbox_v8.py",
            "scripts/build_phase5_approval_inbox_v8_evidence.py",
            "scripts/verify_phase5_approval_inbox_v8.py",
            "scripts/verify_phase5_approval_inbox_v8_worker.py",
            "scripts/check_phase5_approval_inbox_v8_whitespace.py",
        ],
        [python, "scripts/check_phase5_approval_inbox_v8_whitespace.py"],
        [
            "git",
            "diff",
            "--check",
            "--",
            "core/approval_inbox_v8.py",
            "tests/test_approval_inbox_v8.py",
            "scripts/build_phase5_approval_inbox_v8_evidence.py",
            "scripts/verify_phase5_approval_inbox_v8.py",
            "scripts/verify_phase5_approval_inbox_v8_worker.py",
            "scripts/check_phase5_approval_inbox_v8_whitespace.py",
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
    if arguments.manifest_only:
        print(
            f"P52_APPROVAL_INBOX_V8_MANIFEST_OK artifacts={artifacts} "
            f"live_files={live_files} root={sha(SOURCE)}"
        )
        return 0
    focused, combined, regressions, subtests = verify_fresh(bundle)
    print(
        "P52_APPROVAL_INBOX_V8_EVIDENCE_OK "
        f"focused={focused} combined={combined} regressions={regressions} "
        f"subtests={subtests} artifacts={artifacts} live_files={live_files} "
        f"root={sha(SOURCE)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
