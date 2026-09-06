"""Authenticate the V57-V60 to V61 retirement over immutable V20."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from scripts import verify_current_successor_retirement_v20 as predecessor
from scripts.generate_current_successor_retirement_v21 import HISTORICAL_TEST_IDS


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V21.json"
PREDECESSOR_SHA256 = "431d7faf5cda975ddac0c9f805b0a1be0110a33015ab7bf24d2073ed2a1c394e"
RECORD_SHA256 = "e64568819038f25ce05d2815573a298ffd28687ac42f8ffbc74e13914abff7ec"
V20_REGISTERED_ROUTES = 380
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV21Error(RuntimeError):
    """V21, V20, or the V61 successor binding failed closed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_relative_file(root: Path, relative: object, label: str) -> Path:
    parsed = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if (
        parsed.is_absolute()
        or parsed.as_posix() != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise CurrentSuccessorRetirementV21Error(f"{label} path is invalid")
    path = root.joinpath(*parsed.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentSuccessorRetirementV21Error(f"{label} path is invalid") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentSuccessorRetirementV21Error(f"{label} path is invalid")
    return resolved


def _claim(root: Path) -> dict[str, object]:
    raw = RECORD.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256:
        raise CurrentSuccessorRetirementV21Error("retirement V21 digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementV21Error("retirement V21 is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementV21Error("retirement V21 is invalid") from error
    if (
        type(record) is not dict
        or set(record)
        != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or record.get("schema") != "onyx.current-successor-retirement.v21"
        or record.get("predecessor")
        != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V20.json",
            "sha256": PREDECESSOR_SHA256,
        }
        or type(record.get("additional_claims")) is not list
        or len(record["additional_claims"]) != 1
    ):
        raise CurrentSuccessorRetirementV21Error("retirement V21 contract drifted")
    claim = record["additional_claims"][0]
    if (
        type(claim) is not dict
        or set(claim)
        != {"id", "disposition", "historical_test_ids", "successor_tests", "validated_tests", "reason"}
        or claim.get("id") != "release-v57-v60-to-v61-current-authority"
        or claim.get("disposition") != "superseded-not-rebound"
        or claim.get("historical_test_ids") != list(HISTORICAL_TEST_IDS)
        or claim.get("validated_tests") != len(HISTORICAL_TEST_IDS)
        or type(claim.get("reason")) is not str
        or not claim["reason"]
        or type(claim.get("successor_tests")) is not list
        or len(claim["successor_tests"]) != 1
    ):
        raise CurrentSuccessorRetirementV21Error("retirement V21 claim drifted")
    binding = claim["successor_tests"][0]
    if type(binding) is not dict or set(binding) != {"path", "sha256"}:
        raise CurrentSuccessorRetirementV21Error("retirement V21 successor is malformed")
    successor = _strict_relative_file(root, binding["path"], "retirement V21 successor")
    if _sha256(successor) != binding["sha256"]:
        raise CurrentSuccessorRetirementV21Error("retirement V21 successor drifted")
    return claim


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    predecessor_path = _strict_relative_file(
        root,
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V20.json",
        "retirement V20 predecessor",
    )
    if _sha256(predecessor_path) != PREDECESSOR_SHA256:
        raise CurrentSuccessorRetirementV21Error("retirement V20 predecessor drifted")
    predecessor_claims = predecessor._current_claims(root)
    if len(predecessor.registered_test_ids(root)) != V20_REGISTERED_ROUTES:
        raise CurrentSuccessorRetirementV21Error("retirement V20 routes drifted")
    return (_claim(root),) + tuple(predecessor_claims)


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(
        node
        for claim in _current_claims(project)
        for node in claim["historical_test_ids"]
    )


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementV21Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    claims = _current_claims()
    print(
        "CURRENT_SUCCESSOR_RETIREMENT_V21_OK",
        f"claims={len(claims)}",
        f"tests={len(registered_test_ids())}",
    )
