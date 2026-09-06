"""Independent verifier for the portable-correction Release V45 successor."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.verify_release_workflow_v44 import (  # noqa: E402
    POLICY,
    ReleaseWorkflowV43Error,
    ReleaseWorkflowV44Error,
    _canonical_file,
    _entries,
    _issued,
    _root,
    _sha256,
    _strict_json,
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
RELEASE_V44_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v44.json"
)
RELEASE_V44_SHA256: Final = (
    "0d89a2a5eff3a6e0bc155ede25000a331921ae4096f952c3f1c70644e112804d"
)
RELEASE_V44_ROOT_SHA256: Final = (
    "7f9e88230530610675be881d40bf50462917d1bb085ce0fd0517a8ec7fe9e493"
)
V44_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v44.py")
V44_VERIFIER_SHA256: Final = (
    "f46c2ddffc217c1cd34f1e305c17a54b44df48e49c9b8a7ffa1e56c6a670e6dc"
)
V44_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V44_VERIFIER_RECEIPT.json"
)
V44_RECEIPT_SHA256: Final = (
    "b5f85a6bff61d5d263ed9969e016f2cacc0aa04d20bbbf07cc830d0d455404a0"
)
V44_TEST_SHA256: Final = (
    "cce8e7e7b23e6117753d0511b63a96bd6e102bc1cfe177aa65fb62b24d43deea"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v45.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V45_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v45.py")


class ReleaseWorkflowV45Error(RuntimeError):
    """Release V45 or its immutable V44 boundary drifted."""


def _verify(project: Path) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    v45_path = _canonical_file(root, RELEASE_V45_RELATIVE)
    if _sha256(v45_path) != RELEASE_V45_SHA256:
        raise ReleaseWorkflowV45Error("Release V45 fixture digest drifted")
    transition = _strict_json(v45_path)
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
        or transition.get("schema") != "onyx.release-workflow-transition.v45"
        or transition.get("logical_sequence") != 45
        or transition.get("predecessor")
        != {"path": RELEASE_V44_RELATIVE.as_posix(), "sha256": RELEASE_V44_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V45_ROOT_SHA256
        or _root(transition, 45) != RELEASE_V45_ROOT_SHA256
    ):
        raise ReleaseWorkflowV45Error("Release V45 contract drifted")

    v44_path = _canonical_file(root, RELEASE_V44_RELATIVE)
    if _sha256(v44_path) != RELEASE_V44_SHA256:
        raise ReleaseWorkflowV45Error("Release V44 predecessor digest drifted")
    predecessor = _strict_json(v44_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v44"
        or predecessor.get("logical_sequence") != 44
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V44_ROOT_SHA256
        or _root(predecessor, 44) != RELEASE_V44_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V45 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V44 issued_at")
    ):
        raise ReleaseWorkflowV45Error("Release V44 predecessor contract drifted")

    current_entries = _entries(transition, "Release V45")
    predecessor_entries = _entries(predecessor, "Release V44")
    current_hashes = {entry["path"]: entry["sha256"] for entry in current_entries}
    predecessor_hashes = {
        entry["path"]: entry["sha256"] for entry in predecessor_entries
    }
    for entry in current_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] or predecessor_hashes.get(relative) == actual:
            raise ReleaseWorkflowV45Error(f"current release target drifted: {relative}")
    for entry in predecessor_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] and current_hashes.get(relative) != actual:
            raise ReleaseWorkflowV45Error(
                f"Release V44 current target drifted: {relative}"
            )

    for relative, expected in (
        (V44_VERIFIER_RELATIVE, V44_VERIFIER_SHA256),
        (V44_RECEIPT_RELATIVE, V44_RECEIPT_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV45Error(f"Release V44 authority drifted: {relative}")
    v44_receipt = _strict_json(_canonical_file(root, V44_RECEIPT_RELATIVE))
    if v44_receipt.get("test_sha256") != V44_TEST_SHA256:
        raise ReleaseWorkflowV45Error("Release V44 historical test authority drifted")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v45-verifier-receipt.v1",
        "release_path": RELEASE_V45_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V45_SHA256,
        "release_root_sha256": RELEASE_V45_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V44_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
    }:
        raise ReleaseWorkflowV45Error("Release V45 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v29 import verify_current_hud_acceptance
    from scripts.verify_r11_projection_retirement_v1 import (
        _load_blob_pack,
        load_retirement_record,
    )

    runtime = verify_current_hud_acceptance(root)
    retirement = load_retirement_record()
    blobs, head_files = _load_blob_pack()
    return {
        "transition": transition,
        "v44_predecessor": predecessor,
        "runtime": runtime,
        "retirement": retirement,
        "blob_count": len(blobs),
        "head_file_count": len(head_files),
        "receipt": receipt,
    }


def verify_release_workflow_v45(project: Path = PROJECT) -> dict[str, object]:
    try:
        return _verify(project)
    except (ReleaseWorkflowV43Error, ReleaseWorkflowV44Error) as exc:
        raise ReleaseWorkflowV45Error(str(exc)) from exc


if __name__ == "__main__":
    verified = verify_release_workflow_v45()
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
