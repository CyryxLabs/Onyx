from pathlib import Path

from scripts.verify_release_workflow_v55 import verify_release_workflow_v55

ROOT = Path(__file__).resolve().parents[1]


def test_release_v55_authenticates_v33_package_hygiene_successor() -> None:
    result = verify_release_workflow_v55(ROOT)
    transition = result["transition"]
    assert transition["logical_sequence"] == 55
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert {"core/onyx_hud_current_acceptance_v33.py", "scripts/package_hygiene.py", "tests/test_package_hygiene_v1.py"} <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
