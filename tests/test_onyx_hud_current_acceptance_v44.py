from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v44 import (
    CurrentHudAcceptanceV44Error,
    verify_current_hud_acceptance,
)


ROOT = Path(__file__).resolve().parents[1]


def test_current_hud_v44_retires_after_configured_setup_dismissal() -> None:
    with pytest.raises(CurrentHudAcceptanceV44Error, match="ui.py"):
        verify_current_hud_acceptance(ROOT)
