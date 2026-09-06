from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v27 import (
    CURRENT_RUNTIME_PATHS,
    CurrentHudAcceptanceV27Error,
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


def test_v27_authenticates_single_root_source_closure() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert result["candidate"] == (
        "onyx-hud-v10-v40-single-root-accessibility-stability-009"
    )
    assert result["qml_roots_published_at_construction"] == 1
    assert result["runtime_inputs"] == len(CURRENT_RUNTIME_PATHS)
    assert result["stable_activation"] == "V24"


def test_v27_rejects_runtime_and_predecessor_tamper(tmp_path: Path) -> None:
    _copy_closure(tmp_path)
    with (tmp_path / "core/onyx_hud_orb_v10.py").open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV27Error, match="source input drift"):
        verify_current_hud_acceptance(tmp_path)

    shutil.rmtree(tmp_path)
    _copy_closure(tmp_path)
    with (tmp_path / PREDECESSOR_MANIFEST_RELATIVE).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(
        CurrentHudAcceptanceV27Error, match="source input drift|predecessor drift"
    ):
        verify_current_hud_acceptance(tmp_path)
