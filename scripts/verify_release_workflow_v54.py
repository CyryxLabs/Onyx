"""Independent verifier for the Release V54 packaging-closure successor."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.verify_release_runtime_closure_v2 import (  # noqa: E402
    ReleaseRuntimeClosureV2Error,
    verify_release_runtime_closure_v2,
)
from scripts.verify_release_workflow_v45 import (  # noqa: E402
    POLICY,
    ReleaseWorkflowV43Error,
    ReleaseWorkflowV45Error,
    _canonical_file,
    _entries,
    _issued,
    _root,
    _sha256,
    _strict_json,
)


RELEASE_V54_RELATIVE: Final = Path("tests/fixtures/release_workflow_transition_v54.json")
RELEASE_V54_SHA256: Final = "c56bc179a032e5b0f94905b040e37aca8dd27413205c608b58f33eca5e6da739"
RELEASE_V54_ROOT_SHA256: Final = "2ef0cc2f28ed5eb78fbdd16efab285329b2e895c5dea2b99516af5900a6e17b3"
RELEASE_V53_RELATIVE: Final = Path("tests/fixtures/release_workflow_transition_v53.json")
RELEASE_V53_SHA256: Final = "2d1531743bd7f1a30f680c447d819a1724771c70c98f4006cf940cc8433cac52"
RELEASE_V53_ROOT_SHA256: Final = "3b3de7f148463a71ce281d5c55c43fe99e4189d8fc33990da0b22499c4feb9b7"
V53_AUTHORITIES: Final = {
    Path("scripts/verify_release_workflow_v53.py"): "be18f7d2169169cea9bcf7c26ecdec28c7adfa5f34ef3acf7c2586f63af9ff32",
    Path("tests/test_release_workflow_transition_v53.py"): "4c840e68d9bd7cbf25f963dc84b31e496ace0e8e6b148f586563ad0f7db85a21",
    Path("docs/onyx/checkpoints/RELEASE_WORKFLOW_V53_VERIFIER_RECEIPT.json"): "41628705f6b8421e76384e66b27bebb3313599e03b582f2ed8fc36fb877a15e9",
}
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v54.py")
RECEIPT_RELATIVE: Final = Path("docs/onyx/checkpoints/RELEASE_WORKFLOW_V54_VERIFIER_RECEIPT.json")
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v54.py")


class ReleaseWorkflowV54Error(RuntimeError):
    """Release V54 or its immutable V53 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition_path = _canonical_file(root, RELEASE_V54_RELATIVE)
    if _sha256(transition_path) != RELEASE_V54_SHA256:
        raise ReleaseWorkflowV54Error("Release V54 fixture digest drifted")
    transition = _strict_json(transition_path)
    if (
        transition.get("schema") != "onyx.release-workflow-transition.v54"
        or transition.get("logical_sequence") != 54
        or transition.get("predecessor")
        != {"path": RELEASE_V53_RELATIVE.as_posix(), "sha256": RELEASE_V53_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V54_ROOT_SHA256
        or _root(transition, 54) != RELEASE_V54_ROOT_SHA256
    ):
        raise ReleaseWorkflowV54Error("Release V54 contract drifted")
    predecessor = _strict_json(_canonical_file(root, RELEASE_V53_RELATIVE))
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v53"
        or predecessor.get("logical_sequence") != 53
        or predecessor.get("current_root_sha256") != RELEASE_V53_ROOT_SHA256
        or _root(predecessor, 53) != RELEASE_V53_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V54 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V53 issued_at")
    ):
        raise ReleaseWorkflowV54Error("Release V53 predecessor contract drifted")
    for relative, expected in V53_AUTHORITIES.items():
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV54Error(f"Release V53 authority drifted: {relative}")
    for entry in _entries(transition, "Release V54"):
        if _sha256(_canonical_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV54Error(f"current release target drifted: {entry['path']}")
    closure = verify_release_runtime_closure_v2(root)
    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    expected_receipt = {
        "schema": "onyx.release-workflow-v54-verifier-receipt.v1",
        "release_path": RELEASE_V54_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V54_SHA256,
        "release_root_sha256": RELEASE_V54_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V53_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": _sha256(_canonical_file(root, VERIFIER_RELATIVE)),
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": _sha256(_canonical_file(root, TEST_RELATIVE)),
        "chronology": "normal_successor",
        "scope": "provider-free-frozen-capability-packaging-closure-only",
    }
    if receipt != expected_receipt:
        raise ReleaseWorkflowV54Error("Release V54 verifier receipt drifted")
    return {
        "transition": transition,
        "v53_predecessor": predecessor,
        "closure": closure,
        "receipt": receipt,
        "runtime_authority_changed": True,
        "formal_release_ready": False,
        "publishable": False,
    }


def verify_release_workflow_v54(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except (ReleaseRuntimeClosureV2Error, ReleaseWorkflowV43Error, ReleaseWorkflowV45Error) as exc:
        raise ReleaseWorkflowV54Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v54()
    print(json.dumps({"release_root_sha256": verified["transition"]["current_root_sha256"], "release_schema": verified["transition"]["schema"], "runtime_authority_changed": True}, sort_keys=True))
