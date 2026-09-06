"""Hermetic mutable projections for frozen Approval Inbox predecessor tests.

The Session Grants R11 DAG predates content-addressed mutable projections and
names two live documentation paths.  Successor acceptance legitimately changes
those live files.  When V2-V7 tests materialize the frozen R11 tree, supply the
exact bytes named by R11 instead of copying the newer live projections.

Only temporary test materializations are changed.  Historical source files,
manifests, live documentation and runtime wiring remain untouched.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
from pathlib import Path


ROOT = Path(__file__).absolute().parents[1]
SNAPSHOT_ROOT = (
    ROOT / "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections"
)
FROZEN_PROJECTIONS = {
    "docs/onyx/CAPABILITY_MATRIX.md": (
        "5a7c9f2c71d770b7a3fb49a511a9d94e59e985dd96d45f40b9ed6b7505ce3e8b"
    ),
    "docs/onyx/VERIFICATION_EVIDENCE.md": (
        "e8ab4895f1c8c6b61b2a3c97acbeac3149b966003e8a63f2eebe5f954c65ad79"
    ),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install_projection_wrapper(module: object) -> None:
    original = getattr(module, "materialize_r11")
    if getattr(original, "_onyx_v10_frozen_projections", False):
        return

    @functools.wraps(original)
    def materialize_r11(destination: Path) -> tuple[str, ...]:
        copied = original(destination)
        for relative, digest in FROZEN_PROJECTIONS.items():
            snapshot = SNAPSHOT_ROOT / f"{digest}.snapshot"
            if not snapshot.is_file() or _sha(snapshot) != digest:
                raise RuntimeError(f"frozen projection unavailable: {relative}")
            target = destination / relative
            if not target.is_file() or relative not in copied:
                raise RuntimeError(f"frozen projection not materialized: {relative}")
            target.write_bytes(snapshot.read_bytes())
            if _sha(target) != digest:
                raise RuntimeError(f"frozen projection copy drifted: {relative}")
        return copied

    materialize_r11._onyx_v10_frozen_projections = True  # type: ignore[attr-defined]
    setattr(module, "materialize_r11", materialize_r11)


def pytest_collection_modifyitems() -> None:
    for version in range(2, 8):
        module = importlib.import_module(
            f"scripts.verify_phase5_approval_inbox_v{version}"
        )
        _install_projection_wrapper(module)
