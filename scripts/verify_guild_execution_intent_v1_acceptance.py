"""Verify Guild Execution-Intent V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_guild_execution_intent_v1 as candidate  # noqa: E402

ID = "VE-GUILD-EXECUTION-INTENT-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = (
    PROJECT / "docs/onyx/VE-ACCEPTANCE-GUILD-EXECUTION-INTENT-V1-E6-001.sha256"
)
RECORD_SHA = "5bce58279b58bfb9e8fda57ec53278a9474291ee33bb4ca44d2e5af84119306e"
METADATA_SHA = "8413aef59403a9c50c0575045f81dda22cb38f985ede37d08b7a08485275ad03"
ANCHOR_SHA = "3e93a29112524cf04da54ea3ab6a89733130a86e3463b985a6b354edb3140494"
ROOT = "68a4fc775dbdccb0741c0bf69aa5ff786966f4f828f2220ac35ec21efde64e83"
MARKER = "GUILD_EXECUTION_INTENT_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Guild Execution-Intent acceptance artifact unavailable")
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
        raise RuntimeError("Guild Execution-Intent acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Guild Execution-Intent acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["autopilot_module_sha256"] != candidate.candidate.AUTOPILOT_MODULE_SHA256
        or metadata["results"]["passed"] != 796
        or metadata["results"]["subtests_passed"] != 96
        or claims.get("guild_execution_intent_default_off_contract_complete") is not True
        or claims.get("autopilot_pin_and_forward_only_binding_enforced") is not True
        or claims.get("dispatch_authority_added") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("independent_human_review_performed") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Guild Execution-Intent acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Guild Execution-Intent accepted reproduction drift")
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
