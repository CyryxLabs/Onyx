"""Authenticate packaged-smoke retirement V27 over immutable V26."""

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v26 as predecessor
from scripts.generate_current_successor_retirement_v27 import HISTORICAL_TEST_IDS, build

PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V27.json"
PREDECESSOR_SHA256 = "61d6fdc61ff1d0828bbe883746a31091543552149aaa0710c7ef089f3ca6089f"
RECORD_SHA256 = "073c4e6db0351736b1787db33b4b21e14d3325b8d1e8cf60938e6cc1cd320967"
V26_REGISTERED_ROUTES = 412
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV27Error(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claim(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    raw = (root / RECORD.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256 or raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementV27Error("retirement V27 drifted")
    record = json.loads(raw.decode("utf-8"))
    if record != build(root) or record["additional_claims"][0]["historical_test_ids"] != list(HISTORICAL_TEST_IDS):
        raise CurrentSuccessorRetirementV27Error("retirement V27 contract drifted")
    return record["additional_claims"][0]


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    if _sha256(root / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V26.json") != PREDECESSOR_SHA256 or len(predecessor.registered_test_ids(root)) != V26_REGISTERED_ROUTES:
        raise CurrentSuccessorRetirementV27Error("retirement V26 predecessor drifted")
    return (_claim(root),) + tuple(predecessor._current_claims(root))


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(node for claim in _current_claims(project) for node in claim["historical_test_ids"])


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementV27Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    print("CURRENT_SUCCESSOR_RETIREMENT_V27_OK", f"tests={len(registered_test_ids())}")
