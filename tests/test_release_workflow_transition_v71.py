from pathlib import Path
from scripts.generate_release_workflow_v71 import CURRENT_CLOSURE_PATHS
from scripts.verify_release_workflow_v71 import verify_release_workflow_v71

ROOT = Path(__file__).resolve().parents[1]


def test_release_v71_authenticates_converged_release_documentation_authority():
    result = verify_release_workflow_v71(ROOT)
    assert result["transition"]["logical_sequence"] == 71
    paths = {e["path"] for e in result["transition"]["current_release_paths"]}
    assert set(CURRENT_CLOSURE_PATHS) <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
