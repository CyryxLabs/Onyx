"""Standalone verifier for complete current HUD retirement Release V66."""

from datetime import datetime
from pathlib import Path

from scripts.verify_release_workflow_v65 import POLICY, _entries, _file, _json, _root, _sha256

PROJECT = Path(__file__).resolve().parents[1]
V66 = Path("tests/fixtures/release_workflow_transition_v66.json")
V65 = Path("tests/fixtures/release_workflow_transition_v65.json")
V66_SHA256 = "0c116b7546bca0686415060567d878364f95540465b3152a0667bee1f369fbc0"
V66_ROOT_SHA256 = "4fb58fae8be24d0ddd87128559cbf96e74946362935089ae2b842fee88172c90"
V65_SHA256 = "c1e5009460ab129c08881710e287cc8aa6d093196ba8f228c72df531d109ddfa"
V65_ROOT_SHA256 = "e678160f8c83ddc2a7b00f1d19aa1b91d3716b0132608f3c18796ef82d5b8174"


class ReleaseWorkflowV66Error(RuntimeError):
    pass


def verify_release_workflow_v66(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V66))
    predecessor = _json(_file(root, V65))
    if (
        _sha256(root / V66) != V66_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v66"
        or transition.get("logical_sequence") != 66
        or transition.get("predecessor") != {"path": V65.as_posix(), "sha256": V65_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V66_ROOT_SHA256
        or _root(transition, 66) != V66_ROOT_SHA256
    ):
        raise ReleaseWorkflowV66Error("Release V66 contract drifted")
    if _sha256(root / V65) != V65_SHA256 or predecessor.get("current_root_sha256") != V65_ROOT_SHA256 or _root(predecessor, 65) != V65_ROOT_SHA256 or datetime.fromisoformat(transition["issued_at"]) <= datetime.fromisoformat(predecessor["issued_at"]):
        raise ReleaseWorkflowV66Error("Release V65 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV66Error(f"current release target drifted: {entry['path']}")
    return {"transition": transition, "formal_release_ready": False, "publishable": False}


if __name__ == "__main__":
    print(verify_release_workflow_v66()["transition"]["current_root_sha256"])
