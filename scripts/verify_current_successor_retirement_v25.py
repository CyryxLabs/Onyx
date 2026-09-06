"""Authenticate Release V65 and HUD V34/V35 retirement over V24."""

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v24 as predecessor
from scripts.generate_current_successor_retirement_v25 import HUD_TEST_IDS, RELEASE_TEST_IDS, build

PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V25.json"
PREDECESSOR_SHA256 = "4ad07cca8347a05e37eb87682f436133069270e6603a61763a8895de3dd72a01"
RECORD_SHA256 = "0f55926ae65077e77d1fcdace881e82b744ba33ddd48c7b56a14dffb1198a7b5"
V24_REGISTERED_ROUTES = 401
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV25Error(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    raw = (root / RECORD.relative_to(PROJECT)).read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256 or raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementV25Error("retirement V25 drifted")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementV25Error("retirement V25 is invalid") from error
    if record != build(root):
        raise CurrentSuccessorRetirementV25Error("retirement V25 contract drifted")
    claims = tuple(record["additional_claims"])
    if claims[0]["historical_test_ids"] != list(RELEASE_TEST_IDS) or claims[1]["historical_test_ids"] != list(HUD_TEST_IDS):
        raise CurrentSuccessorRetirementV25Error("retirement V25 routes drifted")
    return claims


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    prior = root / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V24.json"
    if _sha256(prior) != PREDECESSOR_SHA256 or len(predecessor.registered_test_ids(root)) != V24_REGISTERED_ROUTES:
        raise CurrentSuccessorRetirementV25Error("retirement V24 predecessor drifted")
    return _claims(root) + tuple(predecessor._current_claims(root))


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(node for claim in _current_claims(project) for node in claim["historical_test_ids"])


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementV25Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    print("CURRENT_SUCCESSOR_RETIREMENT_V25_OK", f"tests={len(registered_test_ids())}")
