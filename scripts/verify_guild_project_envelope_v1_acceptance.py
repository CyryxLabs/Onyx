"""Verify Guild Project Envelope V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_guild_project_envelope_v1 as candidate  # noqa: E402

ID = "VE-GUILD-PROJECT-ENVELOPE-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = (
    PROJECT / "docs/onyx/VE-ACCEPTANCE-GUILD-PROJECT-ENVELOPE-V1-E6-001.sha256"
)
RECORD_SHA = "4f8ccdf51fa080abe460b0544f495c1c8119670a1e93a41a7c80cd92749fd738"
METADATA_SHA = "8c9c9bc652e31ba2146246f0fc6f6029a7e3caed40bf3e300bfae3f63559303b"
ANCHOR_SHA = "24bd483e743364ab0dc2545b673a12f63264e6aef2aafb6ba27fe8d7f5d0c95b"
ROOT = "438fe075ca88e31e588b4e04dc087ab9e58fce5c3fabdfa658a1dc199ad60874"
MARKER = "GUILD_PROJECT_ENVELOPE_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Guild Project Envelope acceptance artifact unavailable")
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
        raise RuntimeError("Guild Project Envelope acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Guild Project Envelope acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 910
        or metadata["results"]["subtests_passed"] != 96
        or claims.get("guild_project_envelope_default_off_contract_complete")
        is not True
        or claims.get("hard_budgets_kpis_and_decommission_policy_enforced")
        is not True
        or claims.get("unlimited_budget_representable") is not False
        or claims.get("softer_decommission_outcome_representable") is not False
        or claims.get("activation_or_spend_authority_added") is not False
        or claims.get("decommission_execution_added") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("independent_human_review_performed") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Guild Project Envelope acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Guild Project Envelope accepted reproduction drift")
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
