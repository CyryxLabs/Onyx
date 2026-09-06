"""Verify Phase 10 Audience/Strategy V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase10_audience_strategy_v1 as candidate  # noqa: E402

ID = "VE-P10-AUDIENCE-STRATEGY-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P10-AUDIENCE-STRATEGY-V1-E6-001.sha256"
RECORD_SHA = "e2f15217f96f2e59580ed070354092ff95ddbe73142595f163386c254b7aa1c4"
METADATA_SHA = "84d9bea5108e44ddb61a5d13fa46cb99d161e84ae23c120d8cbf2d5469187973"
ANCHOR_SHA = "21d0cf122372ec0b4001bdddb2c2cc2ee1004dc61e11ed93115a6ab33c52f1f7"
ROOT = "81199863a9d0acea479c639b1023a1abd119cbb2b76cc8fcdec1caabf9c22829"
MARKER = "P10_AUDIENCE_STRATEGY_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Phase 10 audience/strategy acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(candidate.MANIFEST)
        != json.loads(METADATA.read_text(encoding="utf-8"))[
            "candidate_manifest_sha256"
        ]
    ):
        raise RuntimeError("Phase 10 audience/strategy acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Phase 10 audience/strategy acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 833
        or metadata["results"]["subtests_passed"] != 96
        or claims.get("phase10_audience_strategy_default_off_contract_complete")
        is not True
        or claims.get("cited_research_cadence_and_sample_floor_enforced") is not True
        or claims.get("publish_or_schedule_authority_added") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("independent_human_review_performed") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Phase 10 audience/strategy acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Phase 10 audience/strategy accepted reproduction drift")
    return {
        "acceptance_id": ID,
        "decision": "accepted",
        "findings": metadata["findings"],
        "claims": claims,
        "candidate_artifact_root_sha256": ROOT,
        "marker": MARKER,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True))
    print(MARKER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
