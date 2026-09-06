"""Independent acyclic verifier for the current Release V42 receipt."""

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

RELEASE_V42_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v42.json"
)
RELEASE_V42_SHA256: Final = (
    "04a0e56126dc975eed72061bf51e672aad0433345d72fd9752076e4ed7f15286"
)
RELEASE_V42_ROOT_SHA256: Final = (
    "1ca6bf7f194f88f43646e57fa8c82c8661194bf7fd6184f239e37892c6512dc9"
)
RELEASE_V41_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v41.json"
)
RELEASE_V41_SHA256: Final = (
    "8bce34bf6b5b18c3f1b369633501b4eb8d02cec1a5898694d126bb89398115af"
)
RELEASE_V41_ROOT_SHA256: Final = (
    "ec1040dd9ef0dfad012a9609b77835a2251819a11e2340529407b2e952d8f950"
)
V41_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v41.py")
V41_VERIFIER_SHA256: Final = (
    "da14bac8767c2ff016c86ad3fbc06dac5dfd3609c1ea280917a6cb292f460e34"
)
V41_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V41_VERIFIER_RECEIPT.json"
)
V41_RECEIPT_SHA256: Final = (
    "13936d0dd38432cda7ca3512d6eeccc8212174a2e477db7d6eba7b4b250bfd74"
)
V41_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v41.py")
V41_TEST_SHA256: Final = (
    "f47d092489f0fcc8b5b94a0452efb58a7e5e15a671113bdee6541c202349ee47"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v42.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V42_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v42.py")
POLICY: Final = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}
EXPECTED_CLOCK_ANOMALY: Final = {
    "predecessor_issued_at": "2026-08-10T19:00:00-04:00",
    "observed_at": "2026-08-10T16:10:00-04:00",
    "reason": "predecessor_future_dated",
}


class ReleaseWorkflowV42Error(RuntimeError):
    """Release V42 or its immutable V41 boundary drifted."""


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
        raise ReleaseWorkflowV42Error(f"noncanonical release path: {value!r}")
    candidate = root.joinpath(*parsed.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV42Error(f"release input unavailable: {value}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseWorkflowV42Error(f"release input escapes root: {value}") from exc
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV42Error(f"release input is linked: {value}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV42Error("duplicate release JSON key")
            result[key] = value
        return result

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise ReleaseWorkflowV42Error("release JSON is not canonical")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowV42Error("release JSON is invalid") from exc
    if type(value) is not dict:
        raise ReleaseWorkflowV42Error("release JSON must be an object")
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
        raise ReleaseWorkflowV42Error(f"{label} membership drifted")
    paths: list[str] = []
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or type(entry.get("path")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))) is None
        ):
            raise ReleaseWorkflowV42Error(f"{label} entry is malformed")
        paths.append(entry["path"])
    if paths != sorted(set(paths)):
        raise ReleaseWorkflowV42Error(f"{label} membership drifted")
    return entries


def _parse_rfc3339(value: object, *, label: str) -> datetime:
    if type(value) is not str or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        value,
    ) is None:
        raise ReleaseWorkflowV42Error(f"{label} is not timezone-aware RFC3339")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseWorkflowV42Error(f"{label} is not timezone-aware RFC3339")
    return parsed


def _validate_chronology(
    transition: dict[str, object], predecessor: dict[str, object]
) -> None:
    issued = _parse_rfc3339(transition.get("issued_at"), label="Release V42 issued_at")
    predecessor_issued = _parse_rfc3339(
        predecessor.get("issued_at"), label="Release V41 issued_at"
    )
    if transition.get("logical_sequence") != predecessor.get("logical_sequence") + 1:
        raise ReleaseWorkflowV42Error("Release V42 logical sequence drifted")
    if issued >= predecessor_issued:
        raise ReleaseWorkflowV42Error("Release V42 has a false predecessor clock anomaly")
    if transition.get("predecessor_clock_anomaly") != EXPECTED_CLOCK_ANOMALY:
        raise ReleaseWorkflowV42Error("Release V42 clock anomaly drifted")
    anomaly = transition["predecessor_clock_anomaly"]
    if (
        anomaly["predecessor_issued_at"] != predecessor["issued_at"]
        or anomaly["observed_at"] != transition["issued_at"]
    ):
        raise ReleaseWorkflowV42Error("Release V42 clock anomaly drifted")


def verify_release_workflow_v42(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    v42_path = _canonical_file(root, RELEASE_V42_RELATIVE)
    if _sha256(v42_path) != RELEASE_V42_SHA256:
        raise ReleaseWorkflowV42Error("Release V42 fixture digest drifted")
    transition = _strict_json(v42_path)
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
        or transition.get("schema") != "onyx.release-workflow-transition.v42"
        or transition.get("logical_sequence") != 42
        or transition.get("predecessor")
        != {"path": RELEASE_V41_RELATIVE.as_posix(), "sha256": RELEASE_V41_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V42_ROOT_SHA256
        or _root(transition, 42) != RELEASE_V42_ROOT_SHA256
    ):
        raise ReleaseWorkflowV42Error("Release V42 contract drifted")

    v41_path = _canonical_file(root, RELEASE_V41_RELATIVE)
    if _sha256(v41_path) != RELEASE_V41_SHA256:
        raise ReleaseWorkflowV42Error("Release V41 predecessor digest drifted")
    predecessor = _strict_json(v41_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v41"
        or predecessor.get("logical_sequence") != 41
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V41_ROOT_SHA256
        or _root(predecessor, 41) != RELEASE_V41_ROOT_SHA256
    ):
        raise ReleaseWorkflowV42Error("Release V41 predecessor contract drifted")
    _validate_chronology(transition, predecessor)

    current_entries = _entries(transition, "Release V42")
    predecessor_entries = _entries(predecessor, "Release V41")
    current_hashes = {entry["path"]: entry["sha256"] for entry in current_entries}
    predecessor_hashes = {
        entry["path"]: entry["sha256"] for entry in predecessor_entries
    }
    for entry in current_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"]:
            raise ReleaseWorkflowV42Error(f"current release target drifted: {relative}")
        if predecessor_hashes.get(relative) == actual:
            raise ReleaseWorkflowV42Error(
                f"Release V42 contains unchanged predecessor target: {relative}"
            )
    for entry in predecessor_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] and current_hashes.get(relative) != actual:
            raise ReleaseWorkflowV42Error(
                f"Release V41 current target drifted: {relative}"
            )

    for relative, expected in (
        (V41_VERIFIER_RELATIVE, V41_VERIFIER_SHA256),
        (V41_RECEIPT_RELATIVE, V41_RECEIPT_SHA256),
        (V41_TEST_RELATIVE, V41_TEST_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV42Error(f"Release V41 authority drifted: {relative}")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v42-verifier-receipt.v1",
        "release_path": RELEASE_V42_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V42_SHA256,
        "release_root_sha256": RELEASE_V42_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V41_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "logical_successor_with_predecessor_clock_anomaly",
    }:
        raise ReleaseWorkflowV42Error("Release V42 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v28 import verify_current_hud_acceptance

    runtime = verify_current_hud_acceptance(root)
    return {
        "transition": transition,
        "v41_predecessor": predecessor,
        "runtime": runtime,
        "receipt": receipt,
    }


if __name__ == "__main__":
    verified = verify_release_workflow_v42()
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
