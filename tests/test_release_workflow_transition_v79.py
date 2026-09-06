from pathlib import Path

from scripts.verify_release_workflow_v79 import verify_release_workflow_v79


ROOT = Path(__file__).resolve().parents[1]


def test_release_v79_authenticates_startup_trust_boundary() -> None:
    result = verify_release_workflow_v79(ROOT)

    assert result["transition"]["logical_sequence"] == 79
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
