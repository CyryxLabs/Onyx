from pathlib import Path

from core.onyx_packaged_runtime_hud_contract_v14 import (
    verify_packaged_runtime_hud_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_v14_authenticates_non_visual_setup_dismissal() -> None:
    assert verify_packaged_runtime_hud_contract(ROOT) == {
        "schema": "onyx.packaged-runtime-hud-contract.v14",
        "runtime_inputs": 10,
        "current_presence": "humanoid-presence-v12-continuity",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "configured_setup_dismissible": True,
        "first_boot_setup_mandatory": True,
        "formal_release_ready": False,
    }
