"""Verify Phase 7 aggregate E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase7_exit_candidate_v1 as candidate  # noqa: E402

ID = "VE-P7-EXIT-CANDIDATE-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P7-EXIT-CANDIDATE-V1-E6-001.sha256"
RECORD_SHA = "4e21bc72888ae66a2d07a21e94d08175aac163ade72802d417a4438e7728c8a5"
METADATA_SHA = "c957674c6e3e543d647ed397eff777bb8b99d7af7e03a6909893af947bab91b9"
ANCHOR_SHA = "214e181fac5fde6127b36bda98ec8755765143acfaac1f54921deb04db193e37"
MANIFEST_SHA = "19cb98bb51a14617538aafb9c1f17cb52818e78991b51269ee3b0f126db505e4"
ROOT = "0512b1af1ea38392ca62b37933404119c80b173a3d6e8e059d0e0f5418a7bfcb"
MARKER = "P7_EXIT_CANDIDATE_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(candidate.MANIFEST) != MANIFEST_SHA
    ):
        raise RuntimeError("Phase 7 acceptance hash drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["accepted_component_roots"] != 24
        or metadata["results"]["passed"] != 240
        or metadata["results"]["subtests_passed"] != 80
        or metadata["claims"]["phase7_default_off_implementation_complete"] is not True
        or metadata["claims"]["full_onyx_prd_complete"] is not False
    ):
        raise RuntimeError("Phase 7 acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Phase 7 accepted candidate reproduction drift")
    return {
        "acceptance_id": ID,
        "decision": "accepted",
        "findings": metadata["findings"],
        "claims": metadata["claims"],
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
