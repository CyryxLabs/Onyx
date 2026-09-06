from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v34 import (
    CURRENT_RUNTIME_PATHS,
    MANIFEST_RELATIVE,
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
    CurrentHudAcceptanceV34Error,
    verify_current_hud_acceptance,
)
from scripts.package_hygiene import CAPABILITY_RUNTIME_FILES

ROOT = Path(__file__).resolve().parents[1]


def _copy_closure(destination: Path) -> None:
    for relative in {
        MANIFEST_RELATIVE,
        PREDECESSOR_ACCEPTANCE_RELATIVE,
        PREDECESSOR_MANIFEST_RELATIVE,
        *CURRENT_RUNTIME_PATHS,
    }:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def test_v34_authenticates_exact_current_capabilities_and_package_hygiene() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert result["candidate"] == "onyx-hud-v34-1.1.10-capability-current-001"
    assert result["runtime_inputs"] == len(CURRENT_RUNTIME_PATHS)
    assert result["capability_runtime_files"] == len(CAPABILITY_RUNTIME_FILES)
    assert result["packaged_test_sources"] is False


@pytest.mark.parametrize(
    "relative",
    [
        Path("core/capability_ports/budget_v1.py"),
        Path("scripts/package_hygiene.py"),
        PREDECESSOR_MANIFEST_RELATIVE,
    ],
)
def test_v34_rejects_current_or_predecessor_tamper(
    tmp_path: Path, relative: Path
) -> None:
    _copy_closure(tmp_path)
    with (tmp_path / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(
        CurrentHudAcceptanceV34Error,
        match="source input drift|predecessor drift",
    ):
        verify_current_hud_acceptance(tmp_path)


def test_v34_rejects_linked_capability_input(tmp_path: Path) -> None:
    _copy_closure(tmp_path)
    port = tmp_path / "core/capability_ports/budget_v1.py"
    target = port.with_name("budget_v1-real.py")
    port.replace(target)
    try:
        port.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(CurrentHudAcceptanceV34Error, match="unavailable|linked"):
        verify_current_hud_acceptance(tmp_path)
