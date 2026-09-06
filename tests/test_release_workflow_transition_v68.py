from pathlib import Path

from scripts.generate_release_workflow_v68 import CURRENT_CLOSURE_PATHS
from scripts.verify_release_workflow_v68 import verify_release_workflow_v68

ROOT = Path(__file__).resolve().parents[1]


def test_release_v68_authenticates_current_packaged_hud_smoke() -> None:
    result = verify_release_workflow_v68(ROOT)
    assert result["transition"]["logical_sequence"] == 68
    paths = {entry["path"] for entry in result["transition"]["current_release_paths"]}
    assert set(CURRENT_CLOSURE_PATHS) <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
