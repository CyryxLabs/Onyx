"""Verify the Phase 9 Opportunity Scoring V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase9_opportunity_scoring_v1 as candidate  # noqa: E402

ACCEPTANCE_ID = "VE-P9-OPPORTUNITY-SCORING-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P9-OPPORTUNITY-SCORING-V1-E6-001.sha256"
RECORD_SHA256 = "c29a3dad5802d694d3a3888d3b34872e1b317ee9404d8fea123cb36a5f5517d0"
METADATA_SHA256 = "7562ccdc2d52359a72928d7437a1e5b57bd21b911ab1d2e401fd993eea4ed11c"
ANCHOR_SHA256 = "d94846a68cc9e253c815acae257fa2eaca0919840198074a7fc66c3eab790bdc"
CANDIDATE_MANIFEST_SHA256 = (
    "9249c37f825d07f21860f82296c9eeee2dee9cf4e9948aa7d0e75230e6e68d85"
)
CANDIDATE_ROOT = "519d1e40710210dbc4527954964dc9551efc977911b9c9eec03f8b2c38b6c097"
MARKER = "P9_OPPORTUNITY_SCORING_V1_ACCEPTANCE_OK"


class AcceptanceError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError("acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _digest(RECORD) != RECORD_SHA256
        or _digest(METADATA) != METADATA_SHA256
        or _digest(ANCHOR) != ANCHOR_SHA256
        or _digest(candidate.MANIFEST) != CANDIDATE_MANIFEST_SHA256
    ):
        raise AcceptanceError("acceptance envelope hash drift")
    expected_anchor = (
        f"{RECORD_SHA256}  docs/onyx/acceptance/{ACCEPTANCE_ID}.md\n"
        f"{METADATA_SHA256}  "
        f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise AcceptanceError("acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims")
    results = metadata.get("results")
    if (
        metadata.get("acceptance_id") != ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 1}
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT
        or type(results) is not dict
        or results.get("passed") != 454
        or results.get("subtests_passed") != 80
        or type(claims) is not dict
        or claims.get("opportunity_scoring_v1_accepted") is not True
        or claims.get("transparent_weighted_scoring") is not True
        or claims.get("cost_dimension_inversion") is not True
        or claims.get("autonomous_action_on_score") is not False
        or claims.get("network_or_model_or_action") is not False
        or claims.get("world_monitor_connector") is not False
        or claims.get("live_wiring") is not False
        or claims.get("phase9_exit") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise AcceptanceError("acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != CANDIDATE_ROOT:
        raise AcceptanceError("accepted candidate reproduction drift")
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "decision": "accepted",
        "findings": metadata["findings"],
        "claims": claims,
        "candidate_artifact_root_sha256": CANDIDATE_ROOT,
        "record_sha256": RECORD_SHA256,
        "metadata_sha256": METADATA_SHA256,
        "anchor_sha256": ANCHOR_SHA256,
        "marker": MARKER,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True))
    print(MARKER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
