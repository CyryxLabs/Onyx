"""Verify the Microsoft Graph Calendar V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase8_microsoft_graph_calendar_v1 as candidate  # noqa: E402

ACCEPTANCE_ID = "VE-P8-MICROSOFT-GRAPH-CALENDAR-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = (
    PROJECT / "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-CALENDAR-V1-E6-001.sha256"
)
RECORD_SHA256 = "283934b419b82f346a240e604ad87ce0dba81bee2013ed14b8fd2ec9895e7314"
METADATA_SHA256 = "7d76e98826cd62ccbd4b1d52a8021b557125a085a5d0306abf4e10e74b99eedb"
ANCHOR_SHA256 = "93cdd20f42ef882c6b6c2357861cf923bb6d422d217fa5c95dc5b1848ff3fde8"
CANDIDATE_MANIFEST_SHA256 = (
    "e28bf370f81ac991d4a384d02783aa809d6afc59a5036f75852679679a5962e4"
)
CANDIDATE_ROOT = "4f0e1e3ae48a77f3c113a5ade1bb6e7e5f770bcbe9617ca8389edfce85029c3a"
MARKER = "P8_MICROSOFT_GRAPH_CALENDAR_V1_ACCEPTANCE_OK"


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
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 8}
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT
        or type(results) is not dict
        or results.get("passed") != 363
        or results.get("subtests_passed") != 80
        or type(claims) is not dict
        or claims.get("microsoft_graph_calendar_v1_accepted") is not True
        or claims.get("provider_mutation_authority_beyond_single_event_create")
        is not False
        or claims.get("live_mutation_e2e") is not False
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
