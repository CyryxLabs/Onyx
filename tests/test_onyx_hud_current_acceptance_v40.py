from pathlib import Path

from core.onyx_hud_current_acceptance_v40 import verify_current_hud_acceptance


ROOT = Path(__file__).resolve().parents[1]


def test_current_hud_v40_authenticates_calibrated_multimodal_attention() -> None:
    assert verify_current_hud_acceptance(ROOT) == {
        "candidate": "onyx-hud-v14-calibrated-multimodal-attention-001",
        "runtime_inputs": 13,
        "predecessor": "onyx-hud-v14-stable-multimodal-attention-001",
        "camera_gesture_attention": True,
        "session_hand_calibration": True,
        "attention_bridge_coalesced": True,
        "intermittent_flicker_guard": True,
        "governed_native_close": True,
        "published": False,
    }
