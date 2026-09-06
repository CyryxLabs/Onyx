"""Independent verifier for the hermetic Release V43 successor."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Final


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

RELEASE_V43_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v43.json"
)
RELEASE_V43_SHA256: Final = (
    "98cd93b35a293f46b83836ecff984c7111a53bf6db7496e4f27b29929e73432f"
)
RELEASE_V43_ROOT_SHA256: Final = (
    "66eb5228407317407b8ae084ebe930b7e7c3d45139cfe5ba56d3641bcbe1573b"
)
RELEASE_V42_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v42.json"
)
RELEASE_V42_SHA256: Final = (
    "04a0e56126dc975eed72061bf51e672aad0433345d72fd9752076e4ed7f15286"
)
RELEASE_V42_ROOT_SHA256: Final = (
    "1ca6bf7f194f88f43646e57fa8c82c8661194bf7fd6184f239e37892c6512dc9"
)
V42_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v42.py")
V42_VERIFIER_SHA256: Final = (
    "221e539ff63f359011f50299c95c09c01bc66713566f2d30f763e3d2276feff5"
)
V42_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V42_VERIFIER_RECEIPT.json"
)
V42_RECEIPT_SHA256: Final = (
    "75aa680f4703d2b08f24f0cd5d9e9d2ff2215431adb21b5ac652ecca95903fa0"
)
V42_TEST_SHA256: Final = (
    "f9a6bab1ba29e3bd22abacdd035e64094babb98aabb1f749c8697af7283196bc"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v43.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V43_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v43.py")
POLICY: Final = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}


class ReleaseWorkflowV43Error(RuntimeError):
    """Release V43 or its immutable V42 boundary drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: str | Path) -> Path:
    value = relative.as_posix() if isinstance(relative, Path) else relative
    parsed = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or parsed.is_absolute()
        or parsed.as_posix() != value
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ReleaseWorkflowV43Error(f"noncanonical release path: {value!r}")
    candidate = root.joinpath(*parsed.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV43Error(f"release input unavailable: {value}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseWorkflowV43Error(f"release input escapes root: {value}") from exc
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV43Error(f"release input is linked: {value}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV43Error("duplicate release JSON key")
            result[key] = value
        return result

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise ReleaseWorkflowV43Error("release JSON is not canonical")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowV43Error("release JSON is invalid") from exc
    if type(value) is not dict:
        raise ReleaseWorkflowV43Error("release JSON must be an object")
    return value


def _frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _root(record: dict[str, object], version: int) -> str:
    digest = hashlib.sha256()
    digest.update(f"ONYX-RELEASE-WORKFLOW-TRANSITION-V{version}\0".encode())
    _frame(digest, record["issued_at"])
    _frame(digest, str(record["logical_sequence"]))
    if version == 42:
        anomaly = record["predecessor_clock_anomaly"]
        for key in ("predecessor_issued_at", "observed_at", "reason"):
            _frame(digest, anomaly[key])
    predecessor = record["predecessor"]
    _frame(digest, predecessor["path"])
    _frame(digest, predecessor["sha256"])
    for entry in record["current_release_paths"]:
        _frame(digest, entry["path"])
        _frame(digest, entry["sha256"])
    return digest.hexdigest()


def _entries(record: dict[str, object], label: str) -> list[dict[str, str]]:
    entries = record.get("current_release_paths")
    if type(entries) is not list or not entries:
        raise ReleaseWorkflowV43Error(f"{label} membership drifted")
    paths: list[str] = []
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or type(entry.get("path")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))) is None
        ):
            raise ReleaseWorkflowV43Error(f"{label} entry is malformed")
        paths.append(entry["path"])
    if paths != sorted(set(paths)):
        raise ReleaseWorkflowV43Error(f"{label} membership drifted")
    return entries


def _issued(value: object, label: str) -> datetime:
    if type(value) is not str or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        value,
    ) is None:
        raise ReleaseWorkflowV43Error(f"{label} is not timezone-aware RFC3339")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseWorkflowV43Error(f"{label} is not timezone-aware RFC3339")
    return parsed


def verify_release_workflow_v43(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    v43_path = _canonical_file(root, RELEASE_V43_RELATIVE)
    if _sha256(v43_path) != RELEASE_V43_SHA256:
        raise ReleaseWorkflowV43Error("Release V43 fixture digest drifted")
    transition = _strict_json(v43_path)
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
        or transition.get("schema") != "onyx.release-workflow-transition.v43"
        or transition.get("logical_sequence") != 43
        or transition.get("predecessor")
        != {"path": RELEASE_V42_RELATIVE.as_posix(), "sha256": RELEASE_V42_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V43_ROOT_SHA256
        or _root(transition, 43) != RELEASE_V43_ROOT_SHA256
    ):
        raise ReleaseWorkflowV43Error("Release V43 contract drifted")

    v42_path = _canonical_file(root, RELEASE_V42_RELATIVE)
    if _sha256(v42_path) != RELEASE_V42_SHA256:
        raise ReleaseWorkflowV43Error("Release V42 predecessor digest drifted")
    predecessor = _strict_json(v42_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v42"
        or predecessor.get("logical_sequence") != 42
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V42_ROOT_SHA256
        or _root(predecessor, 42) != RELEASE_V42_ROOT_SHA256
        or _issued(transition.get("issued_at"), "Release V43 issued_at")
        <= _issued(predecessor.get("issued_at"), "Release V42 issued_at")
    ):
        raise ReleaseWorkflowV43Error("Release V42 predecessor contract drifted")

    current_entries = _entries(transition, "Release V43")
    predecessor_entries = _entries(predecessor, "Release V42")
    current_hashes = {entry["path"]: entry["sha256"] for entry in current_entries}
    predecessor_hashes = {
        entry["path"]: entry["sha256"] for entry in predecessor_entries
    }
    for entry in current_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] or predecessor_hashes.get(relative) == actual:
            raise ReleaseWorkflowV43Error(f"current release target drifted: {relative}")
    for entry in predecessor_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] and current_hashes.get(relative) != actual:
            raise ReleaseWorkflowV43Error(
                f"Release V42 current target drifted: {relative}"
            )

    for relative, expected in (
        (V42_VERIFIER_RELATIVE, V42_VERIFIER_SHA256),
        (V42_RECEIPT_RELATIVE, V42_RECEIPT_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV43Error(f"Release V42 authority drifted: {relative}")
    v42_receipt = _strict_json(_canonical_file(root, V42_RECEIPT_RELATIVE))
    if v42_receipt.get("test_sha256") != V42_TEST_SHA256:
        raise ReleaseWorkflowV43Error("Release V42 historical test authority drifted")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v43-verifier-receipt.v1",
        "release_path": RELEASE_V43_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V43_SHA256,
        "release_root_sha256": RELEASE_V43_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V42_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "normal_successor",
    }:
        raise ReleaseWorkflowV43Error("Release V43 verifier receipt drifted")

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
        "v42_predecessor": predecessor,
        "runtime": runtime,
        "retirement": retirement,
        "blob_count": len(blobs),
        "head_file_count": len(head_files),
        "receipt": receipt,
    }


if __name__ == "__main__":
    verified = verify_release_workflow_v43()
    print(
        json.dumps(
            {
                "blob_count": verified["blob_count"],
                "release_root_sha256": verified["transition"]["current_root_sha256"],
                "release_schema": verified["transition"]["schema"],
                "runtime_root_sha256": verified["runtime"]["artifact_root_sha256"],
            },
            sort_keys=True,
        )
    )
