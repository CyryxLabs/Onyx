"""Independent verifier for the HUD V30 and runtime-closure Release V46."""

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


RELEASE_V46_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v46.json"
)
RELEASE_V46_SHA256: Final = (
    "e9c25fb4716a511b28e58f4c6d9dd492db9dd242673dd580082725f423238261"
)
RELEASE_V46_ROOT_SHA256: Final = (
    "278b35b1fb012ecb1c7963d90313fe4389c3ea8fbff46ff9f9176353907ed9d5"
)
RELEASE_V45_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v45.json"
)
RELEASE_V45_SHA256: Final = (
    "d5b7998eb1ea4ca6129c6e572770aa54d79fbc37ffec56d69d51ad07c9b68986"
)
RELEASE_V45_ROOT_SHA256: Final = (
    "47535f1f45edb8f5e0046db00c418110940d2fcf3c9804b11922138c16dbcade"
)
V45_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v45.py")
V45_VERIFIER_SHA256: Final = (
    "2c277a88675b8ebc2906f4039ae04ab90a3688b4a7f7b141bb703a84ce017763"
)
V45_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V45_VERIFIER_RECEIPT.json"
)
V45_RECEIPT_SHA256: Final = (
    "04e4f33ea930265a4fed02554ac82fbfdc6f2173cd441547477727e8006a2fd9"
)
V45_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v45.py")
V45_TEST_SHA256: Final = (
    "6d9ecc511c90ec703fa81ff6053d69ff190432b57b3d87f78b9983b133d817e8"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v46.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V46_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v46.py")


class ReleaseWorkflowV46Error(RuntimeError):
    """Release V46 or its immutable V45 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition_path = _canonical_file(root, RELEASE_V46_RELATIVE)
    if _sha256(transition_path) != RELEASE_V46_SHA256:
        raise ReleaseWorkflowV46Error("Release V46 fixture digest drifted")
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
        or transition.get("schema") != "onyx.release-workflow-transition.v46"
        or transition.get("logical_sequence") != 46
        or transition.get("predecessor")
        != {"path": RELEASE_V45_RELATIVE.as_posix(), "sha256": RELEASE_V45_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V46_ROOT_SHA256
        or _root(transition, 46) != RELEASE_V46_ROOT_SHA256
    ):
        raise ReleaseWorkflowV46Error("Release V46 contract drifted")

    predecessor_path = _canonical_file(root, RELEASE_V45_RELATIVE)
    if _sha256(predecessor_path) != RELEASE_V45_SHA256:
        raise ReleaseWorkflowV46Error("Release V45 predecessor digest drifted")
    predecessor = _strict_json(predecessor_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v45"
        or predecessor.get("logical_sequence") != 45
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V45_ROOT_SHA256
        or _root(predecessor, 45) != RELEASE_V45_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V46 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V45 issued_at")
    ):
        raise ReleaseWorkflowV46Error("Release V45 predecessor contract drifted")
    for relative, expected in (
        (V45_VERIFIER_RELATIVE, V45_VERIFIER_SHA256),
        (V45_RECEIPT_RELATIVE, V45_RECEIPT_SHA256),
        (V45_TEST_RELATIVE, V45_TEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV46Error(f"Release V45 authority drifted: {relative}")

    current_entries = _entries(transition, "Release V46")
    for entry in current_entries:
        relative = entry["path"]
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise ReleaseWorkflowV46Error(f"current release target drifted: {relative}")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v46-verifier-receipt.v1",
        "release_path": RELEASE_V46_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V46_SHA256,
        "release_root_sha256": RELEASE_V46_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V45_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
    }:
        raise ReleaseWorkflowV46Error("Release V46 verifier receipt drifted")

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
        "v45_predecessor": predecessor,
        "runtime": runtime,
        "retirement": retirement,
        "blob_count": len(blobs),
        "head_file_count": len(head_files),
        "receipt": receipt,
    }


def verify_release_workflow_v46(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except (ReleaseWorkflowV43Error, ReleaseWorkflowV45Error) as exc:
        raise ReleaseWorkflowV46Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v46()
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
