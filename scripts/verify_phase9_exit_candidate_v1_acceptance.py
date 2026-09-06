"""Verify Phase 9 aggregate E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase9_exit_candidate_v1 as candidate  # noqa: E402

ID = "VE-P9-EXIT-CANDIDATE-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P9-EXIT-CANDIDATE-V1-E6-001.sha256"
RECORD_SHA = "d579582818877d2ba85824ae1b19b06b302ada9032e147e7de8f0efb5d304c31"
METADATA_SHA = "7fe79fac2eec5f438e0d90d88e2a8a026aa715086e2fdbc75efda772d3bd174a"
ANCHOR_SHA = "2024fc3768fa0e7b22e5ab78bdd05cf43822393513bde7d0998b164204fa88e2"
MANIFEST_SHA = "c0e8105eceb011b5a0629df8d9ea5beb2588787833d6053cebee6f66bf66ee2d"
ROOT = "90d1947576ebaf430cd179b1624c74974789a1426552afb42eab53b180f81fc6"
MARKER = "P9_EXIT_CANDIDATE_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Phase 9 acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(candidate.MANIFEST) != MANIFEST_SHA
    ):
        raise RuntimeError("Phase 9 acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Phase 9 acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["accepted_component_roots"] != 12
        or metadata["candidate_manifest_sha256"] != MANIFEST_SHA
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 472
        or metadata["results"]["subtests_passed"] != 80
        or claims.get("phase9_intelligence_layer_default_off_implementation_complete")
        is not True
        or claims.get("phase10_may_begin") is not True
        or claims.get("world_monitor_bound") is not False
        or claims.get("live_execution_bound") is not False
        or claims.get("autonomous_trading_enabled") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Phase 9 acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Phase 9 accepted candidate reproduction drift")
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
