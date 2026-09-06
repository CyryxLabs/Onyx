from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).absolute().parents[1]
SOURCE_REL = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V15-001.sha256"
ARTIFACTS_REL = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V15-001.sha256"
BUNDLE_REL = "docs/onyx/checkpoints/phase5-approval-inbox-v15/phase5-approval-inbox-v15.bundle.json"
WORKER_REL = "scripts/verify_phase5_approval_inbox_v15_worker.py"
PYTHON_FLAGS = ("-I", "-S", "-B")


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
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
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
    raise SystemExit(f"P52_APPROVAL_INBOX_V15_EVIDENCE_FAIL {message}")


def _validated_taskkill() -> Path:
    if os.name != "nt":
        raise PathIntegrityError("taskkill-non-windows")
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise PathIntegrityError("windows-root-unavailable")
    root = Path(buffer.value).absolute()
    return _safe_path_at(root, "System32/taskkill.exe")


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
    if not (
        sys.flags.isolated
        and sys.flags.no_site
        and sys.flags.safe_path
        and sys.flags.dont_write_bytecode
    ):
        fail("python-not-isolated-use--I--S--B")
    sys.dont_write_bytecode = True
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
    if bundle.get("contract") != "Phase52ApprovalInboxEvidence.v15":
        fail("bundle-contract")
    # Re-check the launch target immediately before the non-atomic process
    # launch. The authoritative tree must remain stable across this boundary.
    worker_path = safe_path(WORKER_REL)
    allowed = {
        "SystemRoot",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "COMSPEC",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER",
        "PROCESSOR_LEVEL",
        "PROCESSOR_REVISION",
        "PATHEXT",
        "LANG",
        "LC_ALL",
        "TZ",
    }
    environment = {name: value for name, value in os.environ.items() if name in allowed}
    environment.update(
        {
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": "",
        }
    )
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    deadline = time.monotonic() + 900.0
    process = subprocess.Popen(
        [sys.executable, *PYTHON_FLAGS, str(worker_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
        **kwargs,
    )
    try:
        output, _ = process.communicate(timeout=deadline - time.monotonic())
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            try:
                taskkill = _validated_taskkill()
            except PathIntegrityError as error:
                process.kill()
                fail(f"taskkill-authority:{error}")
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                env=environment,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)
        fail("global-process-deadline-tree-terminated")
    if process.returncode:
        print(output, end="")
        fail("worker")
    lines = [line for line in output.splitlines() if line]
    if len(lines) != 1 or not lines[0].startswith(
        "P52_APPROVAL_INBOX_V15_EVIDENCE_OK "
    ):
        print(output, end="")
        fail("worker-marker")
    print(lines[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
