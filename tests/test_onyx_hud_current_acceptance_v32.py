from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v32 import (
    CURRENT_RUNTIME_PATHS,
    CurrentHudAcceptanceV32Error,
    MANIFEST_RELATIVE,
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
    verify_current_hud_acceptance,
)


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


def test_v32_authenticates_1_1_10_without_replacing_renderer() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert result["candidate"] == "onyx-hud-v32-1.1.10-integration-001"
    assert result["release_version"] == "1.1.10"
    assert result["qml_root"] == "V11"
    assert result["orb_controller"] == "V12"
    assert result["runtime_inputs"] == len(CURRENT_RUNTIME_PATHS)


def test_v32_rejects_runtime_and_predecessor_tamper(tmp_path: Path) -> None:
    _copy_closure(tmp_path)
    with (tmp_path / "core/topic_monitor_v1.py").open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV32Error, match="source input drift"):
        verify_current_hud_acceptance(tmp_path)

    shutil.rmtree(tmp_path)
    _copy_closure(tmp_path)
    with (tmp_path / PREDECESSOR_MANIFEST_RELATIVE).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(
        CurrentHudAcceptanceV32Error, match="source input drift|predecessor drift"
    ):
        verify_current_hud_acceptance(tmp_path)
