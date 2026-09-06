from pathlib import Path

from scripts.generate_release_workflow_v74 import CURRENT_CLOSURE_PATHS
from scripts.verify_release_workflow_v74 import verify_release_workflow_v74


ROOT = Path(__file__).resolve().parents[1]


def test_release_v74_authenticates_packaged_parity_successor() -> None:
    result = verify_release_workflow_v74(ROOT)
    assert result["transition"]["logical_sequence"] == 74
    paths = {entry["path"] for entry in result["transition"]["current_release_paths"]}
    assert set(CURRENT_CLOSURE_PATHS) <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
