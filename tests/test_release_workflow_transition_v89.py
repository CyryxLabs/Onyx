from pathlib import Path

from scripts.verify_release_workflow_v89 import verify_release_workflow_v89


ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_transition_v89_is_exact_and_non_publishable():
    result = verify_release_workflow_v89(ROOT)
    assert result["transition"]["logical_sequence"] == 89
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
