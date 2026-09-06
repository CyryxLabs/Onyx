from pathlib import Path

from core.onyx_hud_current_acceptance_v46 import verify_current_hud_acceptance


ROOT = Path(__file__).resolve().parents[1]


def test_current_hud_v46_authenticates_non_visual_shortcut_recovery() -> None:
    assert verify_current_hud_acceptance(ROOT) == {
        "candidate": "onyx-hud-v20-empty-shortcut-argument-recovery-001",
        "runtime_inputs": 10,
        "predecessor": "onyx-hud-v19-configured-setup-dismissal-001",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "frozen_shortcut_arguments_empty": True,
        "configured_setup_dismissible": True,
        "first_boot_setup_mandatory": True,
        "published": False,
    }
