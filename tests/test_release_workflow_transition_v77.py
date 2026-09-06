from pathlib import Path

from scripts.verify_release_workflow_v77 import verify_release_workflow_v77


ROOT = Path(__file__).resolve().parents[1]


def test_release_v77_authenticates_humanoid_render_stability() -> None:
    result = verify_release_workflow_v77(ROOT)

    assert result["transition"]["logical_sequence"] == 77
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
