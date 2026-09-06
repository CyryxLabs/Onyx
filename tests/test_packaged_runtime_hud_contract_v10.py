from pathlib import Path

from core.onyx_packaged_runtime_hud_contract_v10 import (
    verify_packaged_runtime_hud_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_runtime_v10_binds_temporally_stable_humanoid() -> None:
    assert verify_packaged_runtime_hud_contract(ROOT) == {
        "schema": "onyx.packaged-runtime-hud-contract.v10",
        "runtime_inputs": 8,
        "current_orb": "humanoid-presence-v11-stable",
        "single_authoritative_animation_loop": True,
        "preserved_webgl_drawing_buffer": True,
        "opaque_hud_matched_surface": True,
        "formal_release_ready": False,
    }


def test_package_smoke_targets_the_current_stable_humanoid() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert '"onyxHumanoidPresenceV11Root"' in source
    assert '"onyxHumanoidThreeWebGLV2"' in source
    assert '"onyxHumanoidWebGLFallbackV2"' in source
    assert '"onyxLiveShellV14Root"' in source
    assert '"qml-v15-humanoid-stable"' in source
