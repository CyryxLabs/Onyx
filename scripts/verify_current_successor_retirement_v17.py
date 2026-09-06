"""Authenticate the additive V57 release-authority retirement over V16."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from scripts import verify_current_successor_retirement_v16 as predecessor


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V17.json"
PREDECESSOR = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V16.json"
PREDECESSOR_SHA256 = "9abf9c0b6117be6df3293b0651e8406d69a9885443306368e811a49a37b991a9"
RECORD_SHA256 = "3ac3d0e0cef689b74a159263fb69d083216e9438dad6d56cdce349beb5249a94"
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV17Error(RuntimeError):
    """V17, its predecessor, or the V57 successor failed closed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claim(root: Path, raw: bytes, expected_digest: str) -> dict[str, object]:
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise CurrentSuccessorRetirementV17Error("retirement V17 digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementV17Error("retirement V17 is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementV17Error("retirement V17 is invalid") from error
    expected_nodes = [
        "tests/test_release_workflow_transition_v56.py::test_release_v56_authenticates_exact_capability_runtime_closure",
        "tests/test_release_workflow_transition_v56.py::test_release_v56_preserves_immutable_packaged_v2_contract",
    ]
    if (
        type(record) is not dict
        or set(record) != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or record.get("schema") != "onyx.current-successor-retirement.v17"
        or record.get("predecessor") != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V16.json",
            "sha256": PREDECESSOR_SHA256,
        }
        or record.get("policy") != predecessor.POLICY
        or type(record.get("additional_claims")) is not list
        or len(record["additional_claims"]) != 1
    ):
        raise CurrentSuccessorRetirementV17Error("retirement V17 contract drifted")
    claim = record["additional_claims"][0]
    if (
        type(claim) is not dict
        or set(claim) != {"id", "disposition", "historical_test_ids", "successor_tests", "validated_tests", "reason"}
        or claim.get("id") != "release-v56-to-v57-current-authority"
        or claim.get("disposition") != "superseded-not-rebound"
        or claim.get("historical_test_ids") != expected_nodes
        or claim.get("validated_tests") != 2
        or type(claim.get("reason")) is not str
        or not claim["reason"]
        or type(claim.get("successor_tests")) is not list
        or len(claim["successor_tests"]) != 1
    ):
        raise CurrentSuccessorRetirementV17Error("retirement V17 claim drifted")
    binding = claim["successor_tests"][0]
    if type(binding) is not dict or set(binding) != {"path", "sha256"}:
        raise CurrentSuccessorRetirementV17Error("retirement V17 successor is malformed")
    relative = binding["path"]
    parsed = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if parsed.is_absolute() or parsed.as_posix() != relative or any(part in {"", ".", ".."} for part in parsed.parts):
        raise CurrentSuccessorRetirementV17Error("retirement V17 successor path is invalid")
    path = root.joinpath(*parsed.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentSuccessorRetirementV17Error("retirement V17 successor path is invalid") from error
    if path.is_symlink() or resolved != path.absolute() or _sha256(resolved) != binding["sha256"]:
        raise CurrentSuccessorRetirementV17Error("retirement V17 successor drifted")
    return claim


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    predecessor_path = root / PREDECESSOR.relative_to(PROJECT)
    if predecessor_path.is_symlink() or _sha256(predecessor_path) != PREDECESSOR_SHA256:
        raise CurrentSuccessorRetirementV17Error("retirement V16 predecessor drifted")
    claims = predecessor._current_claims(root)
    raw = (root / RECORD.relative_to(PROJECT)).read_bytes()
    return (_claim(root, raw, RECORD_SHA256),) + tuple(claims)


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(nodeid for claim in _current_claims(project) for nodeid in claim["historical_test_ids"])


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementV17Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    claims = _current_claims()
    print("CURRENT_SUCCESSOR_RETIREMENT_V17_OK", f"claims={len(claims)}", f"tests={len(registered_test_ids())}")
