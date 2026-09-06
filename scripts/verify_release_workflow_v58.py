"""Standalone verifier for the additive Release V58 successor."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path, PurePosixPath

PROJECT = Path(__file__).resolve().parents[1]
V58 = Path("tests/fixtures/release_workflow_transition_v58.json")
V57 = Path("tests/fixtures/release_workflow_transition_v57.json")
V58_SHA256 = "1939abf3cdf78449d6280c05e144b315b6cc29e6991564801b97c0e6cd79f3f8"
V58_ROOT_SHA256 = "3ce35f5058c725d0d75e0d9435f6a40020691cf32000c21cf5e5191a72b4160c"
V57_SHA256 = "7b866cac1987c43466d00118c1a81dc3761c307ec6455d51a9f46a01b1b0e16d"
V57_ROOT_SHA256 = "6154deffad8e5d5da41b83efe38d857d91a78ad6be9d68a0e7f3ace976b0122a"
RECEIPT = Path("docs/onyx/checkpoints/RELEASE_WORKFLOW_V58_VERIFIER_RECEIPT.json")
POLICY = {"predecessor_is_immutable": True, "historical_hashes_are_rebound": False, "current_release_paths_are_sha256_bound": True, "unsigned_windows_may_be_formal": False, "diagnostic_candidates_may_be_published": False}


class ReleaseWorkflowV58Error(RuntimeError):
    """Release V58 or its immutable V57 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: Path | str) -> Path:
    pure = PurePosixPath(str(relative).replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ReleaseWorkflowV58Error("noncanonical Release V58 path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV58Error(f"Release V58 input unavailable: {pure}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseWorkflowV58Error(f"Release V58 input escapes root: {pure}") from exc
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV58Error(f"Release V58 input is linked: {pure}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV58Error("duplicate Release V58 JSON key")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if type(value) is not dict:
        raise ReleaseWorkflowV58Error("Release V58 JSON must be an object")
    return value


def _entries(value: dict[str, object]) -> list[dict[str, str]]:
    entries = value.get("current_release_paths")
    if type(entries) is not list:
        raise ReleaseWorkflowV58Error("Release V58 entries drifted")
    result: list[dict[str, str]] = []
    prior = ""
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"} or type(entry.get("path")) is not str or type(entry.get("sha256")) is not str or len(entry["sha256"]) != 64 or entry["path"] <= prior:
            raise ReleaseWorkflowV58Error("Release V58 entries drifted")
        prior = entry["path"]
        result.append(entry)
    return result


def _root(value: dict[str, object], sequence: int) -> str:
    digest = hashlib.sha256(f"ONYX-RELEASE-WORKFLOW-TRANSITION-V{sequence}\0".encode())
    predecessor = value["predecessor"]
    for item in (value["issued_at"], str(value["logical_sequence"]), predecessor["path"], predecessor["sha256"]):
        encoded = item.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    for entry in _entries(value):
        for item in (entry["path"], entry["sha256"]):
            encoded = item.encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def verify_release_workflow_v58(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    try:
        transition = _strict_json(_canonical_file(root, V58))
        predecessor = _strict_json(_canonical_file(root, V57))
    except (OSError, UnicodeError, json.JSONDecodeError, ReleaseWorkflowV58Error) as error:
        raise ReleaseWorkflowV58Error("Release V58 contract or predecessor drifted") from error
    if _sha256(root / V58) != V58_SHA256 or transition.get("schema") != "onyx.release-workflow-transition.v58" or transition.get("logical_sequence") != 58 or transition.get("predecessor") != {"path": V57.as_posix(), "sha256": V57_SHA256} or transition.get("policy") != POLICY or transition.get("current_root_sha256") != V58_ROOT_SHA256 or _root(transition, 58) != V58_ROOT_SHA256:
        raise ReleaseWorkflowV58Error("Release V58 contract drifted")
    if _sha256(root / V57) != V57_SHA256 or predecessor.get("current_root_sha256") != V57_ROOT_SHA256 or _root(predecessor, 57) != V57_ROOT_SHA256 or datetime.fromisoformat(transition["issued_at"]) <= datetime.fromisoformat(predecessor["issued_at"]):
        raise ReleaseWorkflowV58Error("Release V57 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_canonical_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV58Error(f"current release target drifted: {entry['path']}")
    receipt = _strict_json(_canonical_file(root, RECEIPT))
    expected = {"schema": "onyx.release-workflow-v58-verifier-receipt.v1", "release_path": V58.as_posix(), "release_sha256": V58_SHA256, "release_root_sha256": V58_ROOT_SHA256, "predecessor_sha256": V57_SHA256, "verifier_path": "scripts/verify_release_workflow_v58.py", "verifier_sha256": _sha256(root / "scripts/verify_release_workflow_v58.py"), "test_path": "tests/test_release_workflow_transition_v58.py", "test_sha256": _sha256(root / "tests/test_release_workflow_transition_v58.py"), "chronology": "normal_successor", "scope": "packaged-runtime-v4-hud-v35-closure-only"}
    if receipt != expected:
        raise ReleaseWorkflowV58Error("Release V58 verifier receipt drifted")
    return {"transition": transition, "receipt": receipt, "formal_release_ready": False, "publishable": False}


if __name__ == "__main__":
    result = verify_release_workflow_v58()
    print(json.dumps({"release_schema": result["transition"]["schema"], "release_root_sha256": result["transition"]["current_root_sha256"]}, sort_keys=True))
