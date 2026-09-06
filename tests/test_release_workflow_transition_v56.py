import json
from pathlib import Path

from scripts.generate_release_workflow_v56 import AUTHORITY_PATHS
from scripts.verify_release_workflow_v56 import verify_release_workflow_v56

ROOT = Path(__file__).resolve().parents[1]


def test_release_v56_authenticates_exact_capability_runtime_closure() -> None:
    result = verify_release_workflow_v56(ROOT)
    transition = result["transition"]
    assert transition["logical_sequence"] == 56
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert set(AUTHORITY_PATHS) <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False


def test_release_v56_preserves_immutable_packaged_v2_contract() -> None:
    v55 = json.loads(
        (ROOT / "tests/fixtures/release_workflow_transition_v55.json").read_text(
            encoding="utf-8"
        )
    )
    v56 = verify_release_workflow_v56(ROOT)["transition"]
    paths = (
        "core/onyx_packaged_runtime_hud_contract_v2.py",
        "core/onyx_packaged_runtime_hud_contract_v2.manifest.json",
    )
    predecessor = {entry["path"]: entry["sha256"] for entry in v55["current_release_paths"]}
    successor = {entry["path"]: entry["sha256"] for entry in v56["current_release_paths"]}
    assert {path: successor[path] for path in paths} == {
        path: predecessor[path] for path in paths
    }
    manifest = json.loads((ROOT / paths[1]).read_text(encoding="utf-8"))
    assert manifest["semantics"] == {
        "capability_smoke": "provider-free-explicit",
        "checkout_fallback": False,
        "provider_dispatch": False,
        "tests_in_runtime": False,
    }
