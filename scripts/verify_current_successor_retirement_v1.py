"""Authenticate closed historical-test retirement to current successor suites."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
GREATGRANDPREDECESSOR_RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V1.json"
GREATGRANDPREDECESSOR_RECORD_SHA256 = "04fe14acefec53c6522e7aeba7271f64e8244de713a5ae82a46a8c0e2cbeb73f"
GRANDPREDECESSOR_RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V2.json"
GRANDPREDECESSOR_RECORD_SHA256 = "e73f77e0b83d3a6de0d277131a6ba742ea1e204c8c8d248d03f994b24f903d37"
PREDECESSOR_RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V3.json"
PREDECESSOR_RECORD_SHA256 = "4521b734b40c7bcc309980aa4a8c81d6a8434455d0194ed62396c90ba19abe8a"
CURRENT_PREDECESSOR_RECORD_V4 = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V4.json"
CURRENT_PREDECESSOR_RECORD_V4_SHA256 = "a810e3ec9fc2e04ec2581180f0d24c7a01660320a1993140a9dc4c0a187297db"
CURRENT_PREDECESSOR_RECORD_V5 = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V5.json"
CURRENT_PREDECESSOR_RECORD_V5_SHA256 = "32cf6ebc7c841355064cef2befbc637efda93e3318dec52fdfe059a4266d516d"
CURRENT_PREDECESSOR_RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V6.json"
CURRENT_PREDECESSOR_RECORD_SHA256 = "32f74a34de4a8902d4be56f4fd7acc1c265f396467a1407f6df7d17be9fe918b"
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V7.json"
RECORD_SHA256 = "aab8b653adf8960d951bff09422ce1ab8efe09bcf44d3a575690a6345b00e973"
EXTENSION_RECORD = (
    PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V8.json"
)
CURRENT_EXTENSION_RECORD = (
    PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V9.json"
)
LATEST_EXTENSION_RECORD = (
    PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V10.json"
)
LATEST_EXTENSION_RECORD_SHA256 = (
    "45b03775c218654916db57b9d7abe5ef8cdb760140b047333567fa5ea7a96cf9"
)
CURRENT_EXTENSION_RECORD_V11 = (
    PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V11.json"
)
CURRENT_EXTENSION_RECORD_V11_SHA256 = (
    "989ca75b133a92705a4d8f50c8f7d2e7e70118b140b27e3e7359761f3166c625"
)
CURRENT_EXTENSION_RECORD_V12 = (
    PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V12.json"
)
CURRENT_EXTENSION_RECORD_V12_SHA256 = (
    "c7e9c1b548e7085ec8644beb77bc545426c85c7e4f92dfe21f4634f3d3239fd4"
)
CURRENT_EXTENSION_RECORD_V13 = (
    PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V13.json"
)
CURRENT_EXTENSION_RECORD_V13_SHA256 = (
    "17edde3d63686916335e920df708e07c0985830ae4a4f77f60cb26091ba62735"
)
CURRENT_EXTENSION_RECORD_V14 = (
    PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V14.json"
)
CURRENT_EXTENSION_RECORD_V14_SHA256 = (
    "84edfabc9e1b3a0b8a143586e695e98827b16f840839b727f8cec40e5a81b9a7"
)
CURRENT_EXTENSION_RECORD_V15 = (
    PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V15.json"
)
CURRENT_EXTENSION_RECORD_V15_SHA256 = (
    "d851155d99a8d131b98ef5087967093f9ad94a53359a91623580692cfa9552e5"
)
EXTENSION_RECORD_SHA256 = (
    "6a839b0a551e81a8ff08e379dd4428cf14f61dd75a9cf532879332a1575c1f28"
)


class CurrentSuccessorRetirementError(RuntimeError):
    """The closed retirement record or a named current successor drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_v15_record(
    *,
    raw: bytes,
    root: Path,
    policy: object,
    registered_nodeids: set[str],
    expected_digest: str,
) -> tuple[dict[str, object], ...]:
    """Validate the additive V15 registry without weakening V1-V14."""

    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise CurrentSuccessorRetirementError("retirement V15 digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementError("retirement V15 is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V15 is invalid") from error
    if (
        type(record) is not dict
        or set(record)
        != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or record.get("schema") != "onyx.current-successor-retirement.v15"
        or record.get("predecessor")
        != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V14.json",
            "sha256": CURRENT_EXTENSION_RECORD_V14_SHA256,
        }
        or record.get("policy") != policy
        or type(record.get("additional_claims")) is not list
        or len(record["additional_claims"]) != 6
    ):
        raise CurrentSuccessorRetirementError("retirement V15 contract drifted")
    claim_ids: list[str] = []
    claims: list[dict[str, object]] = []
    for claim in record["additional_claims"]:
        if type(claim) is not dict or set(claim) != {
            "id",
            "disposition",
            "historical_test_ids",
            "successor_tests",
            "validated_tests",
            "reason",
        }:
            raise CurrentSuccessorRetirementError("retirement V15 claim is malformed")
        historical = claim["historical_test_ids"]
        successors = claim["successor_tests"]
        if (
            type(claim["id"]) is not str
            or not claim["id"]
            or claim["disposition"] != "superseded-not-rebound"
            or type(historical) is not list
            or not historical
            or type(successors) is not list
            or len(successors) != 1
            or claim["validated_tests"] != 1
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementError("retirement V15 claim is invalid")
        claim_ids.append(claim["id"])
        claims.append(claim)
        for nodeid in historical:
            if (
                type(nodeid) is not str
                or "::" not in nodeid
                or nodeid in registered_nodeids
                or any(
                    word in nodeid.lower()
                    for word in ("tamper", "reject", "refuse", "security")
                )
            ):
                raise CurrentSuccessorRetirementError(
                    "retirement V15 test ID is invalid"
                )
            _relative(nodeid.split("::", 1)[0])
            registered_nodeids.add(nodeid)
        successor = successors[0]
        if type(successor) is not dict or set(successor) != {"path", "sha256"}:
            raise CurrentSuccessorRetirementError(
                "retirement V15 successor binding is malformed"
            )
        relative = _relative(successor["path"])
        expected = successor["sha256"]
        path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as error:
            raise CurrentSuccessorRetirementError(
                f"retirement V15 successor path is invalid: {relative}"
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
            raise CurrentSuccessorRetirementError(
                f"retirement V15 successor drifted: {relative}"
            )
    if claim_ids != sorted(claim_ids) or len(registered_nodeids) != 102:
        raise CurrentSuccessorRetirementError("retirement V15 registry drifted")
    return tuple(claims)


def _matches_authenticated_successor(
    *, root: Path, relative: str, predecessor_sha256: str, current_sha256: str
) -> bool:
    """Accept a changed successor only through the current Phase 5 transition."""

    if root != PROJECT.resolve():
        return False
    try:
        from scripts.verify_phase5_exit_retirement_v1 import (
            load_current_successor_transition,
        )

        transition = load_current_successor_transition()
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    for successor in transition.get("named_successors", ()):
        if (
            type(successor) is dict
            and successor.get("path") == relative
            and successor.get("predecessor_sha256") == predecessor_sha256
            and successor.get("current_sha256") == current_sha256
        ):
            return True
    return False


def _relative(value: object) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise CurrentSuccessorRetirementError("retirement path is not canonical")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix() != value or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise CurrentSuccessorRetirementError("retirement path is not canonical")
    return value


def load_record(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    raw = (root / RECORD.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256:
        raise CurrentSuccessorRetirementError("retirement record digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementError("retirement record is not canonical")
    try:
        successor = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement record is invalid") from error
    if (
        type(successor) is not dict
        or successor.get("schema") != "onyx.current-successor-retirement.v7"
        or successor.get("predecessor") != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V6.json",
            "sha256": CURRENT_PREDECESSOR_RECORD_SHA256,
        }
        or successor.get("phase5_current_successor") != {
            "path": "tests/fixtures/phase5_current_successor_transition_v40.json",
            "sha256": "e043cdb0aaf0e6218f34df2f0a1c214f1e90e62a7eb921ec9edb0634bbacd706",
        }
        or successor.get("policy") != {
            "predecessor_is_immutable": True,
            "historical_hashes_are_rebound": False,
            "current_successors_are_sha256_bound": True,
        }
        or successor.get("current_successors") != [{
            "path": "tests/test_onyx_live_activation_v19.py",
            "predecessor_sha256": "e2538899a792e25d1aa9411a5e5750457344eeeef199913af1c841b740bb46b3",
            "current_sha256": "3932f26b5024ae381208e7a121afecc7249f244093aaf514043230f187f21381",
        }]
    ):
        raise CurrentSuccessorRetirementError("retirement successor contract drifted")
    phase_path = root / successor["phase5_current_successor"]["path"]
    current_path = root / successor["current_successors"][0]["path"]
    if (
        _sha256(phase_path) != successor["phase5_current_successor"]["sha256"]
        or _sha256(current_path) != successor["current_successors"][0]["current_sha256"]
    ):
        raise CurrentSuccessorRetirementError("retirement successor binding drifted")
    current_predecessor_raw = CURRENT_PREDECESSOR_RECORD.read_bytes()
    if hashlib.sha256(current_predecessor_raw).hexdigest() != CURRENT_PREDECESSOR_RECORD_SHA256:
        raise CurrentSuccessorRetirementError("retirement V6 predecessor digest drifted")
    try:
        current_predecessor = json.loads(current_predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V6 predecessor is invalid") from error
    if (
        type(current_predecessor) is not dict
        or current_predecessor.get("schema") != "onyx.current-successor-retirement.v6"
        or current_predecessor.get("predecessor") != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V5.json",
            "sha256": CURRENT_PREDECESSOR_RECORD_V5_SHA256,
        }
        or current_predecessor.get("phase5_current_successor") != {
            "path": "tests/fixtures/phase5_current_successor_transition_v39.json",
            "sha256": "0e245140f43fc4348f91d35281fa54276a0243f30d94c468bdfb564dc30dcd2a",
        }
        or current_predecessor.get("policy") != successor["policy"]
        or current_predecessor.get("current_successors") != successor["current_successors"]
    ):
        raise CurrentSuccessorRetirementError("retirement V6 predecessor contract drifted")
    predecessor_v5_raw = CURRENT_PREDECESSOR_RECORD_V5.read_bytes()
    if hashlib.sha256(predecessor_v5_raw).hexdigest() != CURRENT_PREDECESSOR_RECORD_V5_SHA256:
        raise CurrentSuccessorRetirementError("retirement V5 predecessor digest drifted")
    try:
        predecessor_v5 = json.loads(predecessor_v5_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V5 predecessor is invalid") from error
    if (
        type(predecessor_v5) is not dict
        or predecessor_v5.get("schema") != "onyx.current-successor-retirement.v5"
        or predecessor_v5.get("predecessor") != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V4.json",
            "sha256": CURRENT_PREDECESSOR_RECORD_V4_SHA256,
        }
        or predecessor_v5.get("phase5_current_successor") != {
            "path": "tests/fixtures/phase5_current_successor_transition_v38.json",
            "sha256": "9b2dfdefdec21b3181799937b8f41721a744cc3652d9ccbd2302eebf8997488f",
        }
        or predecessor_v5.get("policy") != successor["policy"]
        or predecessor_v5.get("current_successors") != successor["current_successors"]
    ):
        raise CurrentSuccessorRetirementError("retirement V5 predecessor contract drifted")
    predecessor_v4_raw = CURRENT_PREDECESSOR_RECORD_V4.read_bytes()
    if hashlib.sha256(predecessor_v4_raw).hexdigest() != CURRENT_PREDECESSOR_RECORD_V4_SHA256:
        raise CurrentSuccessorRetirementError("retirement V4 predecessor digest drifted")
    try:
        predecessor_v4 = json.loads(predecessor_v4_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V4 predecessor is invalid") from error
    if (
        type(predecessor_v4) is not dict
        or predecessor_v4.get("schema") != "onyx.current-successor-retirement.v4"
        or predecessor_v4.get("predecessor") != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V3.json",
            "sha256": PREDECESSOR_RECORD_SHA256,
        }
        or predecessor_v4.get("phase5_current_successor") != {
            "path": "tests/fixtures/phase5_current_successor_transition_v37.json",
            "sha256": "7e6ad9282d101666953f80b11278349c95aed5715f2530c2870c18bebc9341af",
        }
        or predecessor_v4.get("policy") != successor["policy"]
        or predecessor_v4.get("current_successors") != successor["current_successors"]
    ):
        raise CurrentSuccessorRetirementError("retirement V4 predecessor contract drifted")
    predecessor_raw = (root / PREDECESSOR_RECORD.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(predecessor_raw).hexdigest() != PREDECESSOR_RECORD_SHA256:
        raise CurrentSuccessorRetirementError("retirement predecessor digest drifted")
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement predecessor is invalid") from error
    if (
        type(predecessor) is not dict
        or predecessor.get("schema") != "onyx.current-successor-retirement.v3"
        or predecessor.get("predecessor") != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V2.json",
            "sha256": GRANDPREDECESSOR_RECORD_SHA256,
        }
        or predecessor.get("phase5_current_successor") != {
            "path": "tests/fixtures/phase5_current_successor_transition_v36.json",
            "sha256": "a1685eeeeaed0cdbcc7d4b1405036b64548733890e5bfc38c0e5053db6696546",
        }
        or predecessor.get("policy") != successor["policy"]
        or predecessor.get("current_successors") != successor["current_successors"]
    ):
        raise CurrentSuccessorRetirementError("retirement predecessor contract drifted")
    grandpredecessor_raw = (
        root / GRANDPREDECESSOR_RECORD.relative_to(PROJECT)
    ).read_bytes()
    if hashlib.sha256(grandpredecessor_raw).hexdigest() != GRANDPREDECESSOR_RECORD_SHA256:
        raise CurrentSuccessorRetirementError("retirement grandpredecessor digest drifted")
    try:
        grandpredecessor = json.loads(grandpredecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement grandpredecessor is invalid") from error
    if (
        type(grandpredecessor) is not dict
        or grandpredecessor.get("schema") != "onyx.current-successor-retirement.v2"
        or grandpredecessor.get("predecessor") != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V1.json",
            "sha256": GREATGRANDPREDECESSOR_RECORD_SHA256,
        }
        or grandpredecessor.get("phase5_current_successor") != {
            "path": "tests/fixtures/phase5_current_successor_transition_v35.json",
            "sha256": "10bae13d3f14767cf69d74d935783e306de675b098e06a6c175f254a5469ca2d",
        }
        or grandpredecessor.get("policy") != successor["policy"]
        or grandpredecessor.get("current_successors") != successor["current_successors"]
    ):
        raise CurrentSuccessorRetirementError("retirement grandpredecessor contract drifted")
    greatgrandpredecessor_raw = (
        root / GREATGRANDPREDECESSOR_RECORD.relative_to(PROJECT)
    ).read_bytes()
    if hashlib.sha256(greatgrandpredecessor_raw).hexdigest() != GREATGRANDPREDECESSOR_RECORD_SHA256:
        raise CurrentSuccessorRetirementError("retirement great-grandpredecessor digest drifted")
    try:
        record = json.loads(greatgrandpredecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement great-grandpredecessor is invalid") from error
    successor_current = {
        binding["path"]: binding["current_sha256"]
        for binding in successor["current_successors"]
    }
    if type(record) is not dict or set(record) != {
        "schema", "issued_at", "policy", "claims"
    }:
        raise CurrentSuccessorRetirementError("retirement contract drifted")
    if (
        record["schema"] != "onyx.current-successor-retirement.v1"
        or record["policy"]
        != {
            "historical_tests_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "registered_nodes_must_remain_collected": True,
            "successor_sources_are_sha256_bound": True,
            "successor_tests_must_execute": True,
        }
        or type(record["claims"]) is not list
        or len(record["claims"]) != 8
    ):
        raise CurrentSuccessorRetirementError("retirement policy drifted")
    nodeids: set[str] = set()
    claim_ids: list[str] = []
    for claim in record["claims"]:
        if type(claim) is not dict or set(claim) != {
            "id", "disposition", "historical_test_ids", "successor_tests",
            "validated_tests", "reason"
        }:
            raise CurrentSuccessorRetirementError("retirement claim is malformed")
        if type(claim["id"]) is not str or not claim["id"]:
            raise CurrentSuccessorRetirementError("retirement claim ID is invalid")
        claim_ids.append(claim["id"])
        historical = claim["historical_test_ids"]
        successors = claim["successor_tests"]
        if (
            claim["disposition"] != "superseded-not-rebound"
            or type(historical) is not list
            or not historical
            or type(successors) is not list
            or not successors
            or type(claim["validated_tests"]) is not int
            or claim["validated_tests"] < 1
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementError("retirement claim is invalid")
        for nodeid in historical:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in nodeids:
                raise CurrentSuccessorRetirementError("retired test ID is invalid")
            _relative(nodeid.split("::", 1)[0])
            nodeids.add(nodeid)
        for successor in successors:
            if type(successor) is not dict or set(successor) != {"path", "sha256"}:
                raise CurrentSuccessorRetirementError("successor binding is malformed")
            relative = _relative(successor["path"])
            expected = successor["sha256"]
            if (
                type(expected) is not str
                or len(expected) != 64
                or any(character not in "0123456789abcdef" for character in expected)
            ):
                raise CurrentSuccessorRetirementError("successor digest is invalid")
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise CurrentSuccessorRetirementError(
                    f"current successor path is invalid: {relative}"
                ) from error
            if (
                path.is_symlink()
                or resolved != path.absolute()
                or not resolved.is_file()
            ):
                raise CurrentSuccessorRetirementError(
                    f"current successor drifted: {relative}"
                )
            actual_sha256 = _sha256(resolved)
            if (
                actual_sha256 != expected
                and successor_current.get(relative) != actual_sha256
                and not _matches_authenticated_successor(
                    root=root,
                    relative=relative,
                    predecessor_sha256=expected,
                    current_sha256=actual_sha256,
                )
            ):
                raise CurrentSuccessorRetirementError(
                    f"current successor drifted: {relative}"
                )
    if claim_ids != sorted(claim_ids) or len(nodeids) != 17:
        raise CurrentSuccessorRetirementError("retirement registry drifted")
    return record


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    base = load_record(root)
    raw = (root / EXTENSION_RECORD.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXTENSION_RECORD_SHA256:
        raise CurrentSuccessorRetirementError("retirement V8 digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementError("retirement V8 is not canonical")
    try:
        extension = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V8 is invalid") from error
    if (
        type(extension) is not dict
        or set(extension)
        != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or extension.get("schema") != "onyx.current-successor-retirement.v8"
        or extension.get("predecessor")
        != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V7.json",
            "sha256": RECORD_SHA256,
        }
        or extension.get("policy") != base["policy"]
        or type(extension.get("additional_claims")) is not list
        or len(extension["additional_claims"]) != 4
    ):
        raise CurrentSuccessorRetirementError("retirement V8 contract drifted")

    claims = tuple(base["claims"]) + tuple(extension["additional_claims"])
    nodeids = {
        nodeid
        for claim in base["claims"]
        for nodeid in claim["historical_test_ids"]
    }
    extension_ids: list[str] = []
    for claim in extension["additional_claims"]:
        if type(claim) is not dict or set(claim) != {
            "id",
            "disposition",
            "historical_test_ids",
            "successor_tests",
            "validated_tests",
            "reason",
        }:
            raise CurrentSuccessorRetirementError("retirement V8 claim is malformed")
        historical = claim["historical_test_ids"]
        successors = claim["successor_tests"]
        if (
            type(claim["id"]) is not str
            or not claim["id"]
            or claim["disposition"] != "superseded-not-rebound"
            or type(historical) is not list
            or not historical
            or type(successors) is not list
            or not successors
            or type(claim["validated_tests"]) is not int
            or claim["validated_tests"] < 1
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementError("retirement V8 claim is invalid")
        extension_ids.append(claim["id"])
        for nodeid in historical:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in nodeids:
                raise CurrentSuccessorRetirementError("retirement V8 test ID is invalid")
            _relative(nodeid.split("::", 1)[0])
            nodeids.add(nodeid)
        for successor in successors:
            if type(successor) is not dict or set(successor) != {"path", "sha256"}:
                raise CurrentSuccessorRetirementError(
                    "retirement V8 successor binding is malformed"
                )
            relative = _relative(successor["path"])
            expected = successor["sha256"]
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise CurrentSuccessorRetirementError(
                    f"retirement V8 successor path is invalid: {relative}"
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
                raise CurrentSuccessorRetirementError(
                    f"retirement V8 successor drifted: {relative}"
                )
    if extension_ids != sorted(extension_ids) or len(nodeids) != 26:
        raise CurrentSuccessorRetirementError("retirement V8 registry drifted")

    current_raw = (root / CURRENT_EXTENSION_RECORD.relative_to(PROJECT)).read_bytes()
    if current_raw.startswith(b"\xef\xbb\xbf") or b"\r" in current_raw or not current_raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementError("retirement V9 is not canonical")
    try:
        current = json.loads(current_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V9 is invalid") from error
    if (
        type(current) is not dict
        or set(current)
        != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or current.get("schema") != "onyx.current-successor-retirement.v9"
        or current.get("predecessor")
        != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V8.json",
            "sha256": _sha256(root / EXTENSION_RECORD.relative_to(PROJECT)),
        }
        or current.get("policy") != base["policy"]
        or type(current.get("additional_claims")) is not list
        or len(current["additional_claims"]) != 2
    ):
        raise CurrentSuccessorRetirementError("retirement V9 contract drifted")

    current_ids: list[str] = []
    for claim in current["additional_claims"]:
        if type(claim) is not dict or set(claim) != {
            "id",
            "disposition",
            "historical_test_ids",
            "successor_tests",
            "validated_tests",
            "reason",
        }:
            raise CurrentSuccessorRetirementError("retirement V9 claim is malformed")
        historical = claim["historical_test_ids"]
        successors = claim["successor_tests"]
        if (
            type(claim["id"]) is not str
            or not claim["id"]
            or claim["disposition"] != "superseded-not-rebound"
            or type(historical) is not list
            or not historical
            or type(successors) is not list
            or not successors
            or type(claim["validated_tests"]) is not int
            or claim["validated_tests"] < 1
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementError("retirement V9 claim is invalid")
        current_ids.append(claim["id"])
        for nodeid in historical:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in nodeids:
                raise CurrentSuccessorRetirementError("retirement V9 test ID is invalid")
            _relative(nodeid.split("::", 1)[0])
            nodeids.add(nodeid)
        for successor in successors:
            if type(successor) is not dict or set(successor) != {"path", "sha256"}:
                raise CurrentSuccessorRetirementError(
                    "retirement V9 successor binding is malformed"
                )
            relative = _relative(successor["path"])
            expected = successor["sha256"]
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise CurrentSuccessorRetirementError(
                    f"retirement V9 successor path is invalid: {relative}"
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
                raise CurrentSuccessorRetirementError(
                    f"retirement V9 successor drifted: {relative}"
                )
    if current_ids != sorted(current_ids) or len(nodeids) != 28:
        raise CurrentSuccessorRetirementError("retirement V9 registry drifted")

    latest_raw = (root / LATEST_EXTENSION_RECORD.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(latest_raw).hexdigest() != LATEST_EXTENSION_RECORD_SHA256:
        raise CurrentSuccessorRetirementError("retirement V10 digest drifted")
    if latest_raw.startswith(b"\xef\xbb\xbf") or b"\r" in latest_raw or not latest_raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementError("retirement V10 is not canonical")
    try:
        latest = json.loads(latest_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V10 is invalid") from error
    if (
        type(latest) is not dict
        or set(latest)
        != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or latest.get("schema") != "onyx.current-successor-retirement.v10"
        or latest.get("predecessor")
        != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V9.json",
            "sha256": _sha256(root / CURRENT_EXTENSION_RECORD.relative_to(PROJECT)),
        }
        or latest.get("policy") != base["policy"]
        or type(latest.get("additional_claims")) is not list
        or len(latest["additional_claims"]) != 4
    ):
        raise CurrentSuccessorRetirementError("retirement V10 contract drifted")
    latest_ids: list[str] = []
    for claim in latest["additional_claims"]:
        if type(claim) is not dict or set(claim) != {
            "id",
            "disposition",
            "historical_test_ids",
            "successor_tests",
            "validated_tests",
            "reason",
        }:
            raise CurrentSuccessorRetirementError("retirement V10 claim is malformed")
        historical = claim["historical_test_ids"]
        successors = claim["successor_tests"]
        if (
            type(claim["id"]) is not str
            or not claim["id"]
            or claim["disposition"] != "superseded-not-rebound"
            or type(historical) is not list
            or not historical
            or type(successors) is not list
            or not successors
            or type(claim["validated_tests"]) is not int
            or claim["validated_tests"] < 1
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementError("retirement V10 claim is invalid")
        latest_ids.append(claim["id"])
        for nodeid in historical:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in nodeids:
                raise CurrentSuccessorRetirementError(
                    "retirement V10 test ID is invalid"
                )
            _relative(nodeid.split("::", 1)[0])
            nodeids.add(nodeid)
        for successor in successors:
            if type(successor) is not dict or set(successor) != {"path", "sha256"}:
                raise CurrentSuccessorRetirementError(
                    "retirement V10 successor binding is malformed"
                )
            relative = _relative(successor["path"])
            expected = successor["sha256"]
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise CurrentSuccessorRetirementError(
                    f"retirement V10 successor path is invalid: {relative}"
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
                raise CurrentSuccessorRetirementError(
                    f"retirement V10 successor drifted: {relative}"
                )
    if latest_ids != sorted(latest_ids) or len(nodeids) != 67:
        raise CurrentSuccessorRetirementError("retirement V10 registry drifted")
    v11_raw = (root / CURRENT_EXTENSION_RECORD_V11.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(v11_raw).hexdigest() != CURRENT_EXTENSION_RECORD_V11_SHA256:
        raise CurrentSuccessorRetirementError("retirement V11 digest drifted")
    if v11_raw.startswith(b"\xef\xbb\xbf") or b"\r" in v11_raw or not v11_raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementError("retirement V11 is not canonical")
    try:
        v11 = json.loads(v11_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V11 is invalid") from error
    if (
        type(v11) is not dict
        or set(v11)
        != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or v11.get("schema") != "onyx.current-successor-retirement.v11"
        or v11.get("predecessor")
        != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V10.json",
            "sha256": LATEST_EXTENSION_RECORD_SHA256,
        }
        or v11.get("policy") != base["policy"]
        or type(v11.get("additional_claims")) is not list
        or len(v11["additional_claims"]) != 2
    ):
        raise CurrentSuccessorRetirementError("retirement V11 contract drifted")
    v11_ids: list[str] = []
    for claim in v11["additional_claims"]:
        if type(claim) is not dict or set(claim) != {
            "id",
            "disposition",
            "historical_test_ids",
            "successor_tests",
            "validated_tests",
            "reason",
        }:
            raise CurrentSuccessorRetirementError("retirement V11 claim is malformed")
        historical = claim["historical_test_ids"]
        successors = claim["successor_tests"]
        if (
            type(claim["id"]) is not str
            or not claim["id"]
            or claim["disposition"] != "superseded-not-rebound"
            or type(historical) is not list
            or not historical
            or type(successors) is not list
            or not successors
            or type(claim["validated_tests"]) is not int
            or claim["validated_tests"] < 1
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementError("retirement V11 claim is invalid")
        v11_ids.append(claim["id"])
        for nodeid in historical:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in nodeids:
                raise CurrentSuccessorRetirementError(
                    "retirement V11 test ID is invalid"
                )
            _relative(nodeid.split("::", 1)[0])
            nodeids.add(nodeid)
        for successor in successors:
            if type(successor) is not dict or set(successor) != {"path", "sha256"}:
                raise CurrentSuccessorRetirementError(
                    "retirement V11 successor binding is malformed"
                )
            relative = _relative(successor["path"])
            expected = successor["sha256"]
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise CurrentSuccessorRetirementError(
                    f"retirement V11 successor path is invalid: {relative}"
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
                raise CurrentSuccessorRetirementError(
                    f"retirement V11 successor drifted: {relative}"
                )
    if v11_ids != sorted(v11_ids) or len(nodeids) != 70:
        raise CurrentSuccessorRetirementError("retirement V11 registry drifted")
    v12_raw = (root / CURRENT_EXTENSION_RECORD_V12.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(v12_raw).hexdigest() != CURRENT_EXTENSION_RECORD_V12_SHA256:
        raise CurrentSuccessorRetirementError("retirement V12 digest drifted")
    if v12_raw.startswith(b"\xef\xbb\xbf") or b"\r" in v12_raw or not v12_raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementError("retirement V12 is not canonical")
    try:
        v12 = json.loads(v12_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V12 is invalid") from error
    if (
        type(v12) is not dict
        or set(v12)
        != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or v12.get("schema") != "onyx.current-successor-retirement.v12"
        or v12.get("predecessor")
        != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V11.json",
            "sha256": CURRENT_EXTENSION_RECORD_V11_SHA256,
        }
        or v12.get("policy") != base["policy"]
        or type(v12.get("additional_claims")) is not list
        or len(v12["additional_claims"]) != 1
    ):
        raise CurrentSuccessorRetirementError("retirement V12 contract drifted")
    v12_ids: list[str] = []
    for claim in v12["additional_claims"]:
        if type(claim) is not dict or set(claim) != {
            "id",
            "disposition",
            "historical_test_ids",
            "successor_tests",
            "validated_tests",
            "reason",
        }:
            raise CurrentSuccessorRetirementError("retirement V12 claim is malformed")
        historical = claim["historical_test_ids"]
        successors = claim["successor_tests"]
        if (
            type(claim["id"]) is not str
            or not claim["id"]
            or claim["disposition"] != "superseded-not-rebound"
            or type(historical) is not list
            or not historical
            or type(successors) is not list
            or not successors
            or type(claim["validated_tests"]) is not int
            or claim["validated_tests"] < 1
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementError("retirement V12 claim is invalid")
        v12_ids.append(claim["id"])
        for nodeid in historical:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in nodeids:
                raise CurrentSuccessorRetirementError(
                    "retirement V12 test ID is invalid"
                )
            _relative(nodeid.split("::", 1)[0])
            nodeids.add(nodeid)
        for successor in successors:
            if type(successor) is not dict or set(successor) != {"path", "sha256"}:
                raise CurrentSuccessorRetirementError(
                    "retirement V12 successor binding is malformed"
                )
            relative = _relative(successor["path"])
            expected = successor["sha256"]
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise CurrentSuccessorRetirementError(
                    f"retirement V12 successor path is invalid: {relative}"
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
                raise CurrentSuccessorRetirementError(
                    f"retirement V12 successor drifted: {relative}"
                )
    if v12_ids != sorted(v12_ids) or len(nodeids) != 72:
        raise CurrentSuccessorRetirementError("retirement V12 registry drifted")
    v13_raw = (root / CURRENT_EXTENSION_RECORD_V13.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(v13_raw).hexdigest() != CURRENT_EXTENSION_RECORD_V13_SHA256:
        raise CurrentSuccessorRetirementError("retirement V13 digest drifted")
    if v13_raw.startswith(b"\xef\xbb\xbf") or b"\r" in v13_raw or not v13_raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementError("retirement V13 is not canonical")
    try:
        v13 = json.loads(v13_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V13 is invalid") from error
    if (
        type(v13) is not dict
        or set(v13)
        != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or v13.get("schema") != "onyx.current-successor-retirement.v13"
        or v13.get("predecessor")
        != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V12.json",
            "sha256": CURRENT_EXTENSION_RECORD_V12_SHA256,
        }
        or v13.get("policy") != base["policy"]
        or type(v13.get("additional_claims")) is not list
        or len(v13["additional_claims"]) != 1
    ):
        raise CurrentSuccessorRetirementError("retirement V13 contract drifted")
    v13_ids: list[str] = []
    for claim in v13["additional_claims"]:
        if type(claim) is not dict or set(claim) != {
            "id",
            "disposition",
            "historical_test_ids",
            "successor_tests",
            "validated_tests",
            "reason",
        }:
            raise CurrentSuccessorRetirementError("retirement V13 claim is malformed")
        historical = claim["historical_test_ids"]
        successors = claim["successor_tests"]
        if (
            type(claim["id"]) is not str
            or not claim["id"]
            or claim["disposition"] != "superseded-not-rebound"
            or type(historical) is not list
            or not historical
            or type(successors) is not list
            or not successors
            or type(claim["validated_tests"]) is not int
            or claim["validated_tests"] < 1
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementError("retirement V13 claim is invalid")
        v13_ids.append(claim["id"])
        for nodeid in historical:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in nodeids:
                raise CurrentSuccessorRetirementError(
                    "retirement V13 test ID is invalid"
                )
            _relative(nodeid.split("::", 1)[0])
            nodeids.add(nodeid)
        for successor in successors:
            if type(successor) is not dict or set(successor) != {"path", "sha256"}:
                raise CurrentSuccessorRetirementError(
                    "retirement V13 successor binding is malformed"
                )
            relative = _relative(successor["path"])
            expected = successor["sha256"]
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise CurrentSuccessorRetirementError(
                    f"retirement V13 successor path is invalid: {relative}"
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
                raise CurrentSuccessorRetirementError(
                    f"retirement V13 successor drifted: {relative}"
                )
    if v13_ids != sorted(v13_ids) or len(nodeids) != 74:
        raise CurrentSuccessorRetirementError("retirement V13 registry drifted")
    v14_raw = (root / CURRENT_EXTENSION_RECORD_V14.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(v14_raw).hexdigest() != CURRENT_EXTENSION_RECORD_V14_SHA256:
        raise CurrentSuccessorRetirementError("retirement V14 digest drifted")
    if v14_raw.startswith(b"\xef\xbb\xbf") or b"\r" in v14_raw or not v14_raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementError("retirement V14 is not canonical")
    try:
        v14 = json.loads(v14_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementError("retirement V14 is invalid") from error
    if (
        type(v14) is not dict
        or set(v14)
        != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or v14.get("schema") != "onyx.current-successor-retirement.v14"
        or v14.get("predecessor")
        != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V13.json",
            "sha256": CURRENT_EXTENSION_RECORD_V13_SHA256,
        }
        or v14.get("policy") != base["policy"]
        or type(v14.get("additional_claims")) is not list
        or len(v14["additional_claims"]) != 1
    ):
        raise CurrentSuccessorRetirementError("retirement V14 contract drifted")
    v14_ids: list[str] = []
    for claim in v14["additional_claims"]:
        if type(claim) is not dict or set(claim) != {
            "id",
            "disposition",
            "historical_test_ids",
            "successor_tests",
            "validated_tests",
            "reason",
        }:
            raise CurrentSuccessorRetirementError("retirement V14 claim is malformed")
        historical = claim["historical_test_ids"]
        successors = claim["successor_tests"]
        if (
            type(claim["id"]) is not str
            or not claim["id"]
            or claim["disposition"] != "superseded-not-rebound"
            or type(historical) is not list
            or not historical
            or type(successors) is not list
            or not successors
            or type(claim["validated_tests"]) is not int
            or claim["validated_tests"] < 1
            or type(claim["reason"]) is not str
            or not claim["reason"]
        ):
            raise CurrentSuccessorRetirementError("retirement V14 claim is invalid")
        v14_ids.append(claim["id"])
        for nodeid in historical:
            if type(nodeid) is not str or "::" not in nodeid or nodeid in nodeids:
                raise CurrentSuccessorRetirementError(
                    "retirement V14 test ID is invalid"
                )
            _relative(nodeid.split("::", 1)[0])
            nodeids.add(nodeid)
        for successor in successors:
            if type(successor) is not dict or set(successor) != {"path", "sha256"}:
                raise CurrentSuccessorRetirementError(
                    "retirement V14 successor binding is malformed"
                )
            relative = _relative(successor["path"])
            expected = successor["sha256"]
            path = root.joinpath(*PurePosixPath(relative).parts)
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise CurrentSuccessorRetirementError(
                    f"retirement V14 successor path is invalid: {relative}"
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
                raise CurrentSuccessorRetirementError(
                    f"retirement V14 successor drifted: {relative}"
                )
    if v14_ids != sorted(v14_ids) or len(nodeids) != 76:
        raise CurrentSuccessorRetirementError("retirement V14 registry drifted")
    v15_raw = (root / CURRENT_EXTENSION_RECORD_V15.relative_to(PROJECT)).read_bytes()
    v15_claims = _validate_v15_record(
        raw=v15_raw,
        root=root,
        policy=base["policy"],
        registered_nodeids=nodeids,
        expected_digest=CURRENT_EXTENSION_RECORD_V15_SHA256,
    )
    return (
        claims
        + tuple(current["additional_claims"])
        + tuple(latest["additional_claims"])
        + tuple(v11["additional_claims"])
        + tuple(v12["additional_claims"])
        + tuple(v13["additional_claims"])
        + tuple(v14["additional_claims"])
        + v15_claims
    )


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    claims = _current_claims(project)
    return frozenset(
        nodeid
        for claim in claims
        for nodeid in claim["historical_test_ids"]
    )


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementError(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    claims = _current_claims()
    print(
        "CURRENT_SUCCESSOR_RETIREMENT_V15_OK",
        f"claims={len(claims)}",
        f"tests={len(registered_test_ids())}",
    )
