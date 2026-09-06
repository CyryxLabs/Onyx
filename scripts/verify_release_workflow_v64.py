"""Standalone verifier for corrected Release V64."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
V64 = Path("tests/fixtures/release_workflow_transition_v64.json")
V63 = Path("tests/fixtures/release_workflow_transition_v63.json")
V64_SHA256 = "62b0db65905c15573b07bf617aa44061759ff247a67d6014b24ca8831587ee2b"
V64_ROOT_SHA256 = "82effe946b51a4fcda777822f929296d3402cc40513715d38dc8df188fba633f"
V63_SHA256 = "17d2c6a391fe274e6576867ad41e11aa257773f7b3dd340a9a2b5dc789225d04"
V63_ROOT_SHA256 = "66728573e5229a3ef92269f9128e5b14947f8f0f0883278f0cc5dd9083bf08ca"
POLICY = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}


class ReleaseWorkflowV64Error(RuntimeError):
    """Release V64 or immutable V63 drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root: Path, relative: Path | str) -> Path:
    pure = PurePosixPath(str(relative).replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ReleaseWorkflowV64Error("noncanonical Release V64 path")
    path = root.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file() or path.resolve() != path.absolute():
        raise ReleaseWorkflowV64Error(f"Release V64 input unavailable: {pure}")
    path.resolve().relative_to(root)
    return path


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ReleaseWorkflowV64Error("Release V64 JSON drifted")
    return value


def _entries(value: dict[str, object]) -> list[dict[str, str]]:
    entries = value.get("current_release_paths")
    if type(entries) is not list:
        raise ReleaseWorkflowV64Error("Release V64 entries drifted")
    prior = ""
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "sha256"} or entry["path"] <= prior or len(entry["sha256"]) != 64:
            raise ReleaseWorkflowV64Error("Release V64 entries drifted")
        prior = entry["path"]
    return entries


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


def verify_release_workflow_v64(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    transition = _json(_file(root, V64))
    predecessor = _json(_file(root, V63))
    if (
        _sha256(root / V64) != V64_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v64"
        or transition.get("logical_sequence") != 64
        or transition.get("predecessor") != {"path": V63.as_posix(), "sha256": V63_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V64_ROOT_SHA256
        or _root(transition, 64) != V64_ROOT_SHA256
    ):
        raise ReleaseWorkflowV64Error("Release V64 contract drifted")
    if _sha256(root / V63) != V63_SHA256 or predecessor.get("current_root_sha256") != V63_ROOT_SHA256 or _root(predecessor, 63) != V63_ROOT_SHA256 or datetime.fromisoformat(transition["issued_at"]) <= datetime.fromisoformat(predecessor["issued_at"]):
        raise ReleaseWorkflowV64Error("Release V63 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV64Error(f"current release target drifted: {entry['path']}")
    return {"transition": transition, "formal_release_ready": False, "publishable": False}


if __name__ == "__main__":
    print(json.dumps(verify_release_workflow_v64()["transition"], sort_keys=True))
