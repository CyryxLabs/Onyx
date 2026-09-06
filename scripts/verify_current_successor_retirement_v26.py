"""Authenticate bounded successor execution V26 over immutable V25."""

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v25 as predecessor
from scripts.generate_current_successor_retirement_v26 import HISTORICAL_TEST_IDS, build

PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V26.json"
PREDECESSOR_SHA256 = "0f55926ae65077e77d1fcdace881e82b744ba33ddd48c7b56a14dffb1198a7b5"
RECORD_SHA256 = "61d6fdc61ff1d0828bbe883746a31091543552149aaa0710c7ef089f3ca6089f"
V25_REGISTERED_ROUTES = 411
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV26Error(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claim(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    raw = (root / RECORD.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256 or raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementV26Error("retirement V26 drifted")
    record = json.loads(raw.decode("utf-8"))
    if record != build(root) or record["additional_claims"][0]["historical_test_ids"] != list(HISTORICAL_TEST_IDS):
        raise CurrentSuccessorRetirementV26Error("retirement V26 contract drifted")
    return record["additional_claims"][0]


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    prior = root / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V25.json"
    if _sha256(prior) != PREDECESSOR_SHA256 or len(predecessor.registered_test_ids(root)) != V25_REGISTERED_ROUTES:
        raise CurrentSuccessorRetirementV26Error("retirement V25 predecessor drifted")
    return (_claim(root),) + tuple(predecessor._current_claims(root))


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(node for claim in _current_claims(project) for node in claim["historical_test_ids"])


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementV26Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    print("CURRENT_SUCCESSOR_RETIREMENT_V26_OK", f"tests={len(registered_test_ids())}")
