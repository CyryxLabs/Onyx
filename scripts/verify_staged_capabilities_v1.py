"""Current-source binding for the staged capability slice and legacy receipts.

Build-only validation, not provider or runtime permission. The source authority
must be authenticated before staged bytes are compared. V3/V4 remain immutable
historical contracts; the current stager intentionally retains three exact test
files as data required by the older activation chain, never as a pytest suite.
"""

from pathlib import Path

from scripts.package_hygiene import (
    CAPABILITY_RUNTIME_FILES,
    RUNTIME_TEST_EVIDENCE_FILES,
)
from scripts.verify_release_workflow_v101 import (
    _file,
    _sha256,
    verify_release_workflow_v101,
)


class StagedCapabilityError(RuntimeError):
    """The staged slice does not match authenticated current source."""


def _root(path):
    root = Path(path).absolute()
    if not root.is_dir() or root.is_symlink() or root.resolve(strict=True) != root:
        raise StagedCapabilityError("staged root unavailable or linked")
    return root


def _verify_slice(stage: Path, bindings: dict[str, str]) -> dict:
    """Pure byte/membership checks; only verify() grants source-bound admission."""
    stage = _root(stage)
    capabilities = frozenset(CAPABILITY_RUNTIME_FILES)
    receipts = frozenset(RUNTIME_TEST_EVIDENCE_FILES)
    required = capabilities | receipts
    if not required.issubset(bindings):
        raise StagedCapabilityError("source authority omits capability or receipt inputs")
    for relative in sorted(required):
        try:
            path = _file(stage, Path(relative))
        except (OSError, ValueError, RuntimeError) as exc:
            raise StagedCapabilityError(f"staged input unavailable or linked: {relative}") from exc
        if _sha256(path) != bindings[relative]:
            raise StagedCapabilityError(f"staged input drifted: {relative}")
    expected_ports = {path for path in capabilities if path.startswith("core/capability_ports/")}
    actual_ports = {
        path.relative_to(stage).as_posix()
        for path in (stage / "core/capability_ports").glob("*.py")
    }
    if actual_ports != expected_ports:
        raise StagedCapabilityError("staged capability port membership drifted")
    # These are three explicit flat receipt files, not development tests. Any
    # additional entry, including a directory or link, is not an approved receipt.
    actual_receipts = {path.relative_to(stage).as_posix() for path in (stage / "tests").iterdir()}
    if actual_receipts != receipts:
        raise StagedCapabilityError("staged receipt membership drifted")
    return {
        "schema": "onyx.staged-capability-source.v1",
        "capability_files": len(capabilities),
        "historical_receipt_files": len(receipts),
        "development_tests": False,
        "provider_dispatch": False,
        "checkout_fallback": False,
    }


def verify(stage: Path, *, project: Path) -> dict:
    current = verify_release_workflow_v101(project)
    if (current["publishable"] is not False
            or current["formal_release_ready"] is not False
            or current["transition"]["logical_sequence"] != 101):
        raise StagedCapabilityError("source-only staging cannot grant release authority")
    bindings = {row["path"]: row["sha256"] for row in current["transition"]["current_release_paths"]}
    return _verify_slice(stage, bindings)
