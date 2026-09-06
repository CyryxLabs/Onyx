"""Authenticate immutable legacy activation evidence and current successors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/LEGACY_ACTIVATION_RETIREMENT_V1.json"
RECORD_SHA256 = "756ca894da679559717d8c4ab6247ccbe80227687ddaca28ffa79a7711afa132"
MARKER = "LEGACY_ACTIVATION_RETIREMENT_V1_OK"


class LegacyActivationRetirementV1Error(RuntimeError):
    """The retirement ledger or a byte-bound source drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(value: object) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise LegacyActivationRetirementV1Error("retirement path is not canonical")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix() != value or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise LegacyActivationRetirementV1Error("retirement path is not canonical")
    return value


def _matches_authenticated_successor(
    *, root: Path, relative: str, predecessor_sha256: str, current_sha256: str
) -> bool:
    if root != PROJECT.resolve():
        return False
    try:
        from scripts.verify_phase5_exit_retirement_v1 import (
            load_current_successor_transition,
        )

        transition = load_current_successor_transition()
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return any(
        type(successor) is dict
        and successor.get("path") == relative
        and successor.get("predecessor_sha256") == predecessor_sha256
        and successor.get("current_sha256") == current_sha256
        for successor in transition.get("named_successors", ())
    )


def _verify_binding(
    root: Path,
    binding: object,
    *,
    label: str,
    allow_authenticated_successor: bool = False,
) -> None:
    if type(binding) is not dict or set(binding) != {"path", "sha256"}:
        raise LegacyActivationRetirementV1Error(f"{label} binding is malformed")
    relative = _relative(binding["path"])
    expected = binding["sha256"]
    if type(expected) is not str or len(expected) != 64:
        raise LegacyActivationRetirementV1Error(f"{label} digest is invalid")
    path = root / relative
    if not path.is_file():
        raise LegacyActivationRetirementV1Error(f"{label} drifted: {relative}")
    actual = _sha256(path)
    if actual != expected and not (
        allow_authenticated_successor
        and _matches_authenticated_successor(
            root=root,
            relative=relative,
            predecessor_sha256=expected,
            current_sha256=actual,
        )
    ):
        raise LegacyActivationRetirementV1Error(f"{label} drifted: {relative}")


def load_record(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    raw = (root / RECORD.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256:
        raise LegacyActivationRetirementV1Error("retirement record digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise LegacyActivationRetirementV1Error("retirement record is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LegacyActivationRetirementV1Error("retirement record is invalid") from error
    expected_policy = {
        "historical_sources_are_immutable": True,
        "historical_hashes_are_rebound": False,
        "registered_nodes_must_remain_collected": True,
        "successor_tests_are_sha256_bound": True,
        "successor_tests_must_execute": True,
    }
    if type(record) is not dict or set(record) != {
        "schema", "issued_at", "policy", "claims"
    }:
        raise LegacyActivationRetirementV1Error("retirement contract drifted")
    if (
        record["schema"] != "onyx.legacy-activation-retirement.v1"
        or record["policy"] != expected_policy
        or type(record["claims"]) is not list
        or len(record["claims"]) != 5
    ):
        raise LegacyActivationRetirementV1Error("retirement policy drifted")

    nodeids: set[str] = set()
    claim_ids: list[str] = []
    for claim in record["claims"]:
        if type(claim) is not dict or set(claim) != {
            "id", "disposition", "historical_test_ids", "historical_sources",
            "successor_tests", "reason"
        }:
            raise LegacyActivationRetirementV1Error("retirement claim is malformed")
        claim_ids.append(claim["id"])
        if (
            claim["disposition"] != "superseded-not-rebound"
            or type(claim["historical_test_ids"]) is not list
            or not claim["historical_test_ids"]
            or type(claim["historical_sources"]) is not list
            or not claim["historical_sources"]
            or type(claim["successor_tests"]) is not list
            or not claim["successor_tests"]
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise LegacyActivationRetirementV1Error("retirement claim is invalid")
        for nodeid in claim["historical_test_ids"]:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in nodeids:
                raise LegacyActivationRetirementV1Error("retired test ID is invalid")
            _relative(nodeid.split("::", 1)[0])
            nodeids.add(nodeid)
        for binding in claim["historical_sources"]:
            _verify_binding(root, binding, label="historical source")
        for binding in claim["successor_tests"]:
            _verify_binding(
                root,
                binding,
                label="current successor",
                allow_authenticated_successor=True,
            )
    if claim_ids != sorted(claim_ids) or len(nodeids) != 44:
        raise LegacyActivationRetirementV1Error("retirement registry drifted")
    return record


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(
        nodeid
        for claim in load_record(project)["claims"]
        for nodeid in claim["historical_test_ids"]
    )


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in load_record(project)["claims"]:
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise LegacyActivationRetirementV1Error(
        f"unregistered historical test: {nodeid}"
    )


if __name__ == "__main__":
    record = load_record()
    print(MARKER, f"claims={len(record['claims'])}", f"tests={len(registered_test_ids())}")
