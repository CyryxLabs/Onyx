from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).absolute().parents[1]
SOURCE_REL = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V11-001.sha256"
ARTIFACTS_REL = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V11-001.sha256"
BUNDLE_REL = "docs/onyx/checkpoints/phase5-approval-inbox-v11/phase5-approval-inbox-v11.bundle.json"
WORKER_REL = "scripts/verify_phase5_approval_inbox_v11_worker.py"


class PathIntegrityError(RuntimeError):
    pass


def _safe_path_at(root: Path, relative: str) -> Path:
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
    if not current.is_file():
        raise PathIntegrityError(f"not-file:{relative}")
    return current


def safe_path(relative: str) -> Path:
    try:
        return _safe_path_at(ROOT, relative)
    except PathIntegrityError as error:
        fail(f"authority-path:{error}")


def sha(path: Path) -> str:
    try:
        relative = path.absolute().relative_to(ROOT.absolute()).as_posix()
    except ValueError:
        fail(f"outside-root:{path}")
    return hashlib.sha256(safe_path(relative).read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"P52_APPROVAL_INBOX_V11_EVIDENCE_FAIL {message}")


def manifest(path: Path) -> dict[str, str]:
    try:
        relative = path.absolute().relative_to(ROOT.absolute()).as_posix()
    except ValueError:
        fail(f"manifest-outside-root:{path}")
    path = safe_path(relative)
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([!-~]+)", line)
        if match is None or match.group(2) in result:
            fail(f"manifest:{path.name}")
        result[match.group(2)] = match.group(1)
    return result


def main() -> int:
    source_path = safe_path(SOURCE_REL)
    artifacts_path = safe_path(ARTIFACTS_REL)
    worker_path = safe_path(WORKER_REL)
    safe_path(BUNDLE_REL)
    source = manifest(source_path)
    if source != {ARTIFACTS_REL: sha(artifacts_path)}:
        fail("root-relation")
    artifacts = manifest(artifacts_path)
    for relative in (WORKER_REL, BUNDLE_REL):
        expected = artifacts.get(relative)
        if expected is None or sha(ROOT / relative) != expected:
            fail(f"prelaunch-drift:{relative}")
    bundle = json.loads(safe_path(BUNDLE_REL).read_text(encoding="utf-8"))
    if bundle.get("contract") != "Phase52ApprovalInboxEvidence.v11":
        fail("bundle-contract")
    # Re-check the launch target immediately before the non-atomic process
    # launch. The authoritative tree must remain stable across this boundary.
    worker_path = safe_path(WORKER_REL)
    process = subprocess.run(
        [sys.executable, str(worker_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    if process.returncode:
        print(process.stdout, end="")
        fail("worker")
    lines = [line for line in process.stdout.splitlines() if line]
    if len(lines) != 1 or not lines[0].startswith(
        "P52_APPROVAL_INBOX_V11_EVIDENCE_OK "
    ):
        print(process.stdout, end="")
        fail("worker-marker")
    print(lines[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
