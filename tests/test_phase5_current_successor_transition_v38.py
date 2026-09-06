from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V37 = ROOT / "tests/fixtures/phase5_current_successor_transition_v37.json"
V38 = ROOT / "tests/fixtures/phase5_current_successor_transition_v38.json"


def test_v38_authenticates_v37_and_frozen_runtime_authorities() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_current_successor_transition()
    transition = json.loads(V38.read_text(encoding="utf-8"))
    assert hashlib.sha256(V38.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V38_SHA256
    assert hashlib.sha256(V37.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V37_SHA256
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v38"
    assert transition["current_root_sha256"] == "d26fb8cce02c6ed273bd1bbf27ca52cf8b7d95686a52b24fce3416d00a7d3791"
    current = {entry["path"]: entry["current_sha256"] for entry in transition["historical_bindings"]}
    successors = {entry["path"]: entry["current_sha256"] for entry in transition["named_successors"]}
    assert current["ui.py"] == hashlib.sha256((ROOT / "ui.py").read_bytes()).hexdigest()
    assert successors["scripts/package_hygiene.py"] == (
        "0804ca1bb995cf5e11b2a45f3465aa3191bb71c488135d1d4cd3886c150c9522"
    )
