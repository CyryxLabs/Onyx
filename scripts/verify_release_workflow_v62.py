"""Standalone verifier for additive Release V62."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
V62 = Path("tests/fixtures/release_workflow_transition_v62.json")
V61 = Path("tests/fixtures/release_workflow_transition_v61.json")
V62_SHA256 = "947d4eb360b233e98293c025708ab4894fa09a1ecaf4154d38dcb62d05cf44f8"
V62_ROOT_SHA256 = "df99f906d41fdff74c3ade1adad57b48a7f320c3a2ef1219d116150bcb4da491"
V61_SHA256 = "b6fa425580699ce9fa27efcb54f9bfcab759284c21b3b7e4de53dd44735d3779"
V61_ROOT_SHA256 = "00dd14ca8ab177dd3e122042b5833cb9eb2c1ef74bc117409801a9df4c557050"
POLICY = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}


class ReleaseWorkflowV62Error(RuntimeError):
    """Release V62 or its immutable V61 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: Path | str) -> Path:
    pure = PurePosixPath(str(relative).replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ReleaseWorkflowV62Error("noncanonical Release V62 path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV62Error(f"Release V62 input unavailable: {pure}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ReleaseWorkflowV62Error(f"Release V62 input escapes root: {pure}") from error
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV62Error(f"Release V62 input is linked: {pure}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV62Error("duplicate Release V62 JSON key")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if type(value) is not dict:
        raise ReleaseWorkflowV62Error("Release V62 JSON must be an object")
    return value


def _entries(value: dict[str, object]) -> list[dict[str, str]]:
    entries = value.get("current_release_paths")
    if type(entries) is not list:
        raise ReleaseWorkflowV62Error("Release V62 entries drifted")
    result: list[dict[str, str]] = []
    prior = ""
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or type(entry.get("path")) is not str
            or type(entry.get("sha256")) is not str
            or len(entry["sha256"]) != 64
            or entry["path"] <= prior
        ):
            raise ReleaseWorkflowV62Error("Release V62 entries drifted")
        prior = entry["path"]
        result.append(entry)
    return result


def _root(value: dict[str, object], sequence: int) -> str:
    digest = hashlib.sha256(f"ONYX-RELEASE-WORKFLOW-TRANSITION-V{sequence}\0".encode())
    predecessor = value["predecessor"]
    for item in (
        value["issued_at"],
        str(value["logical_sequence"]),
        predecessor["path"],
        predecessor["sha256"],
    ):
        encoded = item.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    for entry in _entries(value):
        for item in (entry["path"], entry["sha256"]):
            encoded = item.encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def verify_release_workflow_v62(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    try:
        transition = _strict_json(_canonical_file(root, V62))
        predecessor = _strict_json(_canonical_file(root, V61))
    except (OSError, UnicodeError, json.JSONDecodeError, ReleaseWorkflowV62Error) as error:
        raise ReleaseWorkflowV62Error("Release V62 contract or predecessor drifted") from error
    if (
        _sha256(root / V62) != V62_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v62"
        or transition.get("logical_sequence") != 62
        or transition.get("predecessor") != {"path": V61.as_posix(), "sha256": V61_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V62_ROOT_SHA256
        or _root(transition, 62) != V62_ROOT_SHA256
    ):
        raise ReleaseWorkflowV62Error("Release V62 contract drifted")
    if (
        _sha256(root / V61) != V61_SHA256
        or predecessor.get("current_root_sha256") != V61_ROOT_SHA256
        or _root(predecessor, 61) != V61_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV62Error("Release V61 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_canonical_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV62Error(f"current release target drifted: {entry['path']}")
    return {
        "transition": transition,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    result = verify_release_workflow_v62()
    print(json.dumps({
        "release_schema": result["transition"]["schema"],
        "release_root_sha256": result["transition"]["current_root_sha256"],
    }, sort_keys=True))
