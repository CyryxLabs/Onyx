from pathlib import Path

from scripts.generate_release_workflow_v69 import CURRENT_CLOSURE_PATHS
from scripts.verify_release_workflow_v69 import verify_release_workflow_v69

ROOT = Path(__file__).resolve().parents[1]


def test_release_v69_authenticates_converged_phase5_authority() -> None:
    result = verify_release_workflow_v69(ROOT)
    assert result["transition"]["logical_sequence"] == 69
    paths = {entry["path"] for entry in result["transition"]["current_release_paths"]}
    assert set(CURRENT_CLOSURE_PATHS) <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
