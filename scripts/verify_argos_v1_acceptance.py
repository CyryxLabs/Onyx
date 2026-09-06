"""Verify Argos V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_argos_v1 as candidate  # noqa: E402

ID = "VE-ARGOS-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-ARGOS-V1-E6-001.sha256"
RECORD_SHA = "1db01425cebafe46ef64a31df0c2639b28762b5921913d1f04cd6a6c6ea549e3"
METADATA_SHA = "134f7e2459aacb28946089d342fb64f40489fb4b9f3ff233fbfd6176b0b831d7"
ANCHOR_SHA = "b391cbd2c63552861bf0f190d94a3880d799cd6efaf734441f9eddeef9d010fc"
ROOT = "11f51eb86be4e9e953bf0df0e7740683a291ec2f83c641b7054a0fe201738d62"
MARKER = "ARGOS_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Argos acceptance artifact unavailable")
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
        raise RuntimeError("Argos acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Argos acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 868
        or metadata["results"]["subtests_passed"] != 96
        or claims.get("argos_registry_default_off_contract_complete") is not True
        or claims.get("citation_rights_taxonomy_and_ranking_enforced") is not True
        or claims.get("proprietary_original_work") is not True
        or claims.get("third_party_world_monitor_code_used") is not False
        or claims.get("action_authority_added") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("live_world_intelligence_proven") is not False
        or claims.get("independent_human_review_performed") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Argos acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Argos accepted candidate reproduction drift")
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
