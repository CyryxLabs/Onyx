"""Authenticate V63 to V64 retirement over immutable V22."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v22 as predecessor
from scripts.generate_current_successor_retirement_v23 import HISTORICAL_TEST_IDS, build


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V23.json"
PREDECESSOR_SHA256 = "15d1e39712673d846b6d57ce8629b07e31fcbb4f0b87269bf92eb8ca019e3af9"
RECORD_SHA256 = "e0e20e763772631a66878864084850c3b0817a9985747bedcd9e26c341231d2c"
V22_REGISTERED_ROUTES = 399
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV23Error(RuntimeError):
    """V23, V22, or the V64 successor binding failed closed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claim(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    raw = (root / RECORD.relative_to(PROJECT)).read_bytes()
    if (
        hashlib.sha256(raw).hexdigest() != RECORD_SHA256
        or raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in raw
        or not raw.endswith(b"\n")
    ):
        raise CurrentSuccessorRetirementV23Error("retirement V23 drifted")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementV23Error("retirement V23 is invalid") from error
    if record != build(root):
        raise CurrentSuccessorRetirementV23Error("retirement V23 contract drifted")
    claim = record["additional_claims"][0]
    if claim["historical_test_ids"] != list(HISTORICAL_TEST_IDS):
        raise CurrentSuccessorRetirementV23Error("retirement V23 routes drifted")
    return claim


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    predecessor_path = root / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V22.json"
    if _sha256(predecessor_path) != PREDECESSOR_SHA256:
        raise CurrentSuccessorRetirementV23Error("retirement V22 predecessor drifted")
    predecessor_claims = predecessor._current_claims(root)
    if len(predecessor.registered_test_ids(root)) != V22_REGISTERED_ROUTES:
        raise CurrentSuccessorRetirementV23Error("retirement V22 routes drifted")
    return (_claim(root),) + tuple(predecessor_claims)


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(node for claim in _current_claims(project) for node in claim["historical_test_ids"])


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementV23Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    print("CURRENT_SUCCESSOR_RETIREMENT_V23_OK", f"tests={len(registered_test_ids())}")
