from pathlib import Path

from core.onyx_packaged_runtime_hud_contract_v9 import (
    verify_packaged_runtime_hud_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_runtime_v9_binds_calibrated_multimodal_attention() -> None:
    assert verify_packaged_runtime_hud_contract(ROOT) == {
        "schema": "onyx.packaged-runtime-hud-contract.v9",
        "runtime_inputs": 8,
        "current_orb": "humanoid-presence-v10",
        "camera_gesture_attention": True,
        "session_hand_calibration": True,
        "attention_bridge_coalesced": True,
        "intermittent_flicker_guard": True,
        "governed_native_close": True,
        "formal_release_ready": False,
    }
