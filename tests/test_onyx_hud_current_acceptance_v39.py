from pathlib import Path

from core.onyx_hud_current_acceptance_v39 import verify_current_hud_acceptance


ROOT = Path(__file__).resolve().parents[1]


def test_current_hud_v39_authenticates_stable_multimodal_attention() -> None:
    assert verify_current_hud_acceptance(ROOT) == {
        "candidate": "onyx-hud-v14-stable-multimodal-attention-001",
        "runtime_inputs": 13,
        "predecessor": "onyx-hud-v14-multimodal-attention-001",
        "global_pointer_attention": True,
        "camera_gesture_attention": True,
        "attention_bridge_coalesced": True,
        "intermittent_flicker_guard": True,
        "governed_native_close": True,
        "published": False,
    }
