"""Authenticate V48 freezer retirement V29 over immutable V28."""

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v28 as predecessor
from scripts.generate_current_successor_retirement_v29 import HISTORICAL_TEST_IDS, build

PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V29.json"
PREDECESSOR_SHA256 = "040af71d581b060d3421ef83dcd8d3ceb44b2e3815dd4c27b15dda1b0690b1e5"
RECORD_SHA256 = "afcb177f41ca9b05961040855ee6da703c2a26b824ca5686ec269d46a114b0eb"
V28_REGISTERED_ROUTES = 414
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV29Error(RuntimeError):
    pass


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
        raise CurrentSuccessorRetirementV29Error("retirement V29 drifted")
    record = json.loads(raw.decode("utf-8"))
    if record != build(root) or record["additional_claims"][0][
        "historical_test_ids"
    ] != list(HISTORICAL_TEST_IDS):
        raise CurrentSuccessorRetirementV29Error("retirement V29 contract drifted")
    return record["additional_claims"][0]


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    if (
        _sha256(root / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V28.json")
        != PREDECESSOR_SHA256
        or len(predecessor.registered_test_ids(root)) != V28_REGISTERED_ROUTES
    ):
        raise CurrentSuccessorRetirementV29Error("retirement V28 predecessor drifted")
    return (_claim(root),) + tuple(predecessor._current_claims(root))


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
    raise CurrentSuccessorRetirementV29Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    print("CURRENT_SUCCESSOR_RETIREMENT_V29_OK", f"tests={len(registered_test_ids())}")
