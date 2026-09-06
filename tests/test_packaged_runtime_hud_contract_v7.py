from pathlib import Path

from core.onyx_packaged_runtime_hud_contract_v7 import (
    verify_packaged_runtime_hud_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_runtime_v7_binds_multimodal_attention() -> None:
    assert verify_packaged_runtime_hud_contract(ROOT) == {
        "schema": "onyx.packaged-runtime-hud-contract.v7",
        "runtime_inputs": 8,
        "current_orb": "humanoid-presence-v10",
        "camera_gesture_attention": True,
        "formal_release_ready": False,
    }
