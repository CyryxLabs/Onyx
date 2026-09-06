"""Fixed two-phase bootstrap with no command-line or environment command surface."""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


PROJECT = Path(__file__).resolve().parents[1]
PRIVATE_BASE = Path(tempfile.gettempdir()) / "onyx-p53-v19-private"
SENTINEL = ".phase53-v19-private"
_CONTRACT = "Phase53CapabilityNexusBootstrap.v19"
_TOKEN = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN_ENV_PREFIX = "ONYX_P53_V19"


def _plain_component(path: Path) -> None:
    info = path.lstat()
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & reparse:
        raise RuntimeError("bootstrap private path contains a reparse component")


def _evidence_path(nonce: str, *, focused: bool) -> Path:
    expected_base = Path(tempfile.gettempdir()).resolve(strict=True) / PRIVATE_BASE.name
    base = PRIVATE_BASE.resolve(strict=True)
    if base != expected_base:
        raise RuntimeError("bootstrap private base realpath is invalid")
    _plain_component(PRIVATE_BASE)
    directory = PRIVATE_BASE / nonce
    _plain_component(directory)
    resolved = directory.resolve(strict=True)
    if resolved.parent != base or resolved.name != nonce:
        raise RuntimeError("bootstrap nonce directory realpath is invalid")
    sentinel = directory / SENTINEL
    _plain_component(sentinel)
    if not sentinel.is_file() or sentinel.read_text(encoding="ascii") != f"{_CONTRACT}:{nonce}\n":
        raise RuntimeError("bootstrap private sentinel is invalid")
    junit = directory / "focused.junit.xml"
    if focused:
        if junit.exists():
            raise RuntimeError("bootstrap focused JUnit already exists")
    else:
        _plain_component(junit)
        if not junit.is_file() or junit.resolve(strict=True).parent != resolved:
            raise RuntimeError("bootstrap fresh JUnit path is invalid")
    return junit


def _command(phase: str, evidence_nonce: str) -> list[str]:
    junit = _evidence_path(evidence_nonce, focused=phase == "focused")
    if phase == "focused":
        return [
            sys.executable, "-m", "pytest", "-q", "tests/test_capability_nexus_v19.py",
            "--disable-warnings", "--maxfail=1", f"--junitxml={junit}",
        ]
    if phase == "worker":
        return [
            sys.executable, "scripts/verify_phase5_capability_nexus_v19_worker.py",
            "--fresh-focused-junit", str(junit),
        ]
    raise RuntimeError("bootstrap phase is invalid")


def main() -> int:
    if sys.argv != [sys.argv[0]]:
        raise RuntimeError("bootstrap exposes no command-line surface")
    if any(key.startswith(_FORBIDDEN_ENV_PREFIX) for key in os.environ):
        raise RuntimeError("bootstrap environment override is forbidden")
    fields = sys.stdin.readline().rstrip("\n").split(" ")
    if (
        len(fields) != 4
        or fields[0] != "HELLO"
        or fields[1] not in {"focused", "worker"}
        or _TOKEN.fullmatch(fields[2]) is None
        or _TOKEN.fullmatch(fields[3]) is None
    ):
        raise RuntimeError("bootstrap authenticated launch envelope is invalid")
    _, phase, launch_nonce, evidence_nonce = fields
    command = _command(phase, evidence_nonce)
    sys.stdout.write(f"READY {phase} {launch_nonce}\n")
    sys.stdout.flush()
    if sys.stdin.readline() != f"GO {launch_nonce}\n" or sys.stdin.read(1) != "":
        raise RuntimeError("bootstrap one-shot GO barrier is invalid")
    process = subprocess.Popen(
        command, cwd=PROJECT, env=os.environ.copy(), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
    )
    stdout, stderr = process.communicate()
    if stdout:
        sys.stdout.write(stdout)
        sys.stdout.flush()
    if stderr:
        sys.stderr.write(stderr)
        sys.stderr.flush()
    return int(process.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
