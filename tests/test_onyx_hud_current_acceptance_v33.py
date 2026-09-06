from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v33 import (
    CURRENT_RUNTIME_PATHS,
    CurrentHudAcceptanceV33Error,
    MANIFEST_RELATIVE,
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
    verify_current_hud_acceptance,
)

ROOT = Path(__file__).resolve().parents[1]


def _copy_closure(destination: Path) -> None:
    for relative in {MANIFEST_RELATIVE, PREDECESSOR_ACCEPTANCE_RELATIVE, PREDECESSOR_MANIFEST_RELATIVE, *CURRENT_RUNTIME_PATHS}:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def test_v33_authenticates_current_symlink_safe_runtime() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert result["candidate"] == "onyx-hud-v33-1.1.10-symlink-safe-001"
    assert result["runtime_inputs"] == len(CURRENT_RUNTIME_PATHS)
    assert result["symlink_and_reparse_protection_preserved"] is True
    assert result["packaged_test_sources"] is False


@pytest.mark.parametrize("relative", [Path("core/permission_broker.py"), PREDECESSOR_MANIFEST_RELATIVE])
def test_v33_rejects_current_or_predecessor_tamper(tmp_path: Path, relative: Path) -> None:
    _copy_closure(tmp_path)
    with (tmp_path / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV33Error, match="source input drift|predecessor drift"):
        verify_current_hud_acceptance(tmp_path)


def test_v33_rejects_linked_runtime_input(tmp_path: Path) -> None:
    _copy_closure(tmp_path)
    broker = tmp_path / "core/permission_broker.py"
    target = tmp_path / "core/permission_broker-real.py"
    broker.replace(target)
    try:
        broker.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(CurrentHudAcceptanceV33Error, match="unavailable|linked"):
        verify_current_hud_acceptance(tmp_path)
