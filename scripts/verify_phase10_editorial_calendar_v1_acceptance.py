"""Verify Phase 10 Editorial Calendar V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase10_editorial_calendar_v1 as candidate  # noqa: E402

ID = "VE-P10-EDITORIAL-CALENDAR-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P10-EDITORIAL-CALENDAR-V1-E6-001.sha256"
RECORD_SHA = "ad90c8bc971e1048082c1e6d94f63b35e6ac66568d91253c0ff7b524b6e93921"
METADATA_SHA = "12f3edc21c5f36f2130d1e9379f13d17ff7413ab73cd815561dfa6993f8ac3a4"
ANCHOR_SHA = "8def6e446ea34f90af2885980549106525581230685f1d67e27045b6548e4429"
MANIFEST_SHA = "4b2fcce6cab138dbc788e7f5ba16214adf894b6cf37566229ffc91b3f8de683a"
ROOT = "415bbc4de20811c3d7caac47dacb8a01cf50a4ed1660f9670ee5278136411939"
MARKER = "P10_EDITORIAL_CALENDAR_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Phase 10 editorial acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(candidate.MANIFEST) != MANIFEST_SHA
    ):
        raise RuntimeError("Phase 10 editorial acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Phase 10 editorial acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["candidate_manifest_sha256"] != MANIFEST_SHA
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 538
        or metadata["results"]["subtests_passed"] != 80
        or claims.get("phase10_editorial_calendar_default_off_contract_complete")
        is not True
        or claims.get("first_publish_approval_gate_enforced") is not True
        or claims.get("publish_authority_added") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Phase 10 editorial acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Phase 10 editorial accepted candidate reproduction drift")
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
