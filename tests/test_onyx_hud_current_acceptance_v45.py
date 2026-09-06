from pathlib import Path

from core.onyx_hud_current_acceptance_v45 import verify_current_hud_acceptance


ROOT = Path(__file__).resolve().parents[1]


def test_current_hud_v45_authenticates_non_visual_setup_dismissal() -> None:
    assert verify_current_hud_acceptance(ROOT) == {
        "candidate": "onyx-hud-v19-configured-setup-dismissal-001",
        "runtime_inputs": 10,
        "predecessor": "onyx-hud-v18-setup-event-loop-stability-001",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": False,
        "configured_setup_dismissible": True,
        "first_boot_setup_mandatory": True,
        "published": False,
    }
