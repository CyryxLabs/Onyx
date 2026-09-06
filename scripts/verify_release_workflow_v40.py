"""Independent acyclic verifier for the current Release V40 receipt."""

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

RELEASE_V40_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v40.json"
)
RELEASE_V40_SHA256: Final = (
    "19886157609e46aad4372947cf79853012b3032f09676d08595d77da0a57c05e"
)
RELEASE_V40_ROOT_SHA256: Final = (
    "1e0f6fb02dbce32499d4538270f4ac9a0f65d86eb1bdab589c58fc18811827d8"
)
RELEASE_V39_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v39.json"
)
RELEASE_V39_SHA256: Final = (
    "f08504b3148394d7e6bf18128b0105149675434f0d1bbfa24ada67ca8f6b9876"
)
RELEASE_V39_ROOT_SHA256: Final = (
    "2ea6b96d612db8e3519db6b1ff7a2538deef1d2b876f896cb86d658ac4b05e9e"
)
V39_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v39.py")
V39_VERIFIER_SHA256: Final = (
    "a80c2de9760d75727bb8dcf7e684dbe3c2a43c023af9bd5e75ac8de3eab27150"
)
V39_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V39_VERIFIER_RECEIPT.json"
)
V39_RECEIPT_SHA256: Final = (
    "396dcbdda3e1ac70115eae516a44dc2466e6931272f11a23cb633714d3655193"
)
V39_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v39.py")
V39_TEST_SHA256: Final = (
    "68f8d42a02d7698a9111e2b920a6244d7b0152c642e4415d7982b9284bb72a15"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v40.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V40_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v40.py")
POLICY: Final = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}


class ReleaseWorkflowV40Error(RuntimeError):
    """Release V40 or its immutable V39 boundary drifted."""


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
        raise ReleaseWorkflowV40Error(f"noncanonical release path: {value!r}")
    candidate = root.joinpath(*parsed.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV40Error(f"release input unavailable: {value}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseWorkflowV40Error(f"release input escapes root: {value}") from exc
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV40Error(f"release input is linked: {value}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV40Error("duplicate release JSON key")
            result[key] = value
        return result

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise ReleaseWorkflowV40Error("release JSON is not canonical")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowV40Error("release JSON is invalid") from exc
    if type(value) is not dict:
        raise ReleaseWorkflowV40Error("release JSON must be an object")
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
        raise ReleaseWorkflowV40Error(f"{label} membership drifted")
    paths: list[str] = []
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or type(entry.get("path")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))) is None
        ):
            raise ReleaseWorkflowV40Error(f"{label} entry is malformed")
        paths.append(entry["path"])
    if paths != sorted(set(paths)):
        raise ReleaseWorkflowV40Error(f"{label} membership drifted")
    return entries


def verify_release_workflow_v40(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    v40_path = _canonical_file(root, RELEASE_V40_RELATIVE)
    if _sha256(v40_path) != RELEASE_V40_SHA256:
        raise ReleaseWorkflowV40Error("Release V40 fixture digest drifted")
    transition = _strict_json(v40_path)
    expected_keys = {
        "schema",
        "issued_at",
        "logical_sequence",
        "predecessor_clock_anomaly",
        "predecessor",
        "policy",
        "current_release_paths",
        "current_root_sha256",
    }
    if (
        set(transition) != expected_keys
        or transition.get("schema") != "onyx.release-workflow-transition.v40"
        or transition.get("logical_sequence") != 40
        or transition.get("predecessor_clock_anomaly") is not None
        or transition.get("predecessor")
        != {"path": RELEASE_V39_RELATIVE.as_posix(), "sha256": RELEASE_V39_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V40_ROOT_SHA256
        or _root(transition, 40) != RELEASE_V40_ROOT_SHA256
    ):
        raise ReleaseWorkflowV40Error("Release V40 contract drifted")

    v39_path = _canonical_file(root, RELEASE_V39_RELATIVE)
    if _sha256(v39_path) != RELEASE_V39_SHA256:
        raise ReleaseWorkflowV40Error("Release V39 predecessor digest drifted")
    predecessor = _strict_json(v39_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v39"
        or predecessor.get("logical_sequence") != 39
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V39_ROOT_SHA256
        or _root(predecessor, 39) != RELEASE_V39_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV40Error("Release V39 predecessor contract drifted")

    current_entries = _entries(transition, "Release V40")
    predecessor_entries = _entries(predecessor, "Release V39")
    current_hashes = {entry["path"]: entry["sha256"] for entry in current_entries}
    predecessor_hashes = {
        entry["path"]: entry["sha256"] for entry in predecessor_entries
    }
    for entry in current_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"]:
            raise ReleaseWorkflowV40Error(f"current release target drifted: {relative}")
        if predecessor_hashes.get(relative) == actual:
            raise ReleaseWorkflowV40Error(
                f"Release V40 contains unchanged predecessor target: {relative}"
            )
    for entry in predecessor_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] and current_hashes.get(relative) != actual:
            raise ReleaseWorkflowV40Error(
                f"Release V39 current target drifted: {relative}"
            )

    for relative, expected in (
        (V39_VERIFIER_RELATIVE, V39_VERIFIER_SHA256),
        (V39_RECEIPT_RELATIVE, V39_RECEIPT_SHA256),
        (V39_TEST_RELATIVE, V39_TEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV40Error(f"Release V39 authority drifted: {relative}")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v40-verifier-receipt.v1",
        "release_path": RELEASE_V40_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V40_SHA256,
        "release_root_sha256": RELEASE_V40_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V39_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "strict_successor",
    }:
        raise ReleaseWorkflowV40Error("Release V40 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v27 import verify_current_hud_acceptance

    runtime = verify_current_hud_acceptance(root)
    return {
        "transition": transition,
        "v39_predecessor": predecessor,
        "runtime": runtime,
        "receipt": receipt,
    }


if __name__ == "__main__":
    verified = verify_release_workflow_v40()
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
