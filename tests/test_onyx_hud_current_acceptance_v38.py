from pathlib import Path

from core.onyx_hud_current_acceptance_v38 import verify_current_hud_acceptance


ROOT = Path(__file__).resolve().parents[1]


def test_current_hud_v38_authenticates_multimodal_attention() -> None:
    assert verify_current_hud_acceptance(ROOT) == {
        "candidate": "onyx-hud-v14-multimodal-attention-001",
        "runtime_inputs": 11,
        "predecessor": "onyx-hud-v14-humanoid-presence-001",
        "global_pointer_attention": True,
        "camera_gesture_attention": True,
        "published": False,
    }
