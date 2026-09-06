from pathlib import Path

from scripts.generate_release_workflow_v65 import CURRENT_CLOSURE_PATHS
from scripts.verify_release_workflow_v65 import verify_release_workflow_v65

ROOT = Path(__file__).resolve().parents[1]


def test_release_v65_authenticates_current_hud_accessibility_authority() -> None:
    result = verify_release_workflow_v65(ROOT)
    assert result["transition"]["logical_sequence"] == 65
    paths = {entry["path"] for entry in result["transition"]["current_release_paths"]}
    assert set(CURRENT_CLOSURE_PATHS) <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
