"""Standalone verifier for the additive Release V61 successor."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path, PurePosixPath

PROJECT = Path(__file__).resolve().parents[1]
V61 = Path("tests/fixtures/release_workflow_transition_v61.json")
V60 = Path("tests/fixtures/release_workflow_transition_v60.json")
V61_SHA256 = "b6fa425580699ce9fa27efcb54f9bfcab759284c21b3b7e4de53dd44735d3779"
V61_ROOT_SHA256 = "00dd14ca8ab177dd3e122042b5833cb9eb2c1ef74bc117409801a9df4c557050"
V60_SHA256 = "79521716c4c0cc7e835068d3441261123699096e20aaa66c448f21c8917ca49c"
V60_ROOT_SHA256 = "d2f98dd01391d20fbe44259cff3201115cc2dc6f96ca8b9db0fd3b1bdfb09ba7"
RECEIPT = Path("docs/onyx/checkpoints/RELEASE_WORKFLOW_V61_VERIFIER_RECEIPT.json")
POLICY = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}


class ReleaseWorkflowV61Error(RuntimeError):
    """Release V61 or its immutable V60 predecessor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: Path | str) -> Path:
    pure = PurePosixPath(str(relative).replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ReleaseWorkflowV61Error("noncanonical Release V61 path")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV61Error(f"Release V61 input unavailable: {pure}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReleaseWorkflowV61Error(
            f"Release V61 input escapes root: {pure}"
        ) from exc
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV61Error(f"Release V61 input is linked: {pure}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV61Error("duplicate Release V61 JSON key")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if type(value) is not dict:
        raise ReleaseWorkflowV61Error("Release V61 JSON must be an object")
    return value


def _entries(value: dict[str, object]) -> list[dict[str, str]]:
    entries = value.get("current_release_paths")
    if type(entries) is not list:
        raise ReleaseWorkflowV61Error("Release V61 entries drifted")
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
            raise ReleaseWorkflowV61Error("Release V61 entries drifted")
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


def verify_release_workflow_v61(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    try:
        transition = _strict_json(_canonical_file(root, V61))
        predecessor = _strict_json(_canonical_file(root, V60))
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ReleaseWorkflowV61Error,
    ) as error:
        raise ReleaseWorkflowV61Error(
            "Release V61 contract or predecessor drifted"
        ) from error
    if (
        _sha256(root / V61) != V61_SHA256
        or transition.get("schema") != "onyx.release-workflow-transition.v61"
        or transition.get("logical_sequence") != 61
        or transition.get("predecessor")
        != {"path": V60.as_posix(), "sha256": V60_SHA256}
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != V61_ROOT_SHA256
        or _root(transition, 61) != V61_ROOT_SHA256
    ):
        raise ReleaseWorkflowV61Error("Release V61 contract drifted")
    if (
        _sha256(root / V60) != V60_SHA256
        or predecessor.get("current_root_sha256") != V60_ROOT_SHA256
        or _root(predecessor, 60) != V60_ROOT_SHA256
        or datetime.fromisoformat(transition["issued_at"])
        <= datetime.fromisoformat(predecessor["issued_at"])
    ):
        raise ReleaseWorkflowV61Error("Release V60 predecessor drifted")
    for entry in _entries(transition):
        if _sha256(_canonical_file(root, entry["path"])) != entry["sha256"]:
            raise ReleaseWorkflowV61Error(
                f"current release target drifted: {entry['path']}"
            )
    receipt = _strict_json(_canonical_file(root, RECEIPT))
    expected = {
        "schema": "onyx.release-workflow-v61-verifier-receipt.v1",
        "release_path": V61.as_posix(),
        "release_sha256": V61_SHA256,
        "release_root_sha256": V61_ROOT_SHA256,
        "predecessor_sha256": V60_SHA256,
        "verifier_path": "scripts/verify_release_workflow_v61.py",
        "verifier_sha256": _sha256(root / "scripts/verify_release_workflow_v61.py"),
        "test_path": "tests/test_release_workflow_transition_v61.py",
        "test_sha256": _sha256(root / "tests/test_release_workflow_transition_v61.py"),
        "chronology": "normal_successor",
        "scope": "living-liquid-metal-v9-hud-v36-packaged-v5-closure",
    }
    if receipt != expected:
        raise ReleaseWorkflowV61Error("Release V61 verifier receipt drifted")
    return {
        "transition": transition,
        "receipt": receipt,
        "formal_release_ready": False,
        "publishable": False,
    }


if __name__ == "__main__":
    result = verify_release_workflow_v61()
    print(
        json.dumps(
            {
                "release_schema": result["transition"]["schema"],
                "release_root_sha256": result["transition"]["current_root_sha256"],
            },
            sort_keys=True,
        )
    )
