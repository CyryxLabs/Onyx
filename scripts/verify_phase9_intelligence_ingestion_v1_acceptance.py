"""Verify the Phase 9 Intelligence Ingestion V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase9_intelligence_ingestion_v1 as candidate  # noqa: E402

ACCEPTANCE_ID = "VE-P9-INTELLIGENCE-INGESTION-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P9-INTELLIGENCE-INGESTION-V1-E6-001.sha256"
RECORD_SHA256 = "8496c3cbc39bbca67c25241355ad494a622b64076733436ebe5447eb1e209465"
METADATA_SHA256 = "6105adc37682a47296d87181dc5f7e70a3aa82e039b1f4a335830139acd1bbf1"
ANCHOR_SHA256 = "dcf8b3351ee909f44efe7b5e442f8c26acc361bf580adceb48ff398ba61e0a84"
CANDIDATE_MANIFEST_SHA256 = (
    "2d7650b305b203ce9c74e576652d8221b4dac2498d37c7450ab365325e04a78f"
)
CANDIDATE_ROOT = "977132cea3f9316bb1b7a62ecc4c8368da6f2a12a7e65a62b9d5511a833cbb6a"
MARKER = "P9_INTELLIGENCE_INGESTION_V1_ACCEPTANCE_OK"


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
        or results.get("passed") != 439
        or results.get("subtests_passed") != 80
        or type(claims) is not dict
        or claims.get("intelligence_ingestion_v1_accepted") is not True
        or claims.get("recycled_story_dedup") is not True
        or claims.get("consequential_claim_corroboration") is not True
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
