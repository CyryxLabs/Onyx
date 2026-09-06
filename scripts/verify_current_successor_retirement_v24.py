"""Authenticate V64 to V65 retirement over immutable V23."""

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v23 as predecessor
from scripts.generate_current_successor_retirement_v24 import HISTORICAL_TEST_IDS, build

PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V24.json"
PREDECESSOR_SHA256 = "e0e20e763772631a66878864084850c3b0817a9985747bedcd9e26c341231d2c"
RECORD_SHA256 = "4ad07cca8347a05e37eb87682f436133069270e6603a61763a8895de3dd72a01"
V23_REGISTERED_ROUTES = 400
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV24Error(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claim(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    raw = (root / RECORD.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256 or raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementV24Error("retirement V24 drifted")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementV24Error("retirement V24 is invalid") from error
    if record != build(root) or record["additional_claims"][0]["historical_test_ids"] != list(HISTORICAL_TEST_IDS):
        raise CurrentSuccessorRetirementV24Error("retirement V24 contract drifted")
    return record["additional_claims"][0]


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    prior = root / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V23.json"
    if _sha256(prior) != PREDECESSOR_SHA256 or len(predecessor.registered_test_ids(root)) != V23_REGISTERED_ROUTES:
        raise CurrentSuccessorRetirementV24Error("retirement V23 predecessor drifted")
    return (_claim(root),) + tuple(predecessor._current_claims(root))


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(node for claim in _current_claims(project) for node in claim["historical_test_ids"])


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementV24Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    print("CURRENT_SUCCESSOR_RETIREMENT_V24_OK", f"tests={len(registered_test_ids())}")
