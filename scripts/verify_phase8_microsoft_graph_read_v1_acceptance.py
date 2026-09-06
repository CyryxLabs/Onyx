"""Verify the Microsoft Graph Read V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase8_microsoft_graph_read_v1 as candidate  # noqa: E402

ACCEPTANCE_ID = "VE-P8-MICROSOFT-GRAPH-READ-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-READ-V1-E6-001.sha256"
RECORD_SHA256 = "c34565135bbd7366cc51febee82ebd41bb3ed5932d928e6df0bea82920cb2325"
METADATA_SHA256 = "095f5f5af0d26cf45970bae84f97181cb4f8a672e33cbaab17e37e4d29e41769"
ANCHOR_SHA256 = "87289e933edb2d369252e6f9816785682e0f2eb4e8d8382ffc5861f2b0f920e8"
CANDIDATE_MANIFEST_SHA256 = (
    "91a97a56729e396b84da60d30db5d33d71c8e315343d544792e7183d436dc261"
)
CANDIDATE_ROOT = "abb152e611e1b58adc55b88207497d64188ad9485d2b6a32ada5f8c364528291"
MARKER = "P8_MICROSOFT_GRAPH_READ_V1_ACCEPTANCE_OK"


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
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT
        or type(results) is not dict
        or results.get("passed") != 264
        or results.get("subtests_passed") != 80
        or type(claims) is not dict
        or claims.get("microsoft_graph_read_v1_accepted") is not True
        or claims.get("provider_mutation_authority") is not False
        or claims.get("oauth_onboarding") is not False
        or claims.get("live_http_transport") is not False
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
