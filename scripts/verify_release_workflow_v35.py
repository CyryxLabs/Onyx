"""Independent acyclic verifier for the current Release V35 receipt."""

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
RELEASE_V35_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v35.json"
)
RELEASE_V35_SHA256: Final = (
    "9095403955e2a66e03ad5610c5195673c8c34c6647c8cdbc1516dd61c33625ad"
)
RELEASE_V35_ROOT_SHA256: Final = (
    "4fb14fdf3b4d005b2b945fad6e9df2b52575daa730486331f61b7fbfa52ceb8d"
)
RELEASE_V34_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v34.json"
)
RELEASE_V34_SHA256: Final = (
    "043867379fb07fc8753a11665a06a90f72306d51031fae4fa1825d3d443c93aa"
)
RELEASE_V34_ROOT_SHA256: Final = (
    "0090d6962f14983968d292537285affd42540539e750ac7db3bf8cc735496548"
)
V34_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v34.py")
V34_VERIFIER_SHA256: Final = (
    "48be48acc7842935a6187f97dfb9697df5dbb4f29cda8e4259a3d978607af344"
)
V34_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V34_VERIFIER_RECEIPT.json"
)
V34_RECEIPT_SHA256: Final = (
    "f977a51cacbecf51ceeabfead61c34c8a56568bb1d560704c494bde06775d514"
)
V34_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v34.py")
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v35.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V35_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v35.py")
POLICY: Final = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}


class ReleaseWorkflowV35Error(RuntimeError):
    """Release V35 or its immutable V34 boundary drifted."""


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
        raise ReleaseWorkflowV35Error(f"noncanonical release path: {value!r}")
    candidate = root.joinpath(*parsed.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV35Error(f"release input unavailable: {value}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseWorkflowV35Error(f"release input escapes root: {value}") from exc
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV35Error(f"release input is linked: {value}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV35Error("duplicate release JSON key")
            result[key] = value
        return result

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise ReleaseWorkflowV35Error("release JSON is not canonical")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowV35Error("release JSON is invalid") from exc
    if type(value) is not dict:
        raise ReleaseWorkflowV35Error("release JSON must be an object")
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
        raise ReleaseWorkflowV35Error(f"{label} membership drifted")
    paths: list[str] = []
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or type(entry.get("path")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))) is None
        ):
            raise ReleaseWorkflowV35Error(f"{label} entry is malformed")
        paths.append(entry["path"])
    if paths != sorted(set(paths)):
        raise ReleaseWorkflowV35Error(f"{label} membership drifted")
    return entries


def verify_release_workflow_v35(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    v35_path = _canonical_file(root, RELEASE_V35_RELATIVE)
    if _sha256(v35_path) != RELEASE_V35_SHA256:
        raise ReleaseWorkflowV35Error("Release V35 fixture digest drifted")
    transition = _strict_json(v35_path)
    expected_keys = {
        "schema", "issued_at", "logical_sequence", "predecessor_clock_anomaly",
        "predecessor", "policy", "current_release_paths", "current_root_sha256",
    }
    if (
        set(transition) != expected_keys
        or transition.get("schema") != "onyx.release-workflow-transition.v35"
        or transition.get("logical_sequence") != 35
        or transition.get("predecessor_clock_anomaly") is not None
        or transition.get("predecessor") != {
            "path": RELEASE_V34_RELATIVE.as_posix(), "sha256": RELEASE_V34_SHA256
        }
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V35_ROOT_SHA256
        or _root(transition, 35) != RELEASE_V35_ROOT_SHA256
    ):
        raise ReleaseWorkflowV35Error("Release V35 contract drifted")

    v34_path = _canonical_file(root, RELEASE_V34_RELATIVE)
    if _sha256(v34_path) != RELEASE_V34_SHA256:
        raise ReleaseWorkflowV35Error("Release V34 predecessor digest drifted")
    predecessor = _strict_json(v34_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v34"
        or predecessor.get("logical_sequence") != 34
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V34_ROOT_SHA256
        or _root(predecessor, 34) != RELEASE_V34_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV35Error("Release V34 predecessor contract drifted")

    current_entries = _entries(transition, "Release V35")
    predecessor_entries = _entries(predecessor, "Release V34")
    current_hashes = {entry["path"]: entry["sha256"] for entry in current_entries}
    predecessor_hashes = {
        entry["path"]: entry["sha256"] for entry in predecessor_entries
    }
    for entry in current_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"]:
            raise ReleaseWorkflowV35Error(f"current release target drifted: {relative}")
        if predecessor_hashes.get(relative) == actual:
            raise ReleaseWorkflowV35Error(
                f"Release V35 contains unchanged predecessor target: {relative}"
            )
    for entry in predecessor_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] and current_hashes.get(relative) != actual:
            raise ReleaseWorkflowV35Error(
                f"Release V34 current target drifted: {relative}"
            )

    for relative, expected in (
        (V34_VERIFIER_RELATIVE, V34_VERIFIER_SHA256),
        (V34_RECEIPT_RELATIVE, V34_RECEIPT_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV35Error(f"Release V34 authority drifted: {relative}")
    if current_hashes.get(V34_TEST_RELATIVE.as_posix()) != _sha256(
        _canonical_file(root, V34_TEST_RELATIVE)
    ):
        raise ReleaseWorkflowV35Error("Release V34 test successor drifted")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v35-verifier-receipt.v1",
        "release_path": RELEASE_V35_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V35_SHA256,
        "release_root_sha256": RELEASE_V35_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V34_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "strict_successor",
    }:
        raise ReleaseWorkflowV35Error("Release V35 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v26 import verify_current_hud_acceptance

    runtime = verify_current_hud_acceptance(root)
    return {
        "transition": transition,
        "predecessor": predecessor,
        "runtime": runtime,
        "receipt": receipt,
    }


if __name__ == "__main__":
    verified = verify_release_workflow_v35()
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
