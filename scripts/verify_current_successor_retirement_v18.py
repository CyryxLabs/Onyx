"""Authenticate the additive exact-node V18 retirement over immutable V17."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from scripts import verify_current_successor_retirement_v17 as predecessor


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V18.json"
PREDECESSOR = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V17.json"
PREDECESSOR_SHA256 = "3ac3d0e0cef689b74a159263fb69d083216e9438dad6d56cdce349beb5249a94"
RECORD_SHA256 = "5eb69ec483bbb978ffeadb676717e948accc62042a0f877fd6a169f2c4f6f517"
V17_REGISTERED_ROUTES = 222
V18_REGISTERED_ROUTES = 155
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV18Error(RuntimeError):
    """V18, V17, or an exact current-successor binding failed closed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_relative_file(root: Path, relative: object, label: str) -> Path:
    parsed = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        parsed.is_absolute()
        or parsed.as_posix() != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise CurrentSuccessorRetirementV18Error(f"{label} path is invalid")
    path = root.joinpath(*parsed.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentSuccessorRetirementV18Error(f"{label} path is invalid") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentSuccessorRetirementV18Error(f"{label} path is invalid")
    return resolved


def _decode(raw: bytes, label: str) -> dict[str, object]:
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementV18Error(f"{label} is not canonical")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementV18Error(f"{label} is invalid") from error
    if type(value) is not dict:
        raise CurrentSuccessorRetirementV18Error(f"{label} contract drifted")
    return value


def _canonical_contract() -> dict[str, object]:
    raw = RECORD.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256:
        raise CurrentSuccessorRetirementV18Error("retirement V18 canonical record drifted")
    return _decode(raw, "retirement V18")


def _claim(root: Path, raw: bytes, expected_digest: str) -> tuple[dict[str, object], ...]:
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise CurrentSuccessorRetirementV18Error("retirement V18 digest drifted")
    record = _decode(raw, "retirement V18")
    if record != _canonical_contract():
        raise CurrentSuccessorRetirementV18Error("retirement V18 contract drifted")

    claims = record["additional_claims"]
    if type(claims) is not list or len(claims) != 8:
        raise CurrentSuccessorRetirementV18Error("retirement V18 claims drifted")
    all_nodes: list[str] = []
    all_successors: list[str] = []
    for claim in claims:
        if (
            type(claim) is not dict
            or set(claim) != {
                "id", "disposition", "historical_test_ids", "successor_tests",
                "validated_tests", "reason",
            }
            or claim.get("disposition") != "superseded-not-rebound"
            or type(claim.get("historical_test_ids")) is not list
            or type(claim.get("successor_tests")) is not list
            or claim.get("validated_tests") != len(claim["historical_test_ids"])
            or type(claim.get("reason")) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementV18Error("retirement V18 claim drifted")
        nodes = claim["historical_test_ids"]
        if any(type(node) is not str or "::" not in node for node in nodes):
            raise CurrentSuccessorRetirementV18Error("retirement V18 nodeid drifted")
        all_nodes.extend(nodes)
        for binding in claim["successor_tests"]:
            if type(binding) is not dict or set(binding) != {"path", "sha256"}:
                raise CurrentSuccessorRetirementV18Error("retirement V18 successor is malformed")
            successor = _strict_relative_file(root, binding["path"], "retirement V18 successor")
            if _sha256(successor) != binding["sha256"]:
                raise CurrentSuccessorRetirementV18Error("retirement V18 successor drifted")
            all_successors.append(binding["path"])
    if len(all_nodes) != V18_REGISTERED_ROUTES or len(set(all_nodes)) != len(all_nodes):
        raise CurrentSuccessorRetirementV18Error("retirement V18 nodes contain extras or duplicates")
    if len(all_successors) != len(set(all_successors)) + 1:
        # phase6_current_v1.py is intentionally shared by exactly two claims.
        raise CurrentSuccessorRetirementV18Error("retirement V18 successor duplicates drifted")
    return tuple(claims)


def _v18_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    record = _strict_relative_file(
        root, "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V18.json", "retirement V18 record"
    )
    return _claim(root, record.read_bytes(), RECORD_SHA256)


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    predecessor_path = _strict_relative_file(
        root, "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V17.json", "retirement V17 predecessor"
    )
    if _sha256(predecessor_path) != PREDECESSOR_SHA256:
        raise CurrentSuccessorRetirementV18Error("retirement V17 predecessor drifted")
    predecessor_claims = predecessor._current_claims(root)
    if len(predecessor.registered_test_ids(root)) != V17_REGISTERED_ROUTES:
        raise CurrentSuccessorRetirementV18Error("retirement V17 routes drifted")
    return _v18_claims(root) + tuple(predecessor_claims)


def v18_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(node for claim in _v18_claims(project) for node in claim["historical_test_ids"])


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(node for claim in _current_claims(project) for node in claim["historical_test_ids"])


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    # V18 is first by construction and therefore owns every overlap with V17.
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementV18Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    claims = _current_claims()
    print(
        "CURRENT_SUCCESSOR_RETIREMENT_V18_OK",
        f"claims={len(claims)}",
        f"v17_routes={V17_REGISTERED_ROUTES}",
        f"v18_routes={len(v18_test_ids())}",
        f"combined_routes={len(registered_test_ids())}",
    )
