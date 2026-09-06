from pathlib import Path

from core.onyx_packaged_runtime_hud_contract_v15 import (
    verify_packaged_runtime_hud_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_v15_authenticates_non_visual_shortcut_recovery() -> None:
    assert verify_packaged_runtime_hud_contract(ROOT) == {
        "schema": "onyx.packaged-runtime-hud-contract.v15",
        "runtime_inputs": 10,
        "current_presence": "humanoid-presence-v12-continuity",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "frozen_shortcut_arguments_empty": True,
        "configured_setup_dismissible": True,
        "first_boot_setup_mandatory": True,
        "formal_release_ready": False,
    }
