from pathlib import Path

from scripts.verify_release_workflow_v78 import verify_release_workflow_v78


ROOT = Path(__file__).resolve().parents[1]


def test_release_v78_authenticates_compositor_continuity() -> None:
    result = verify_release_workflow_v78(ROOT)

    assert result["transition"]["logical_sequence"] == 78
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False

