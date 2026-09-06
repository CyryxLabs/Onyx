from pathlib import Path

from core.onyx_hud_current_acceptance_v37 import verify_current_hud_acceptance


ROOT = Path(__file__).resolve().parents[1]


def test_current_hud_v37_authenticates_humanoid_successor() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert result == {
        "candidate": "onyx-hud-v14-humanoid-presence-001",
        "runtime_inputs": 9,
        "predecessor": "onyx-hud-v36-liquid-metal-001",
        "palette_changed": False,
        "published": False,
    }
