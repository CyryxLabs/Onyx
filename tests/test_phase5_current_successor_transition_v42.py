from __future__ import annotations

import hashlib
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V42 = ROOT / "tests/fixtures/phase5_current_successor_transition_v42.json"


def test_v42_is_the_immutable_predecessor_of_current_v43() -> None:
    retirement.load_current_successor_transition.cache_clear()
    transition = retirement.load_current_successor_transition()
    assert hashlib.sha256(V42.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V42_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v43"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v42.json",
        "sha256": retirement.CURRENT_TRANSITION_V42_SHA256,
    }


def test_v43_authenticates_current_runtime_authority() -> None:
    retirement.load_current_successor_transition.cache_clear()
    transition = retirement.load_current_successor_transition()

    historical = {
        entry["path"]: entry["current_sha256"]
        for entry in transition["historical_bindings"]
    }
    for relative in (
        "packaging/windows/onyx.iss",
        "scripts/build_release.py",
        "ui.py",
    ):
        assert historical[relative] == hashlib.sha256(
            (ROOT / relative).read_bytes()
        ).hexdigest()

    successors = {
        entry["path"]: entry["current_sha256"]
        for entry in transition["named_successors"]
    }
    for relative in (
        "scripts/package_hygiene.py",
        "tests/test_package_hygiene_v1.py",
    ):
        assert successors[relative] == hashlib.sha256(
            (ROOT / relative).read_bytes()
        ).hexdigest()
