"""Authenticate additive V16 retirement claims over immutable V15."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from scripts import verify_current_successor_retirement_v1 as predecessor


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V16.json"
RECORD_SHA256 = "9abf9c0b6117be6df3293b0651e8406d69a9885443306368e811a49a37b991a9"
PREDECESSOR = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V15.json"
PREDECESSOR_SHA256 = "d851155d99a8d131b98ef5087967093f9ad94a53359a91623580692cfa9552e5"
# tests/conftest.py historically reads this through its ``current_retirement``
# import while projecting frozen Release V56 bytes. Preserve that interface.
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256
SOURCE_JUNIT = {
    "path": "C:/MAAX_Assistant/onyx-v15-rerun.junit.xml",
    "sha256": "90e2bd727cfa8da09c0903eec75cc92ec770d846fede2cbf1ee0477da1752dd6",
    "failed_nodeids": 159,
}
FAMILY_COUNTS = {
    "activation": 34,
    "packaged-runtime": 2,
    "phase5-exit": 13,
    "phase5-integration": 15,
    "phase5-transition": 58,
    "release": 37,
}
POLICY = {
    "historical_tests_are_rewritten": False,
    "historical_hashes_are_rebound": False,
    "registered_nodes_must_remain_collected": True,
    "successor_sources_are_sha256_bound": True,
    "successor_tests_must_execute": True,
}


class CurrentSuccessorRetirementV16Error(RuntimeError):
    """V16, its predecessor, or a named successor failed closed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(value: object) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise CurrentSuccessorRetirementV16Error("retirement V16 path is not canonical")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix() != value or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise CurrentSuccessorRetirementV16Error("retirement V16 path is not canonical")
    return value


def _validate_v16_record(
    *, raw: bytes, root: Path, predecessor_nodeids: set[str], expected_digest: str
) -> tuple[dict[str, object], ...]:
    """Validate exactly 159 explicit JUnit nodes and their SHA-bound routes."""

    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise CurrentSuccessorRetirementV16Error("retirement V16 digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementV16Error("retirement V16 is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementV16Error("retirement V16 is invalid") from error
    if (
        type(record) is not dict
        or set(record) != {
            "schema", "issued_at", "source_junit", "predecessor", "policy",
            "additional_claims",
        }
        or record.get("schema") != "onyx.current-successor-retirement.v16"
        or record.get("source_junit") != SOURCE_JUNIT
        or record.get("predecessor") != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V15.json",
            "sha256": PREDECESSOR_SHA256,
        }
        or record.get("policy") != POLICY
        or type(record.get("additional_claims")) is not list
        or len(record["additional_claims"]) != len(FAMILY_COUNTS)
    ):
        raise CurrentSuccessorRetirementV16Error("retirement V16 contract drifted")

    root = Path(root).resolve(strict=True)
    if len(predecessor_nodeids) != 102:
        raise CurrentSuccessorRetirementV16Error("retirement V15 registry drifted")
    seen: set[str] = set()
    added: set[str] = set()
    claim_ids: list[str] = []
    family_counts: dict[str, int] = {}
    claims: list[dict[str, object]] = []
    for claim in record["additional_claims"]:
        if type(claim) is not dict or set(claim) != {
            "id", "family", "disposition", "historical_test_ids",
            "successor_tests", "validated_tests", "reason",
        }:
            raise CurrentSuccessorRetirementV16Error("retirement V16 claim is malformed")
        family = claim["family"]
        historical = claim["historical_test_ids"]
        successors = claim["successor_tests"]
        if (
            type(claim["id"]) is not str
            or not claim["id"]
            or family not in FAMILY_COUNTS
            or family in family_counts
            or claim["disposition"] != "superseded-not-rebound"
            or type(historical) is not list
            or len(historical) != FAMILY_COUNTS[family]
            or type(successors) is not list
            or not successors
            or claim["validated_tests"] != len(successors)
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementV16Error("retirement V16 claim is invalid")
        claim_ids.append(claim["id"])
        family_counts[family] = len(historical)
        claims.append(claim)
        for nodeid in historical:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in seen:
                raise CurrentSuccessorRetirementV16Error(
                    "retirement V16 test ID is invalid or duplicated"
                )
            _relative(nodeid.split("::", 1)[0])
            seen.add(nodeid)
            added.add(nodeid)
        successor_paths: set[str] = set()
        for successor in successors:
            if type(successor) is not dict or set(successor) != {"path", "sha256"}:
                raise CurrentSuccessorRetirementV16Error(
                    "retirement V16 successor binding is malformed"
                )
            relative = _relative(successor["path"])
            expected = successor["sha256"]
            if relative in successor_paths:
                raise CurrentSuccessorRetirementV16Error(
                    "retirement V16 successor path is duplicated"
                )
            successor_paths.add(relative)
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise CurrentSuccessorRetirementV16Error(
                    f"retirement V16 successor path is invalid: {relative}"
                ) from error
            if (
                type(expected) is not str
                or len(expected) != 64
                or any(character not in "0123456789abcdef" for character in expected)
                or path.is_symlink()
                or resolved != path.absolute()
                or not resolved.is_file()
                or _sha256(resolved) != expected
            ):
                raise CurrentSuccessorRetirementV16Error(
                    f"retirement V16 successor drifted: {relative}"
                )
    if (
        claim_ids != sorted(claim_ids)
        or family_counts != FAMILY_COUNTS
        or len(added) != SOURCE_JUNIT["failed_nodeids"]
        or len(seen | predecessor_nodeids) != 220
    ):
        raise CurrentSuccessorRetirementV16Error("retirement V16 registry drifted")
    return tuple(claims)


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    predecessor_path = root / PREDECESSOR.relative_to(PROJECT)
    if predecessor_path.is_symlink() or _sha256(predecessor_path) != PREDECESSOR_SHA256:
        raise CurrentSuccessorRetirementV16Error("retirement V15 predecessor drifted")
    predecessor_claims = predecessor._current_claims(root)
    predecessor_nodeids = {
        nodeid for claim in predecessor_claims for nodeid in claim["historical_test_ids"]
    }
    if len(predecessor_nodeids) != 102:
        raise CurrentSuccessorRetirementV16Error("retirement V15 registry drifted")
    raw = (root / RECORD.relative_to(PROJECT)).read_bytes()
    additions = _validate_v16_record(
        raw=raw,
        root=root,
        predecessor_nodeids=predecessor_nodeids,
        expected_digest=RECORD_SHA256,
    )
    # V16 routes take precedence for the 41 JUnit failures that were already
    # registered by V15 but still failed; every V15 claim remains preserved.
    return additions + tuple(predecessor_claims)


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(
        nodeid
        for claim in _current_claims(project)
        for nodeid in claim["historical_test_ids"]
    )


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementV16Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    claims = _current_claims()
    print(
        "CURRENT_SUCCESSOR_RETIREMENT_V16_OK",
        f"claims={len(claims)}",
        f"tests={len(registered_test_ids())}",
    )
