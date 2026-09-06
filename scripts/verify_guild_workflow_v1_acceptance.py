"""Verify Guild Workflow V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_guild_workflow_v1 as candidate  # noqa: E402

ID = "VE-GUILD-WORKFLOW-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-GUILD-WORKFLOW-V1-E6-001.sha256"
RECORD_SHA = "c6a382e47c08c30ce720d4c15a64d1553eaee3a894871d357d9307f86a3a74fe"
METADATA_SHA = "7f3350a8a23cfdfbba80abf63cab496a7b7dbacd4611092b6d7e32b05d071e32"
ANCHOR_SHA = "b4711e50af05fdaf85249b20fdf8d235f9041f05f769a5b2f3a1f7665d84fe9a"
ROOT = "48043deead60aecc926925a191926f785896229026097e1e2048e46916dabfdc"
MARKER = "GUILD_WORKFLOW_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Guild Workflow acceptance artifact unavailable")
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
        raise RuntimeError("Guild Workflow acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Guild Workflow acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 752
        or metadata["results"]["subtests_passed"] != 96
        or claims.get("guild_workflow_default_off_contract_complete") is not True
        or claims.get("template_run_and_authority_coupling_enforced") is not True
        or claims.get("execution_or_dispatch_authority_added") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("independent_human_review_performed") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Guild Workflow acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Guild Workflow accepted candidate reproduction drift")
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
