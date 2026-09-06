from pathlib import Path

from scripts.verify_release_workflow_v80 import verify_release_workflow_v80


ROOT = Path(__file__).resolve().parents[1]


def test_release_v80_authenticates_governed_shutdown_recovery() -> None:
    result = verify_release_workflow_v80(ROOT)

    assert result["transition"]["logical_sequence"] == 80
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
