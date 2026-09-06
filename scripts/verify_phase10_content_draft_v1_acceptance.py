"""Verify Phase 10 Content Draft V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase10_content_draft_v1 as candidate  # noqa: E402

ID = "VE-P10-CONTENT-DRAFT-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P10-CONTENT-DRAFT-V1-E6-001.sha256"
RECORD_SHA = "94f0964876f8c4a094ec8a3152501a87f20ddd8c1e08545eee591d92c822ad13"
METADATA_SHA = "8af9f47156ccd9ad8de232a105a40b6a32d9a42a85852d48de29c805fa5d850f"
ANCHOR_SHA = "cee917429abc1c5463a839411973307b6cf381a6e2003256a309ae5360e8a221"
MANIFEST_SHA = "f57046e1f65de10484b8ef31c706323683fd57952076d164dd0395150fdba8ff"
ROOT = "59308ada89f691443238644bdb18b7bc29aa66a61365b95908bc5631d8b8d449"
MARKER = "P10_CONTENT_DRAFT_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Phase 10 content acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(candidate.MANIFEST) != MANIFEST_SHA
    ):
        raise RuntimeError("Phase 10 content acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Phase 10 content acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["candidate_manifest_sha256"] != MANIFEST_SHA
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 607
        or metadata["results"]["subtests_passed"] != 80
        or claims.get("phase10_content_draft_default_off_contract_complete")
        is not True
        or claims.get("provenance_claim_accessibility_policy_gates_enforced")
        is not True
        or claims.get("publish_authority_added") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Phase 10 content acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Phase 10 content accepted candidate reproduction drift")
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
