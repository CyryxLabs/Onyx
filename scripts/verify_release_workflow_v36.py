"""Independent acyclic verifier for the current Release V36 receipt."""

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
RELEASE_V36_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v36.json"
)
RELEASE_V36_SHA256: Final = (
    "1a9e63b28c251dcd505c3a5804316c1d6297e568c7dc53de622126eaa7a1b236"
)
RELEASE_V36_ROOT_SHA256: Final = (
    "a9ebbf21df121bcec09dec7bf713cac8010830e1d534b0ab8c4ea22e5d57e4c7"
)
RELEASE_V35_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v35.json"
)
RELEASE_V35_SHA256: Final = (
    "9095403955e2a66e03ad5610c5195673c8c34c6647c8cdbc1516dd61c33625ad"
)
RELEASE_V35_ROOT_SHA256: Final = (
    "4fb14fdf3b4d005b2b945fad6e9df2b52575daa730486331f61b7fbfa52ceb8d"
)
V35_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v35.py")
V35_VERIFIER_SHA256: Final = (
    "1d75ce417c58c36495553d3c56b0eef9dff3ca60d1d3b18512ae913df091b453"
)
V35_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V35_VERIFIER_RECEIPT.json"
)
V35_RECEIPT_SHA256: Final = (
    "f35b8fb1076a6a8f06c4a26e7ab6b5205a3b4a04e563fec261113e6b9785330c"
)
V35_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v35.py")
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v36.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V36_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v36.py")
POLICY: Final = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}


class ReleaseWorkflowV36Error(RuntimeError):
    """Release V36 or its immutable V35 boundary drifted."""


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
        raise ReleaseWorkflowV36Error(f"noncanonical release path: {value!r}")
    candidate = root.joinpath(*parsed.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV36Error(f"release input unavailable: {value}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseWorkflowV36Error(f"release input escapes root: {value}") from exc
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV36Error(f"release input is linked: {value}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV36Error("duplicate release JSON key")
            result[key] = value
        return result

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise ReleaseWorkflowV36Error("release JSON is not canonical")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowV36Error("release JSON is invalid") from exc
    if type(value) is not dict:
        raise ReleaseWorkflowV36Error("release JSON must be an object")
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
        raise ReleaseWorkflowV36Error(f"{label} membership drifted")
    paths: list[str] = []
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or type(entry.get("path")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))) is None
        ):
            raise ReleaseWorkflowV36Error(f"{label} entry is malformed")
        paths.append(entry["path"])
    if paths != sorted(set(paths)):
        raise ReleaseWorkflowV36Error(f"{label} membership drifted")
    return entries


def verify_release_workflow_v36(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    v36_path = _canonical_file(root, RELEASE_V36_RELATIVE)
    if _sha256(v36_path) != RELEASE_V36_SHA256:
        raise ReleaseWorkflowV36Error("Release V36 fixture digest drifted")
    transition = _strict_json(v36_path)
    expected_keys = {
        "schema", "issued_at", "logical_sequence", "predecessor_clock_anomaly",
        "predecessor", "policy", "current_release_paths", "current_root_sha256",
    }
    if (
        set(transition) != expected_keys
        or transition.get("schema") != "onyx.release-workflow-transition.v36"
        or transition.get("logical_sequence") != 36
        or transition.get("predecessor_clock_anomaly") is not None
        or transition.get("predecessor") != {
            "path": RELEASE_V35_RELATIVE.as_posix(), "sha256": RELEASE_V35_SHA256
        }
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V36_ROOT_SHA256
        or _root(transition, 36) != RELEASE_V36_ROOT_SHA256
    ):
        raise ReleaseWorkflowV36Error("Release V36 contract drifted")

    v35_path = _canonical_file(root, RELEASE_V35_RELATIVE)
    if _sha256(v35_path) != RELEASE_V35_SHA256:
        raise ReleaseWorkflowV36Error("Release V35 predecessor digest drifted")
    predecessor = _strict_json(v35_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v35"
        or predecessor.get("logical_sequence") != 35
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V35_ROOT_SHA256
        or _root(predecessor, 35) != RELEASE_V35_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV36Error("Release V35 predecessor contract drifted")

    current_entries = _entries(transition, "Release V36")
    predecessor_entries = _entries(predecessor, "Release V35")
    current_hashes = {entry["path"]: entry["sha256"] for entry in current_entries}
    predecessor_hashes = {
        entry["path"]: entry["sha256"] for entry in predecessor_entries
    }
    for entry in current_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"]:
            raise ReleaseWorkflowV36Error(f"current release target drifted: {relative}")
        if predecessor_hashes.get(relative) == actual:
            raise ReleaseWorkflowV36Error(
                f"Release V36 contains unchanged predecessor target: {relative}"
            )
    for entry in predecessor_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] and current_hashes.get(relative) != actual:
            raise ReleaseWorkflowV36Error(
                f"Release V35 current target drifted: {relative}"
            )

    for relative, expected in (
        (V35_VERIFIER_RELATIVE, V35_VERIFIER_SHA256),
        (V35_RECEIPT_RELATIVE, V35_RECEIPT_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV36Error(f"Release V35 authority drifted: {relative}")
    if current_hashes.get(V35_TEST_RELATIVE.as_posix()) != _sha256(
        _canonical_file(root, V35_TEST_RELATIVE)
    ):
        raise ReleaseWorkflowV36Error("Release V35 test successor drifted")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v36-verifier-receipt.v1",
        "release_path": RELEASE_V36_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V36_SHA256,
        "release_root_sha256": RELEASE_V36_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V35_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "strict_successor",
    }:
        raise ReleaseWorkflowV36Error("Release V36 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v26 import verify_current_hud_acceptance

    runtime = verify_current_hud_acceptance(root)
    return {
        "transition": transition,
        "predecessor": predecessor,
        "runtime": runtime,
        "receipt": receipt,
    }


if __name__ == "__main__":
    verified = verify_release_workflow_v36()
    print(
        json.dumps(
            {
                "release_schema": verified["transition"]["schema"],
                "release_root_sha256": verified["transition"]["current_root_sha256"],
                "runtime_root_sha256": verified["runtime"]["artifact_root_sha256"],
            },
            sort_keys=True,
        )
    )
