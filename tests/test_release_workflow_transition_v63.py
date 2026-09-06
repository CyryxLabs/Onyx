from __future__ import annotations

from pathlib import Path

from scripts.generate_release_workflow_v63 import CURRENT_CLOSURE_PATHS
from scripts.verify_release_workflow_v63 import verify_release_workflow_v63


ROOT = Path(__file__).resolve().parents[1]


def test_release_v63_authenticates_converged_current_authority() -> None:
    result = verify_release_workflow_v63(ROOT)
    assert result["transition"]["logical_sequence"] == 63
    paths = {entry["path"] for entry in result["transition"]["current_release_paths"]}
    assert set(CURRENT_CLOSURE_PATHS) <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
