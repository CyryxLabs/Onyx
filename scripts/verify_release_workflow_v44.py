"""Independent verifier for the fully hermetic Release V44 successor."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.verify_release_workflow_v43 import (  # noqa: E402
    POLICY,
    ReleaseWorkflowV43Error,
    _canonical_file,
    _entries,
    _issued,
    _root,
    _sha256,
    _strict_json,
)


RELEASE_V44_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v44.json"
)
RELEASE_V44_SHA256: Final = (
    "0d89a2a5eff3a6e0bc155ede25000a331921ae4096f952c3f1c70644e112804d"
)
RELEASE_V44_ROOT_SHA256: Final = (
    "7f9e88230530610675be881d40bf50462917d1bb085ce0fd0517a8ec7fe9e493"
)
RELEASE_V43_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v43.json"
)
RELEASE_V43_SHA256: Final = (
    "98cd93b35a293f46b83836ecff984c7111a53bf6db7496e4f27b29929e73432f"
)
RELEASE_V43_ROOT_SHA256: Final = (
    "66eb5228407317407b8ae084ebe930b7e7c3d45139cfe5ba56d3641bcbe1573b"
)
V43_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v43.py")
V43_VERIFIER_SHA256: Final = (
    "2ab50fe39fbe4787f7ec850e21258a06045b3a47c1c8999719e9d56a4ffaffe3"
)
V43_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V43_VERIFIER_RECEIPT.json"
)
V43_RECEIPT_SHA256: Final = (
    "4ac163e0e453447dd37bcbe9caf7f548add359c0e4645e007a11fad72434617a"
)
V43_TEST_SHA256: Final = (
    "324728fa90caa971e31becb98a79a10c0ded93acd4ee1f4564192bf34d56f328"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v44.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V44_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v44.py")


class ReleaseWorkflowV44Error(RuntimeError):
    """Release V44 or its immutable V43 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    v44_path = _canonical_file(root, RELEASE_V44_RELATIVE)
    if _sha256(v44_path) != RELEASE_V44_SHA256:
        raise ReleaseWorkflowV44Error("Release V44 fixture digest drifted")
    transition = _strict_json(v44_path)
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
        or transition.get("schema") != "onyx.release-workflow-transition.v44"
        or transition.get("logical_sequence") != 44
        or transition.get("predecessor")
        != {"path": RELEASE_V43_RELATIVE.as_posix(), "sha256": RELEASE_V43_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V44_ROOT_SHA256
        or _root(transition, 44) != RELEASE_V44_ROOT_SHA256
    ):
        raise ReleaseWorkflowV44Error("Release V44 contract drifted")

    v43_path = _canonical_file(root, RELEASE_V43_RELATIVE)
    if _sha256(v43_path) != RELEASE_V43_SHA256:
        raise ReleaseWorkflowV44Error("Release V43 predecessor digest drifted")
    predecessor = _strict_json(v43_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v43"
        or predecessor.get("logical_sequence") != 43
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V43_ROOT_SHA256
        or _root(predecessor, 43) != RELEASE_V43_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V44 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V43 issued_at")
    ):
        raise ReleaseWorkflowV44Error("Release V43 predecessor contract drifted")

    current_entries = _entries(transition, "Release V44")
    predecessor_entries = _entries(predecessor, "Release V43")
    current_hashes = {entry["path"]: entry["sha256"] for entry in current_entries}
    predecessor_hashes = {
        entry["path"]: entry["sha256"] for entry in predecessor_entries
    }
    for entry in current_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] or predecessor_hashes.get(relative) == actual:
            raise ReleaseWorkflowV44Error(f"current release target drifted: {relative}")
    for entry in predecessor_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] and current_hashes.get(relative) != actual:
            raise ReleaseWorkflowV44Error(
                f"Release V43 current target drifted: {relative}"
            )

    for relative, expected in (
        (V43_VERIFIER_RELATIVE, V43_VERIFIER_SHA256),
        (V43_RECEIPT_RELATIVE, V43_RECEIPT_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV44Error(f"Release V43 authority drifted: {relative}")
    v43_receipt = _strict_json(_canonical_file(root, V43_RECEIPT_RELATIVE))
    if v43_receipt.get("test_sha256") != V43_TEST_SHA256:
        raise ReleaseWorkflowV44Error("Release V43 historical test authority drifted")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v44-verifier-receipt.v1",
        "release_path": RELEASE_V44_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V44_SHA256,
        "release_root_sha256": RELEASE_V44_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V43_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
    }:
        raise ReleaseWorkflowV44Error("Release V44 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v28 import verify_current_hud_acceptance
    from scripts.verify_r11_projection_retirement_v1 import (
        _load_blob_pack,
        load_retirement_record,
    )

    runtime = verify_current_hud_acceptance(root)
    retirement = load_retirement_record()
    blobs, head_files = _load_blob_pack()
    return {
        "transition": transition,
        "v43_predecessor": predecessor,
        "runtime": runtime,
        "retirement": retirement,
        "blob_count": len(blobs),
        "head_file_count": len(head_files),
        "receipt": receipt,
    }


def verify_release_workflow_v44(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except ReleaseWorkflowV43Error as exc:
        raise ReleaseWorkflowV44Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v44()
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
