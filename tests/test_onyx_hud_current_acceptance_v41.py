from pathlib import Path

from core.onyx_hud_current_acceptance_v41 import verify_current_hud_acceptance


ROOT = Path(__file__).resolve().parents[1]


def test_current_hud_v41_authenticates_temporally_stable_humanoid() -> None:
    assert verify_current_hud_acceptance(ROOT) == {
        "candidate": "onyx-hud-v15-temporally-stable-humanoid-001",
        "runtime_inputs": 11,
        "predecessor": "onyx-hud-v14-calibrated-multimodal-attention-001",
        "single_authoritative_animation_loop": True,
        "preserved_webgl_drawing_buffer": True,
        "opaque_hud_matched_surface": True,
        "temporal_states_tested": ["READY", "LISTENING", "SPEAKING"],
        "published": False,
    }
