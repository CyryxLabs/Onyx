"""Verify the Microsoft Graph OneDrive Read V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase8_microsoft_graph_drive_v1 as candidate  # noqa: E402

ACCEPTANCE_ID = "VE-P8-MICROSOFT-GRAPH-DRIVE-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-DRIVE-V1-E6-001.sha256"
RECORD_SHA256 = "690231d53f93ef281e457d8fcf631de153be84f37ae3d788a4fb2ebf65e7e2d5"
METADATA_SHA256 = "1f130a1adb1ccfc42c244efccf3611772a2095febd502b4dcbb4dbb8f4b2ca9a"
ANCHOR_SHA256 = "132b6ad4c884c4f257e9fc754e5bd08295287274c51150542cd5034ca854b1f0"
CANDIDATE_MANIFEST_SHA256 = (
    "3ad944de2b85de78e343f0cbee0556644218ec7d7039b93efe9daffe774758b5"
)
CANDIDATE_ROOT = "c79ee2960fdf3c74f4ec33cb693cd328a79bfa5547a8e74d2033603f9f0a6c21"
MARKER = "P8_MICROSOFT_GRAPH_DRIVE_V1_ACCEPTANCE_OK"


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
        or results.get("passed") != 421
        or results.get("subtests_passed") != 80
        or type(claims) is not dict
        or claims.get("microsoft_graph_drive_v1_accepted") is not True
        or claims.get("content_download") is not False
        or claims.get("drive_mutation_authority") is not False
        or claims.get("live_listing_e2e") is not False
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
