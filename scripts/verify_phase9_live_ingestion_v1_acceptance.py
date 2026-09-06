"""Verify the Phase 9 Live Ingestion V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase9_live_ingestion_v1 as candidate  # noqa: E402

ACCEPTANCE_ID = "VE-P9-LIVE-INGESTION-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P9-LIVE-INGESTION-V1-E6-001.sha256"
RECORD_SHA256 = "6c87468da08ae7520593b9d0cae08e89681d3ccebe72e85351895475eb2d9281"
METADATA_SHA256 = "e104dcf14e12169491263382c7bcb01a3421253cd4b25a70e0a22e2b44c2c4ad"
ANCHOR_SHA256 = "1dc70fc02987382fa8524be953e42aad04f1b73f1b437ea4d1a5026592d59163"
CANDIDATE_MANIFEST_SHA256 = (
    "0def1781c9e98c50d6728bfdec54b3866fdd5bb392a89af9ef068ff20bb7ae29"
)
CANDIDATE_ROOT = "fc1611e4ac1c896a637bab525df0d066e2eecf7f860f8f0766f4312c6f920d6a"
MARKER = "P9_LIVE_INGESTION_V1_ACCEPTANCE_OK"


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
        or results.get("passed") != 472
        or results.get("subtests_passed") != 80
        or type(claims) is not dict
        or claims.get("live_ingestion_connector_v1_accepted") is not True
        or claims.get("redirects_disabled") is not True
        or claims.get("source_health_and_category_attributed_from_registry") is not True
        or claims.get("real_live_fetch_exercised") is not False
        or claims.get("mutation_or_action_or_model_or_persistence") is not False
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
