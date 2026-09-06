from pathlib import Path

from scripts.verify_release_workflow_v82 import verify_release_workflow_v82


ROOT = Path(__file__).resolve().parents[1]


def test_release_v82_authenticates_mark_lii_operational_parity() -> None:
    result = verify_release_workflow_v82(ROOT)

    assert result["transition"]["logical_sequence"] == 82
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
