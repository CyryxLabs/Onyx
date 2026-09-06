"""Verify Guild Handoff V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_guild_handoff_v1 as candidate  # noqa: E402

ID = "VE-GUILD-HANDOFF-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-GUILD-HANDOFF-V1-E6-001.sha256"
RECORD_SHA = "3aaee02e674044acdc7d4433c56c17510dd8da9b90eb3efbaecbba37e4f8020b"
METADATA_SHA = "4fd4ef3871bea2ecf60904b10e3bacc686ffac8f4c19fe8322bc3088f878a015"
ANCHOR_SHA = "5e879789f6710fe7aecc0b2cf1a5439aa52517c3a1ce334f1bf9964a67b2302b"
ROOT = "104efcc6762416ea6ffd2055a5368df49f605a9e507cc746d8cf0bbf37be6b79"
MARKER = "GUILD_HANDOFF_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Guild Handoff acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(candidate.MANIFEST)
        != json.loads(METADATA.read_text(encoding="utf-8"))[
            "candidate_manifest_sha256"
        ]
    ):
        raise RuntimeError("Guild Handoff acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Guild Handoff acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 717
        or metadata["results"]["subtests_passed"] != 96
        or claims.get("guild_handoff_default_off_contract_complete") is not True
        or claims.get("lifecycle_qa_and_handoff_bounds_enforced") is not True
        or claims.get("execution_or_dispatch_authority_added") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("independent_human_review_performed") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Guild Handoff acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Guild Handoff accepted candidate reproduction drift")
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
