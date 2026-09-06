from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v42 import (
    CurrentHudAcceptanceV42Error,
    verify_current_hud_acceptance,
)


ROOT = Path(__file__).resolve().parents[1]


def test_current_hud_v42_retires_after_authenticated_setup_delta() -> None:
    with pytest.raises(CurrentHudAcceptanceV42Error, match="ui.py"):
        verify_current_hud_acceptance(ROOT)
