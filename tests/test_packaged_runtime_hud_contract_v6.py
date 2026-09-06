from pathlib import Path

from core.onyx_packaged_runtime_hud_contract_v6 import (
    verify_packaged_runtime_hud_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_runtime_v6_binds_humanoid_presence() -> None:
    assert verify_packaged_runtime_hud_contract(ROOT) == {
        "schema": "onyx.packaged-runtime-hud-contract.v6",
        "runtime_inputs": 11,
        "current_orb": "humanoid-presence-v10",
        "formal_release_ready": False,
    }
