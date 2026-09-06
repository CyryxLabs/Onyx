"""Verify immutable activation history and its non-retired current successor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/LEGACY_ACTIVATION_RETIREMENT_V2.json"
PREDECESSOR = PROJECT / "docs/onyx/checkpoints/LEGACY_ACTIVATION_RETIREMENT_V1.json"
MARKER = "LEGACY_ACTIVATION_RETIREMENT_V2_OK"
RETIRED_GENERATION = "tests/test_onyx_live_activation_v19.py"
CURRENT_SUCCESSOR = "tests/test_phase6_current_v1.py"


class LegacyActivationRetirementV2Error(RuntimeError):
    """The append-only retirement chain or a bound file drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(value: object) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise LegacyActivationRetirementV2Error("retirement path is not canonical")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix() != value or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise LegacyActivationRetirementV2Error("retirement path is not canonical")
    return value


def _binding(root: Path, value: object, label: str) -> str:
    if type(value) is not dict or set(value) != {"path", "sha256"}:
        raise LegacyActivationRetirementV2Error(f"{label} binding is malformed")
    relative = _relative(value["path"])
    expected = value["sha256"]
    path = root.joinpath(*PurePosixPath(relative).parts)
    if (
        type(expected) is not str
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
        or path.is_symlink()
        or not path.is_file()
        or path.resolve() != path.absolute()
        or _sha256(path) != expected
    ):
        raise LegacyActivationRetirementV2Error(f"{label} drifted: {relative}")
    return relative


def load_record(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    raw = (root / RECORD.relative_to(PROJECT)).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise LegacyActivationRetirementV2Error("retirement V2 is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
        predecessor = json.loads(
            (root / PREDECESSOR.relative_to(PROJECT)).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LegacyActivationRetirementV2Error("retirement V2 is invalid") from error
    if type(record) is not dict or set(record) != {
        "schema", "issued_at", "predecessor", "policy", "claims"
    }:
        raise LegacyActivationRetirementV2Error("retirement V2 contract drifted")
    if record["schema"] != "onyx.legacy-activation-retirement.v2":
        raise LegacyActivationRetirementV2Error("retirement V2 schema drifted")
    expected_predecessor = {
        "path": "docs/onyx/checkpoints/LEGACY_ACTIVATION_RETIREMENT_V1.json",
        "sha256": _sha256(root / PREDECESSOR.relative_to(PROJECT)),
    }
    if record["predecessor"] != expected_predecessor:
        raise LegacyActivationRetirementV2Error("retirement V1 predecessor drifted")
    expected_policy = predecessor["policy"] | {
        "retired_successor_generations_cannot_be_current": True,
    }
    if record["policy"] != expected_policy:
        raise LegacyActivationRetirementV2Error("retirement V2 policy drifted")
    claims = record["claims"]
    if type(claims) is not list or len(claims) != len(predecessor["claims"]):
        raise LegacyActivationRetirementV2Error("retirement V2 claims drifted")
    predecessor_by_id = {claim["id"]: claim for claim in predecessor["claims"]}
    nodeids: set[str] = set()
    for claim in claims:
        if type(claim) is not dict or set(claim) != {
            "id", "disposition", "historical_test_ids", "historical_sources",
            "successor_tests", "reason"
        }:
            raise LegacyActivationRetirementV2Error("retirement V2 claim malformed")
        original = predecessor_by_id.get(claim["id"])
        if original is None or claim["historical_test_ids"] != original["historical_test_ids"]:
            raise LegacyActivationRetirementV2Error("historical node registry changed")
        if claim["historical_sources"] != original["historical_sources"]:
            raise LegacyActivationRetirementV2Error("historical source registry changed")
        if claim["disposition"] != "superseded-not-rebound":
            raise LegacyActivationRetirementV2Error("retirement disposition drifted")
        for binding in claim["historical_sources"]:
            _binding(root, binding, "historical source")
        successors = [_binding(root, binding, "current successor") for binding in claim["successor_tests"]]
        if claim["id"] == "activation-v1-v11-historical-closures":
            if successors != [CURRENT_SUCCESSOR]:
                raise LegacyActivationRetirementV2Error("active successor is not Phase 6 current")
        elif claim["successor_tests"] != original["successor_tests"]:
            raise LegacyActivationRetirementV2Error("unrelated successor binding changed")
        if RETIRED_GENERATION in successors:
            raise LegacyActivationRetirementV2Error("retired V19 generation is still current")
        for nodeid in claim["historical_test_ids"]:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in nodeids:
                raise LegacyActivationRetirementV2Error("historical node ID drifted")
            nodeids.add(nodeid)
    if len(nodeids) != 44:
        raise LegacyActivationRetirementV2Error("retirement V2 node count drifted")
    return record


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(
        nodeid for claim in load_record(project)["claims"]
        for nodeid in claim["historical_test_ids"]
    )


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in load_record(project)["claims"]:
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise LegacyActivationRetirementV2Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    result = load_record()
    print(MARKER, f"claims={len(result['claims'])}", f"tests={len(registered_test_ids())}")
