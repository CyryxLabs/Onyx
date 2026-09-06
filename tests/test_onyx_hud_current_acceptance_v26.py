from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PySide6.QtQuick import QQuickItem  # noqa: F401
from PySide6.QtQuickWidgets import QQuickWidget  # noqa: F401

from core.onyx_hud_current_acceptance_v26 import (
    CURRENT_RUNTIME_PATHS,
    CurrentHudAcceptanceV26Error,
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


def test_v26_authenticates_source_frozen_split_and_v25_predecessor() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert result["candidate"] == "onyx-hud-v10-v38-frozen-diagnostic-closure-008"
    assert result["runtime_inputs"] == len(CURRENT_RUNTIME_PATHS)
    assert result["stable_activation"] == "V24"
    assert result["packaged_subset_contract"] == "v1"


def test_v26_rejects_current_tamper_and_v25_predecessor_tamper(tmp_path: Path) -> None:
    _copy_closure(tmp_path)
    with (tmp_path / "core/native_startup_smoke_v1.py").open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV26Error, match="source input drift"):
        verify_current_hud_acceptance(tmp_path)

    shutil.rmtree(tmp_path)
    _copy_closure(tmp_path)
    with (tmp_path / PREDECESSOR_MANIFEST_RELATIVE).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV26Error, match="source input drift|predecessor drift"):
        verify_current_hud_acceptance(tmp_path)
