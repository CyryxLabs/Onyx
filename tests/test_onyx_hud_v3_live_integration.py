from __future__ import annotations

import json

from core.paths import resource_root


RETIREMENT_LEDGER = (
    "docs/onyx/checkpoints/HUD_REJECTED_CANDIDATES_RETIREMENT_V1.json"
)


def test_rejected_candidate_001_snapshot_is_retired_and_absent() -> None:
    root = resource_root()
    ledger = json.loads((root / RETIREMENT_LEDGER).read_text(encoding="utf-8"))
    assert ledger["schema"] == "OnyxHudRejectedCandidateRetirement.v1"
    candidate = ledger["retired"][0]
    assert candidate == {
        "candidate": "ONYX-HUD-ORB-V3-LIVE-INTEGRATION-001",
        "snapshot_root": (
            "docs/onyx/checkpoints/hud-orb-v3-live/candidate-001-snapshot"
        ),
        "state": "absent",
        "files": 12,
        "bytes": 2061782,
        "manifest_sha256": (
            "ab6d43bb91eb35613f37ed968b44f6022cd56177ed81eded61dd5a4b2a065411"
        ),
        "checkpoint_sha256": (
            "107c4079b6579c65d74edade651ca827526ef68cd698456631f401e7c7f0ae02"
        ),
        "screenshot_sha256": (
            "beb76bae5dea82e6daf8ac994c445c5c7b1fad003ec3b24ceb6e0e1f6400301b"
        ),
    }
    assert not (root / candidate["snapshot_root"]).exists()


def test_rejected_v3_flag_has_no_live_activation_path() -> None:
    source = (resource_root() / "ui.py").read_text(encoding="utf-8")
    assert "ONYX_HUD_V3_LIVE" not in source
    assert "ONYX_HUD_V4_LIVE" not in source
    assert 'os.environ.get("ONYX_HUD_V5_LIVE", "0").strip() == "1"' in source
