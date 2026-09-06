"""Independent, acyclic verifier for the current Release V32 receipt."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Final


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

RELEASE_V32_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v32.json"
)
RELEASE_V32_SHA256: Final = (
    "78f02874ee159ce60428ff71701ca3b1dab3159e61ff69fed4e1dad90f46b251"
)
RELEASE_V31_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v31.json"
)
RELEASE_V31_SHA256: Final = (
    "372e86d759f326fbc9198f9c6d1b49032f7db849f6e4bfb5bc7d93f6e6389307"
)
RELEASE_V32_ROOT_SHA256: Final = (
    "abec138b6a40ff211163bf33ca1648739baa9635d5f5cf281be76ac63bc92480"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v32.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V32_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v32.py")
POLICY: Final = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}


class ReleaseWorkflowV32Error(RuntimeError):
    """Release V32 or its externally anchored verifier receipt drifted."""


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
        raise ReleaseWorkflowV32Error(f"noncanonical release path: {value!r}")
    candidate = root.joinpath(*parsed.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV32Error(f"release input unavailable: {value}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ReleaseWorkflowV32Error(f"release input escapes root: {value}") from exc
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV32Error(f"release input is linked: {value}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV32Error("duplicate release JSON key")
            result[key] = value
        return result

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise ReleaseWorkflowV32Error("release JSON is not canonical")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowV32Error("release JSON is invalid") from exc
    if type(value) is not dict:
        raise ReleaseWorkflowV32Error("release JSON must be an object")
    return value


def _frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _root(record: dict[str, object], domain: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    predecessor = record["predecessor"]
    _frame(digest, predecessor["path"])
    _frame(digest, predecessor["sha256"])
    for entry in record["current_release_paths"]:
        _frame(digest, entry["path"])
        _frame(digest, entry["sha256"])
    return digest.hexdigest()


def _valid_sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def verify_release_workflow_v32(project: Path = PROJECT) -> dict[str, object]:
    """Validate V32, V31, every current path, receipt and full V26 closure."""

    root = Path(project).resolve(strict=True)
    v32_path = _canonical_file(root, RELEASE_V32_RELATIVE)
    if _sha256(v32_path) != RELEASE_V32_SHA256:
        raise ReleaseWorkflowV32Error("Release V32 fixture digest drifted")
    transition = _strict_json(v32_path)
    if (
        set(transition) != {
            "schema", "issued_at", "predecessor", "policy",
            "current_release_paths", "current_root_sha256",
        }
        or transition.get("schema") != "onyx.release-workflow-transition.v32"
        or transition.get("predecessor") != {
            "path": RELEASE_V31_RELATIVE.as_posix(),
            "sha256": RELEASE_V31_SHA256,
        }
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V32_ROOT_SHA256
    ):
        raise ReleaseWorkflowV32Error("Release V32 contract drifted")

    v31_path = _canonical_file(root, RELEASE_V31_RELATIVE)
    if _sha256(v31_path) != RELEASE_V31_SHA256:
        raise ReleaseWorkflowV32Error("Release V31 predecessor digest drifted")
    predecessor = _strict_json(v31_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v31"
        or predecessor.get("policy") != POLICY
        or _root(predecessor, b"ONYX-RELEASE-WORKFLOW-TRANSITION-V31\0")
        != predecessor.get("current_root_sha256")
    ):
        raise ReleaseWorkflowV32Error("Release V31 predecessor contract drifted")

    entries = transition["current_release_paths"]
    predecessor_hashes = {
        entry["path"]: entry["sha256"]
        for entry in predecessor["current_release_paths"]
    }
    paths: list[str] = []
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or type(entry.get("path")) is not str
            or not _valid_sha(entry.get("sha256"))
        ):
            raise ReleaseWorkflowV32Error("Release V32 entry is malformed")
        relative = entry["path"]
        paths.append(relative)
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise ReleaseWorkflowV32Error(
                f"current release target drifted: {relative}"
            )
        if predecessor_hashes.get(relative) == entry["sha256"]:
            raise ReleaseWorkflowV32Error(
                f"Release V32 contains unchanged target: {relative}"
            )
    if paths != sorted(set(paths)) or not paths:
        raise ReleaseWorkflowV32Error("Release V32 membership drifted")
    if _root(transition, b"ONYX-RELEASE-WORKFLOW-TRANSITION-V32\0") != (
        RELEASE_V32_ROOT_SHA256
    ):
        raise ReleaseWorkflowV32Error("Release V32 root drifted")

    # Validate every V31 payload byte before importing any V26 authority.  A
    # path may differ from its immutable V31 hash only when V32 names that
    # exact successor hash.  This closes coordinated module+manifest tamper.
    v32_hashes = {
        entry["path"]: entry["sha256"]
        for entry in transition["current_release_paths"]
    }
    predecessor_paths: list[str] = []
    for entry in predecessor["current_release_paths"]:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or type(entry.get("path")) is not str
            or not _valid_sha(entry.get("sha256"))
        ):
            raise ReleaseWorkflowV32Error("Release V31 entry is malformed")
        relative = entry["path"]
        predecessor_paths.append(relative)
        actual_sha256 = _sha256(_canonical_file(root, relative))
        if (
            actual_sha256 != entry["sha256"]
            and v32_hashes.get(relative) != actual_sha256
        ):
            raise ReleaseWorkflowV32Error(
                f"Release V31 current target drifted: {relative}"
            )
    if predecessor_paths != sorted(set(predecessor_paths)) or not predecessor_paths:
        raise ReleaseWorkflowV32Error("Release V31 membership drifted")

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v32-verifier-receipt.v1",
        "release_path": RELEASE_V32_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V32_SHA256,
        "release_root_sha256": RELEASE_V32_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V31_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
    }:
        raise ReleaseWorkflowV32Error("Release V32 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v26 import verify_current_hud_acceptance

    runtime = verify_current_hud_acceptance(root)
    return {"transition": transition, "runtime": runtime, "receipt": receipt}


if __name__ == "__main__":
    verified = verify_release_workflow_v32()
    print(json.dumps({
        "release_schema": verified["transition"]["schema"],
        "release_root_sha256": verified["transition"]["current_root_sha256"],
        "runtime_root_sha256": verified["runtime"]["artifact_root_sha256"],
        "verifier_sha256": verified["receipt"]["verifier_sha256"],
    }, sort_keys=True))
