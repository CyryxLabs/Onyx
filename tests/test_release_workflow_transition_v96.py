from pathlib import Path

from scripts.verify_release_workflow_v96 import verify_release_workflow_v96


def test_release_v96_keeps_public_release_unapproved():
    result = verify_release_workflow_v96(Path(__file__).resolve().parents[1])
    assert result["publishable"] is False
    assert result["formal_release_ready"] is False
