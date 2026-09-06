"""Independent verifier for the additive Release V55 successor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.verify_release_workflow_v45 import POLICY, _canonical_file, _entries, _issued, _root, _sha256, _strict_json  # noqa: E402

V55 = Path("tests/fixtures/release_workflow_transition_v55.json")
V54 = Path("tests/fixtures/release_workflow_transition_v54.json")
V55_SHA256 = "161b84b2c7bbb607d6221219037d665889c3579cd395417955e1ff727f093584"
V55_ROOT_SHA256 = "747dd23aba4db6c3c6812c6ed49abf2e137cbc98f0afe4160139b730ae9685e2"
V54_SHA256 = "c56bc179a032e5b0f94905b040e37aca8dd27413205c608b58f33eca5e6da739"
V54_ROOT_SHA256 = "2ef0cc2f28ed5eb78fbdd16efab285329b2e895c5dea2b99516af5900a6e17b3"
RECEIPT = Path("docs/onyx/checkpoints/RELEASE_WORKFLOW_V55_VERIFIER_RECEIPT.json")


class ReleaseWorkflowV55Error(RuntimeError):
    """Release V55 or its immutable V54 predecessor drifted."""


def verify_release_workflow_v55(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition = _strict_json(_canonical_file(root, V55))
    predecessor = _strict_json(_canonical_file(root, V54))
    if _sha256(root / V55) != V55_SHA256 or transition.get("schema") != "onyx.release-workflow-transition.v55" or transition.get("logical_sequence") != 55 or transition.get("predecessor") != {"path": V54.as_posix(), "sha256": V54_SHA256} or transition.get("policy") != POLICY or transition.get("current_root_sha256") != V55_ROOT_SHA256 or _root(transition, 55) != V55_ROOT_SHA256:
        raise ReleaseWorkflowV55Error("Release V55 contract drifted")
    if _sha256(root / V54) != V54_SHA256 or predecessor.get("current_root_sha256") != V54_ROOT_SHA256 or _root(predecessor, 54) != V54_ROOT_SHA256 or _issued(transition["issued_at"], "V55") <= _issued(predecessor["issued_at"], "V54"):
        raise ReleaseWorkflowV55Error("Release V54 predecessor drifted")
    for entry in _entries(transition, "Release V55"):
        if _sha256(_canonical_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV55Error(f"current release target drifted: {entry['path']}")
    receipt = _strict_json(_canonical_file(root, RECEIPT))
    expected = {"schema": "onyx.release-workflow-v55-verifier-receipt.v1", "release_path": V55.as_posix(), "release_sha256": V55_SHA256, "release_root_sha256": V55_ROOT_SHA256, "predecessor_sha256": V54_SHA256, "verifier_path": "scripts/verify_release_workflow_v55.py", "verifier_sha256": _sha256(root / "scripts/verify_release_workflow_v55.py"), "test_path": "tests/test_release_workflow_transition_v55.py", "test_sha256": _sha256(root / "tests/test_release_workflow_transition_v55.py"), "chronology": "normal_successor", "scope": "v33-symlink-safe-package-hygiene-closure-only"}
    if receipt != expected:
        raise ReleaseWorkflowV55Error("Release V55 verifier receipt drifted")
    return {"transition": transition, "receipt": receipt, "formal_release_ready": False, "publishable": False}


if __name__ == "__main__":
    result = verify_release_workflow_v55()
    print(json.dumps({"release_schema": result["transition"]["schema"], "release_root_sha256": result["transition"]["current_root_sha256"]}, sort_keys=True))
