from __future__ import annotations

import json

from core.paths import resource_root


RETIREMENT_LEDGER = (
    "docs/onyx/checkpoints/HUD_REJECTED_CANDIDATES_RETIREMENT_V1.json"
)


def test_rejected_candidate_002_snapshot_is_retired_and_absent() -> None:
    root = resource_root()
    ledger = json.loads((root / RETIREMENT_LEDGER).read_text(encoding="utf-8"))
    assert ledger["schema"] == "OnyxHudRejectedCandidateRetirement.v1"
    candidate = ledger["retired"][1]
    assert candidate == {
        "candidate": "ONYX-HUD-ORB-V4-LIVE-INTEGRATION-002",
        "snapshot_root": (
            "docs/onyx/checkpoints/hud-orb-v4-live/candidate-002-snapshot"
        ),
        "state": "absent",
        "files": 13,
        "bytes": 2095770,
        "manifest_sha256": (
            "8daf7a43fd08ee6d7548992f4a8ef2da48c4271142dabae4e8fb0ee76c50d495"
        ),
        "checkpoint_sha256": (
            "42148552f863791979812f19b1019921ce9b785153f511f80803e40d127126d5"
        ),
        "screenshot_sha256": (
            "03b99d56a542d48680c5baa42ffd818e20c6e87043dc82333d098be662ee57a1"
        ),
    }
    assert not (root / candidate["snapshot_root"]).exists()


def test_rejected_v4_flag_has_no_live_activation_path() -> None:
    source = (resource_root() / "ui.py").read_text(encoding="utf-8")
    assert "ONYX_HUD_V4_LIVE" not in source
    assert 'os.environ.get("ONYX_HUD_V5_LIVE", "0").strip() == "1"' in source
