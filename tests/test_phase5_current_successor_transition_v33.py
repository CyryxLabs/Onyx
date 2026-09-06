from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V32 = ROOT / "tests/fixtures/phase5_current_successor_transition_v32.json"
V33 = ROOT / "tests/fixtures/phase5_current_successor_transition_v33.json"


def test_v33_authenticates_v32_and_binds_governed_resident_exit() -> None:
    transition = json.loads(V33.read_text(encoding="utf-8"))
    predecessor = json.loads(V32.read_text(encoding="utf-8"))
    assert hashlib.sha256(V33.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V33_SHA256
    )
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v32.json",
        "sha256": retirement.CURRENT_TRANSITION_V32_SHA256,
    }
    changed = {
        current["path"]
        for current, prior in zip(
            transition["historical_bindings"],
            predecessor["historical_bindings"],
            strict=True,
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert changed == {"main.py", "ui.py"}
    assert transition["current_root_sha256"] == (
        "78aa19d7f3dffcdff3fb8b03a203fc51d0b76be082059574ba3205a5e08edab0"
    )
