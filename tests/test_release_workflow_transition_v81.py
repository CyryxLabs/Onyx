from pathlib import Path

from scripts.verify_release_workflow_v81 import verify_release_workflow_v81


ROOT = Path(__file__).resolve().parents[1]


def test_release_v81_authenticates_mobile_humanoid_and_current_tests() -> None:
    result = verify_release_workflow_v81(ROOT)

    assert result["transition"]["logical_sequence"] == 81
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
