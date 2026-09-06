"""Verify the Phase 10 Provider Connector CURRENT successor acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase10_provider_connector_current_v1 as candidate  # noqa: E402

ID = "VE-P10-PROVIDER-CONNECTOR-CURRENT-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = (
    PROJECT
    / "docs/onyx/VE-ACCEPTANCE-P10-PROVIDER-CONNECTOR-CURRENT-V1-E6-001.sha256"
)
RECORD_SHA = "cdafa577505f9bfa530fbc4441b05882844da9c18c10deaa9195135eb1463462"
METADATA_SHA = "7b0ef192dee1f615928a9fbed2567451fe2b31fc8f6059b6d0e0e9385d20d362"
ANCHOR_SHA = "db350b8fa5c5bbb2250d24ac1c466a8f2c203c85ba66d1af97bd4143b2241448"
ROOT = "90139dd8b2856a6d778356b64a747d851e5320afe2241401b7150cf9499d9054"
MARKER = "P10_PROVIDER_CONNECTOR_CURRENT_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("provider-connector successor artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
    ):
        raise RuntimeError("provider-connector successor acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("provider-connector successor anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted_current_successor"
        or metadata["historical_acceptance_id"] != "VE-P10-PROVIDER-CONNECTOR-V1-E6-001"
        or metadata["candidate_artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 32
        or claims.get("current_bytes_bound") is not True
        or claims.get("historical_record_rewritten") is not False
        or claims.get("capability_or_authority_added") is not False
        or claims.get("independent_human_review_performed") is not False
    ):
        raise RuntimeError("provider-connector successor semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["candidate_artifact_root_sha256"] != ROOT:
        raise RuntimeError("provider-connector successor reproduction drift")
    return {
        "acceptance_id": ID,
        "decision": "accepted_current_successor",
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
