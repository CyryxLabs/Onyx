from pathlib import Path

from core.onyx_hud_current_acceptance_v43 import verify_current_hud_acceptance


ROOT = Path(__file__).resolve().parents[1]


def test_current_hud_v43_authenticates_setup_voice_selection() -> None:
    assert verify_current_hud_acceptance(ROOT) == {
        "candidate": "onyx-hud-v17-setup-voice-selection-001",
        "runtime_inputs": 10,
        "predecessor": "onyx-hud-v16-compositor-continuity-humanoid-001",
        "live_renderer": "three.js-webgl",
        "primary_layout_changed": False,
        "setup_surface_changed": True,
        "voice_selection_surface_changed": True,
        "published": False,
    }
