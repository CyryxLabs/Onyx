"""Independent verifier for the dependency-safe Release V47 successor."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

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


RELEASE_V47_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v47.json"
)
RELEASE_V47_SHA256: Final = (
    "96743238fee217e561ceb91734649aa1394f930acc312a30e0491bd7714267cc"
)
RELEASE_V47_ROOT_SHA256: Final = (
    "cc9ce78980e2a714c26f046449a7ed8aa770a19d09322909adbf4106464238b6"
)
RELEASE_V46_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v46.json"
)
RELEASE_V46_SHA256: Final = (
    "e9c25fb4716a511b28e58f4c6d9dd492db9dd242673dd580082725f423238261"
)
RELEASE_V46_ROOT_SHA256: Final = (
    "278b35b1fb012ecb1c7963d90313fe4389c3ea8fbff46ff9f9176353907ed9d5"
)
V46_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v46.py")
V46_VERIFIER_SHA256: Final = (
    "a828a75954b9ca8187570eb28e87502643a2e57de403df2c70672b8e14814ce7"
)
V46_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V46_VERIFIER_RECEIPT.json"
)
V46_RECEIPT_SHA256: Final = (
    "1e1149ec1796ab0bc4eef2f05d16a3ec22fa8026ab0662db364881f6705a4f5a"
)
V46_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v46.py")
V46_TEST_SHA256: Final = (
    "2dee71f866552efd44a4e829e7ecc77df6a6b5442113e6d2034beee93061d8bb"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v47.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V47_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v47.py")


class ReleaseWorkflowV47Error(RuntimeError):
    """Release V47 or its immutable V46 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition_path = _canonical_file(root, RELEASE_V47_RELATIVE)
    if _sha256(transition_path) != RELEASE_V47_SHA256:
        raise ReleaseWorkflowV47Error("Release V47 fixture digest drifted")
    transition = _strict_json(transition_path)
    if (
        set(transition)
        != {
            "schema",
            "issued_at",
            "logical_sequence",
            "predecessor",
            "policy",
            "current_release_paths",
            "current_root_sha256",
        }
        or transition.get("schema") != "onyx.release-workflow-transition.v47"
        or transition.get("logical_sequence") != 47
        or transition.get("predecessor")
        != {"path": RELEASE_V46_RELATIVE.as_posix(), "sha256": RELEASE_V46_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V47_ROOT_SHA256
        or _root(transition, 47) != RELEASE_V47_ROOT_SHA256
    ):
        raise ReleaseWorkflowV47Error("Release V47 contract drifted")

    predecessor_path = _canonical_file(root, RELEASE_V46_RELATIVE)
    if _sha256(predecessor_path) != RELEASE_V46_SHA256:
        raise ReleaseWorkflowV47Error("Release V46 predecessor digest drifted")
    predecessor = _strict_json(predecessor_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v46"
        or predecessor.get("logical_sequence") != 46
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V46_ROOT_SHA256
        or _root(predecessor, 46) != RELEASE_V46_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V47 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V46 issued_at")
    ):
        raise ReleaseWorkflowV47Error("Release V46 predecessor contract drifted")
    for relative, expected in (
        (V46_VERIFIER_RELATIVE, V46_VERIFIER_SHA256),
        (V46_RECEIPT_RELATIVE, V46_RECEIPT_SHA256),
        (V46_TEST_RELATIVE, V46_TEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV47Error(f"Release V46 authority drifted: {relative}")

    current_entries = _entries(transition, "Release V47")
    for entry in current_entries:
        relative = entry["path"]
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise ReleaseWorkflowV47Error(f"current release target drifted: {relative}")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v47-verifier-receipt.v1",
        "release_path": RELEASE_V47_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V47_SHA256,
        "release_root_sha256": RELEASE_V47_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V46_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
    }:
        raise ReleaseWorkflowV47Error("Release V47 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v30 import verify_current_hud_acceptance
    from scripts.verify_r11_projection_retirement_v1 import (
        _load_blob_pack,
        load_retirement_record,
    )

    runtime = verify_current_hud_acceptance(root)
    retirement = load_retirement_record()
    blobs, head_files = _load_blob_pack()
    return {
        "transition": transition,
        "v46_predecessor": predecessor,
        "runtime": runtime,
        "retirement": retirement,
        "blob_count": len(blobs),
        "head_file_count": len(head_files),
        "receipt": receipt,
    }


def verify_release_workflow_v47(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except (ReleaseWorkflowV43Error, ReleaseWorkflowV45Error) as exc:
        raise ReleaseWorkflowV47Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v47()
    print(
        json.dumps(
            {
                "blob_count": verified["blob_count"],
                "head_file_count": verified["head_file_count"],
                "release_root_sha256": verified["transition"]["current_root_sha256"],
                "release_schema": verified["transition"]["schema"],
                "runtime_root_sha256": verified["runtime"]["artifact_root_sha256"],
            },
            sort_keys=True,
        )
    )
