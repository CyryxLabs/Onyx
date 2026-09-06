"""Verify Phase 8 aggregate E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase8_exit_candidate_v1 as candidate  # noqa: E402

ID = "VE-P8-EXIT-CANDIDATE-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P8-EXIT-CANDIDATE-V1-E6-001.sha256"
RECORD_SHA = "14d680c58ecc5521e2ba902dfc340dc7ad0cf4fed264c5d3bf71a667a208e2d3"
METADATA_SHA = "8e1f6fd7b448a6d7a4777d073ec4038a8405a32e0f81b2da6ee871c7a8357204"
ANCHOR_SHA = "13ea98542ab41bedc59da2261cbf456b1b5bb4c6f8512559c2047b1b7035968b"
MANIFEST_SHA = "8b23754d1d0cbc6f5ec613a5b454ed66cb933cd007fb0c4524f8d92cd8bdfd46"
ROOT = "114cba2de27b680848ed5bfe6ddba7e0033c6448d6f85d198689aa8cffc1485a"
MARKER = "P8_EXIT_CANDIDATE_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Phase 8 acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(candidate.MANIFEST) != MANIFEST_SHA
    ):
        raise RuntimeError("Phase 8 acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Phase 8 acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["accepted_component_roots"] != 28
        or metadata["candidate_manifest_sha256"] != MANIFEST_SHA
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 421
        or metadata["results"]["subtests_passed"] != 80
        or claims.get("phase8_connector_layer_default_off_implementation_complete")
        is not True
        or claims.get("phase9_may_begin") is not True
        or claims.get("live_wiring") is not False
        or claims.get("live_e2e_bound_in_aggregate") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Phase 8 acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Phase 8 accepted candidate reproduction drift")
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
