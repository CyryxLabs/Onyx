from pathlib import Path

import pytest

from core.onyx_packaged_runtime_hud_contract_v11 import (
    PackagedRuntimeHudContractV11Error,
    verify_packaged_runtime_hud_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_runtime_v11_retires_after_authenticated_setup_delta() -> None:
    with pytest.raises(PackagedRuntimeHudContractV11Error, match="ui.py"):
        verify_packaged_runtime_hud_contract(ROOT)


def test_package_smoke_targets_the_current_continuity_humanoid() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert '"onyxHumanoidPresenceV12Root"' in source
    assert '"onyxHumanoidThreeWebGLV3"' in source
    assert '"onyxHumanoidContinuityA"' in source
    assert '"onyxLiveShellV15Root"' in source
    assert '"qml-v16-humanoid-continuity"' in source
