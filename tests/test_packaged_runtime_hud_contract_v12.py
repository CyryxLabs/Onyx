from pathlib import Path

from core.onyx_packaged_runtime_hud_contract_v12 import (
    verify_packaged_runtime_hud_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_v12_authenticates_setup_voice_selection() -> None:
    assert verify_packaged_runtime_hud_contract(ROOT) == {
        "schema": "onyx.packaged-runtime-hud-contract.v12",
        "runtime_inputs": 10,
        "current_presence": "humanoid-presence-v12-continuity",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": True,
        "voice_selection_surface_changed": True,
        "formal_release_ready": False,
    }
