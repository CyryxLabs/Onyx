"""Closed V23 positive-test succession; historical tests/manifests stay intact.

Only the old assertion that V23 describes the current ui.py is superseded.
V23's negative scope-reduction test still executes unchanged. V24 must execute
its positive and tamper tests, not merely return a verifier marker.
"""

import hashlib
from pathlib import Path

NODE = "tests/test_advanced_operations_source_acceptance_v23.py::test_v23_is_reproducible_exact_and_append_only"
SUCCESSOR = "tests/test_advanced_operations_source_acceptance_v24.py"
BINDINGS = {
    NODE.split("::")[0]: "0e79c2c0361f680f45e46b53513d884bf837654062dd5c6565442dae3eedeecd",
    SUCCESSOR: "4289bfebc603952f63e47032304321dabae3ea2a998a1d159f96f8c4bed9281c",
    "scripts/verify_advanced_operations_source_acceptance_v23.py": "8977de4c810150ccebccf3cc919ea82f5bbd33835ee0e1296110f0428b466431",
    "scripts/verify_advanced_operations_source_acceptance_v24.py": "e9d4dc5c24569c6a870f7537bd3923dbfdc04cc9d3d92ed8f8ab6e7a55125470",
    "docs/onyx/acceptance/VE-ADVANCED-OPS-V23-001.manifest.json": "3b719d4ad59bb19bc23ffad083419352fcf2b8ea5d0049cae51336c1ea034b8c",
}


def authenticate(root: Path) -> None:
    for relative, digest in BINDINGS.items():
        path = root / relative
        if path.is_symlink() or path.resolve(strict=True) != path.absolute():
            raise RuntimeError(f"Operations test succession path drifted: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Operations test succession bytes drifted: {relative}")


def run_verified_successor(root: Path, run_suite) -> None:
    from scripts import verify_advanced_operations_source_acceptance_v24 as current

    authenticate(root)
    # A cached test outcome is not authentication of today's runtime bytes.
    current.verify(root)
    run_suite("operations-v23-to-v24", (SUCCESSOR,))
