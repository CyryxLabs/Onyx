"""Recover four exact R11 source edges without rebinding historical hashes.

Snapshot recovered from Onyx-Remediation-20260823-150305/memory/store.py.
The digest is the pre-existing R11 manifest edge, not a newly selected digest.
The installed/current memory implementation is never replaced.
"""

import hashlib
from pathlib import Path

from scripts import verify_r11_projection_retirement_v2 as predecessor

PROJECT = Path(__file__).resolve().parents[1]
RELATIVE = "memory/store.py"
EXPECTED = "0516fafd24be3519851615108c1bdf396309d6f730ae21345a81cb02ee0e61ff"
SNAPSHOT = "tests/fixtures/r11-memory-store-0516fafd.snapshot"
EDGES = {
    RELATIVE: (EXPECTED, SNAPSHOT),
    "actions/file_processor.py": (
        "a233194960de277fe697172d663ea12d8d6ac9de5feb4e1c41fc24ce7185a04c",
        "tests/fixtures/r11-a233194960de277fe697172d663ea12d8d6ac9de5feb4e1c41fc24ce7185a04c.snapshot",
    ),
    "core/readiness.py": (
        "6cd546e975b05efd74c5cd790f3a6129d151ff86fb8557e8ec56cd465a661601",
        "tests/fixtures/r11-6cd546e975b05efd74c5cd790f3a6129d151ff86fb8557e8ec56cd465a661601.snapshot",
    ),
    "memory/memory_manager.py": (
        "6f4418afba826a60a682ec2c926fb9d214f14081a20c958f7f55688b66b0777c",
        "tests/fixtures/r11-6f4418afba826a60a682ec2c926fb9d214f14081a20c958f7f55688b66b0777c.snapshot",
    ),
}


def read_memory_evidence(expected_sha256: str, project: Path = PROJECT) -> bytes:
    return read_evidence(RELATIVE, expected_sha256, project)


def read_evidence(relative: str, expected_sha256: str, project: Path = PROJECT) -> bytes:
    expected, snapshot = EDGES[relative]
    if expected_sha256 != expected:
        raise predecessor.R11ProjectionRetirementError("R11 memory edge drifted")
    root = Path(project).resolve(strict=True)
    path = root / snapshot
    if path.is_symlink() or path.resolve(strict=True) != path.absolute():
        raise predecessor.R11ProjectionRetirementError("R11 memory snapshot path drifted")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise predecessor.R11ProjectionRetirementError("R11 memory snapshot digest drifted")
    return data


def install():
    original = predecessor._historical_head_file

    def read(relative: str, expected_sha256: str) -> bytes:
        if relative in EDGES:
            return read_evidence(relative, expected_sha256)
        return original(relative, expected_sha256)

    predecessor._historical_head_file = read

    def restore():
        predecessor._historical_head_file = original

    return restore
