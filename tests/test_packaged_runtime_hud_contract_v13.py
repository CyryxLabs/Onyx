from pathlib import Path

import pytest

from core.onyx_packaged_runtime_hud_contract_v13 import (
    PackagedRuntimeHudContractV13Error,
    verify_packaged_runtime_hud_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_runtime_v13_retires_after_configured_setup_dismissal() -> None:
    with pytest.raises(PackagedRuntimeHudContractV13Error, match="ui.py"):
        verify_packaged_runtime_hud_contract(ROOT)
