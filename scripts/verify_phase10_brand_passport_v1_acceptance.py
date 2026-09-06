"""Verify Phase 10 Brand Passport V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase10_brand_passport_v1 as candidate  # noqa: E402

ID = "VE-P10-BRAND-PASSPORT-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P10-BRAND-PASSPORT-V1-E6-001.sha256"
RECORD_SHA = "1e6f1c94963f8eedf3a362159650651cba789967ac8a4e1e54548f96599d246d"
METADATA_SHA = "3f21bf082f9f81a699d38fa5658528be94219490b4f894e05e3d2b5a05116cb9"
ANCHOR_SHA = "64dee786a9509c62981e11053da42be238fe1d2bd99765bc76deb8efc176a8bc"
MANIFEST_SHA = "5d0a4bd6c6b3a15b112bb86a95da96a5008b784704f511e3df57ab7043b3af0e"
ROOT = "6f218e78ca1be45218ae8bd25448666482714edd2cd5a087d4eace45654f2483"
MARKER = "P10_BRAND_PASSPORT_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Phase 10 acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(candidate.MANIFEST) != MANIFEST_SHA
    ):
        raise RuntimeError("Phase 10 acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Phase 10 acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["candidate_manifest_sha256"] != MANIFEST_SHA
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 504
        or metadata["results"]["subtests_passed"] != 80
        or claims.get("phase10_brand_inventory_default_off_contract_complete")
        is not True
        or claims.get("strict_brand_separation_enforced") is not True
        or claims.get("publish_authority_added") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Phase 10 acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Phase 10 accepted candidate reproduction drift")
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
