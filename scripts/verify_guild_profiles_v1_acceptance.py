"""Verify Guild Profiles V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_guild_profiles_v1 as candidate  # noqa: E402

ID = "VE-GUILD-PROFILES-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-GUILD-PROFILES-V1-E6-001.sha256"
RECORD_SHA = "f2eab1e05b0350c61f4327ab4d069b114f9b9644a3be0bfac81606ab6987855e"
METADATA_SHA = "d4a27650157d8ad95a37701db2ac08a37a2750c79312181f6f444efe9f7c5fdd"
ANCHOR_SHA = "9e9c50c2b20c2b0634f8892298019c411656583ec81b5d158fb7dd9e24aae926"
ROOT = "818196ac6bd2048bbfe5218d0e576b392b07aa1005816b6f4b867f3ee9bbc09d"
MARKER = "GUILD_PROFILES_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Guild Profiles acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(candidate.MANIFEST) != json.loads(
            METADATA.read_text(encoding="utf-8")
        )["candidate_manifest_sha256"]
    ):
        raise RuntimeError("Guild Profiles acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Guild Profiles acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 674
        or metadata["results"]["subtests_passed"] != 96
        or claims.get("guild_profiles_default_off_contract_complete") is not True
        or claims.get("constitutional_floor_and_exclusivity_enforced") is not True
        or claims.get("orchestration_or_dispatch_authority_added") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("independent_human_review_performed") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Guild Profiles acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Guild Profiles accepted candidate reproduction drift")
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
