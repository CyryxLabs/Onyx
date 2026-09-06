"""Authenticate release-documentation retirement V30 over V29."""

import hashlib
import json
from pathlib import Path
from scripts import verify_current_successor_retirement_v29 as predecessor
from scripts.generate_current_successor_retirement_v30 import HISTORICAL_TEST_IDS, build

PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V30.json"
PREDECESSOR_SHA256 = "afcb177f41ca9b05961040855ee6da703c2a26b824ca5686ec269d46a114b0eb"
RECORD_SHA256 = "f247b0742cad7c4185374cded81eba0a4af8f92dceb192874b42ae7747846dfb"
V29_REGISTERED_ROUTES = 415
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV30Error(RuntimeError):
    pass


def _sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _claim(project=PROJECT):
    r = Path(project).resolve(strict=True)
    raw = (r / RECORD.relative_to(PROJECT)).read_bytes()
    if (
        hashlib.sha256(raw).hexdigest() != RECORD_SHA256
        or raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in raw
        or not raw.endswith(b"\n")
    ):
        raise CurrentSuccessorRetirementV30Error("retirement V30 drifted")
    record = json.loads(raw.decode())
    if record != build(r) or record["additional_claims"][0][
        "historical_test_ids"
    ] != list(HISTORICAL_TEST_IDS):
        raise CurrentSuccessorRetirementV30Error("retirement V30 contract drifted")
    return record["additional_claims"][0]


def _current_claims(project=PROJECT):
    r = Path(project).resolve(strict=True)
    if (
        _sha256(r / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V29.json")
        != PREDECESSOR_SHA256
        or len(predecessor.registered_test_ids(r)) != V29_REGISTERED_ROUTES
    ):
        raise CurrentSuccessorRetirementV30Error("retirement V29 predecessor drifted")
    return (_claim(r),) + tuple(predecessor._current_claims(r))


def registered_test_ids(project=PROJECT):
    return frozenset(
        n for c in _current_claims(project) for n in c["historical_test_ids"]
    )


def claim_for_test(nodeid, project=PROJECT):
    for c in _current_claims(project):
        if nodeid in c["historical_test_ids"]:
            return c
    raise CurrentSuccessorRetirementV30Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    print("CURRENT_SUCCESSOR_RETIREMENT_V30_OK", f"tests={len(registered_test_ids())}")
