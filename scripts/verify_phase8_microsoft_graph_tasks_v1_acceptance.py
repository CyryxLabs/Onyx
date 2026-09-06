"""Verify the Microsoft Graph Tasks V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase8_microsoft_graph_tasks_v1 as candidate  # noqa: E402

ACCEPTANCE_ID = "VE-P8-MICROSOFT-GRAPH-TASKS-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-TASKS-V1-E6-001.sha256"
RECORD_SHA256 = "8940ab667fd20ed168335d45a3a5c65df11c2644d39cf5832a9a0c686dc93ee7"
METADATA_SHA256 = "51061cd36e1688c97d80c5cad9f3ec796bb7a623ca99f29e159b4648522af7a5"
ANCHOR_SHA256 = "c0a9e00072300963e32103fe116f185256869db6069d3d2b7b910d0fb5892d9e"
CANDIDATE_MANIFEST_SHA256 = (
    "44337ca6fdd348cd8ff7010d8ffeeb6fd6bc3167b4b80f0e3a08888b1bc859a8"
)
CANDIDATE_ROOT = "984f32cf236bac4b9ef1c4ad0a63bcf9a1384c19a0fdc8feae5720d0334f6508"
MARKER = "P8_MICROSOFT_GRAPH_TASKS_V1_ACCEPTANCE_OK"


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
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 3}
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT
        or type(results) is not dict
        or results.get("passed") != 403
        or results.get("subtests_passed") != 80
        or type(claims) is not dict
        or claims.get("microsoft_graph_tasks_v1_accepted") is not True
        or claims.get("task_update_delete_complete_authority") is not False
        or claims.get("live_task_create_e2e") is not False
        or claims.get("live_wiring") is not False
        or claims.get("phase8_exit") is not False
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
