"""Independent acyclic verifier for the current Release V37 receipt."""

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
RELEASE_V37_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v37.json"
)
RELEASE_V37_SHA256: Final = (
    "ebe6eff3d8c00eaeafa657fe99287434181de5fc7c0521be1f05d7906fb93cf5"
)
RELEASE_V37_ROOT_SHA256: Final = (
    "31374474b7f76502ba3a833fc7efa62247f57df08fe407e91cc13f1548f03aeb"
)
RELEASE_V36_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v36.json"
)
RELEASE_V36_SHA256: Final = (
    "1a9e63b28c251dcd505c3a5804316c1d6297e568c7dc53de622126eaa7a1b236"
)
RELEASE_V36_ROOT_SHA256: Final = (
    "a9ebbf21df121bcec09dec7bf713cac8010830e1d534b0ab8c4ea22e5d57e4c7"
)
V36_VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v36.py")
V36_VERIFIER_SHA256: Final = (
    "9bc71c2ff85134e701197f7f4812f321644bc26aa7364de9d122e40f61d999bf"
)
V36_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V36_VERIFIER_RECEIPT.json"
)
V36_RECEIPT_SHA256: Final = (
    "df55fc9ec3e4c9d632f68d1830c00d6b471bc2737cf4b032eebced4ec4594b5f"
)
V36_TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v36.py")
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v37.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V37_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v37.py")
POLICY: Final = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}


class ReleaseWorkflowV37Error(RuntimeError):
    """Release V37 or its immutable V36 boundary drifted."""


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
        raise ReleaseWorkflowV37Error(f"noncanonical release path: {value!r}")
    candidate = root.joinpath(*parsed.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV37Error(f"release input unavailable: {value}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseWorkflowV37Error(
            f"release input escapes root: {value}"
        ) from exc
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV37Error(f"release input is linked: {value}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV37Error("duplicate release JSON key")
            result[key] = value
        return result

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise ReleaseWorkflowV37Error("release JSON is not canonical")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowV37Error("release JSON is invalid") from exc
    if type(value) is not dict:
        raise ReleaseWorkflowV37Error("release JSON must be an object")
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
        raise ReleaseWorkflowV37Error(f"{label} membership drifted")
    paths: list[str] = []
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or type(entry.get("path")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))) is None
        ):
            raise ReleaseWorkflowV37Error(f"{label} entry is malformed")
        paths.append(entry["path"])
    if paths != sorted(set(paths)):
        raise ReleaseWorkflowV37Error(f"{label} membership drifted")
    return entries


def verify_release_workflow_v37(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    v37_path = _canonical_file(root, RELEASE_V37_RELATIVE)
    if _sha256(v37_path) != RELEASE_V37_SHA256:
        raise ReleaseWorkflowV37Error("Release V37 fixture digest drifted")
    transition = _strict_json(v37_path)
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
        or transition.get("schema") != "onyx.release-workflow-transition.v37"
        or transition.get("logical_sequence") != 37
        or transition.get("predecessor_clock_anomaly") is not None
        or transition.get("predecessor")
        != {"path": RELEASE_V36_RELATIVE.as_posix(), "sha256": RELEASE_V36_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V37_ROOT_SHA256
        or _root(transition, 37) != RELEASE_V37_ROOT_SHA256
    ):
        raise ReleaseWorkflowV37Error("Release V37 contract drifted")

    v36_path = _canonical_file(root, RELEASE_V36_RELATIVE)
    if _sha256(v36_path) != RELEASE_V36_SHA256:
        raise ReleaseWorkflowV37Error("Release V36 predecessor digest drifted")
    predecessor = _strict_json(v36_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v36"
        or predecessor.get("logical_sequence") != 36
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V36_ROOT_SHA256
        or _root(predecessor, 36) != RELEASE_V36_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV37Error("Release V36 predecessor contract drifted")

    current_entries = _entries(transition, "Release V37")
    predecessor_entries = _entries(predecessor, "Release V36")
    current_hashes = {entry["path"]: entry["sha256"] for entry in current_entries}
    predecessor_hashes = {
        entry["path"]: entry["sha256"] for entry in predecessor_entries
    }
    for entry in current_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"]:
            raise ReleaseWorkflowV37Error(
                f"current release target drifted: {relative}"
            )
        if predecessor_hashes.get(relative) == actual:
            raise ReleaseWorkflowV37Error(
                f"Release V37 contains unchanged predecessor target: {relative}"
            )
    for entry in predecessor_entries:
        relative = entry["path"]
        actual = _sha256(_canonical_file(root, relative))
        if actual != entry["sha256"] and current_hashes.get(relative) != actual:
            raise ReleaseWorkflowV37Error(
                f"Release V36 current target drifted: {relative}"
            )

    for relative, expected in (
        (V36_VERIFIER_RELATIVE, V36_VERIFIER_SHA256),
        (V36_RECEIPT_RELATIVE, V36_RECEIPT_SHA256),
    ):
        if _sha256(_canonical_file(root, relative)) != expected:
            raise ReleaseWorkflowV37Error(
                f"Release V36 authority drifted: {relative}"
            )
    if current_hashes.get(V36_TEST_RELATIVE.as_posix()) != _sha256(
        _canonical_file(root, V36_TEST_RELATIVE)
    ):
        raise ReleaseWorkflowV37Error("Release V36 test successor drifted")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v37-verifier-receipt.v1",
        "release_path": RELEASE_V37_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V37_SHA256,
        "release_root_sha256": RELEASE_V37_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V36_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "strict_successor",
    }:
        raise ReleaseWorkflowV37Error("Release V37 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v26 import verify_current_hud_acceptance

    runtime = verify_current_hud_acceptance(root)
    return {
        "transition": transition,
        "predecessor": predecessor,
        "runtime": runtime,
        "receipt": receipt,
    }


if __name__ == "__main__":
    verified = verify_release_workflow_v37()
    print(
        json.dumps(
            {
                "release_schema": verified["transition"]["schema"],
                "release_root_sha256": verified["transition"][
                    "current_root_sha256"
                ],
                "runtime_root_sha256": verified["runtime"][
                    "artifact_root_sha256"
                ],
            },
            sort_keys=True,
        )
    )
