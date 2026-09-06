"""Verify the Microsoft Graph Live Read E2E V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import (  # noqa: E402
    verify_phase8_microsoft_graph_live_read_e2e_v1 as candidate,
)

ACCEPTANCE_ID = "VE-P8-MICROSOFT-GRAPH-LIVE-READ-E2E-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = (
    PROJECT
    / "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-LIVE-READ-E2E-V1-E6-001.sha256"
)
RECORD_SHA256 = "688b8dfea9a687474497a0aa82bce67fc443dee8f921d98ee5b455b2596739c5"
METADATA_SHA256 = "47ee0cc94d177f0cc52d02df6b5f975bc24894ea5d25deae7134c32979dc571e"
ANCHOR_SHA256 = "14fb863e7e8a935b9c9558b6bfedb0e78c0fcf0a075641b9b74c4bbf36d0ffde"
CANDIDATE_MANIFEST_SHA256 = (
    "63e2ff3a059aeb1c856ca73ad80ac523aac99aa33162fc200ce0fee47dcdc104"
)
CANDIDATE_ROOT = "30bdd9e3bf1bde4effa1acb7147fcd714d763c6fcc017e6b23fe189fcfabef6b"
MARKER = "P8_MICROSOFT_GRAPH_LIVE_READ_E2E_V1_ACCEPTANCE_OK"


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
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 9}
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT
        or type(results) is not dict
        or results.get("passed") != 337
        or results.get("subtests_passed") != 80
        or type(claims) is not dict
        or claims.get("microsoft_graph_live_read_e2e_v1_accepted") is not True
        or claims.get("provider_mutation_authority") is not False
        or claims.get("real_app_registration") is not False
        or claims.get("live_identity_e2e") is not False
        or claims.get("live_graph_e2e") is not False
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
