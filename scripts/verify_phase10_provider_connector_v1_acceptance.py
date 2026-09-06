"""Verify Phase 10 Provider Connector V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase10_provider_connector_v1 as candidate  # noqa: E402

ID = "VE-P10-PROVIDER-CONNECTOR-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P10-PROVIDER-CONNECTOR-V1-E6-001.sha256"
RECORD_SHA = "c5a68dc99acb0c102de42c9434907ab6619423efa04e87ab5299bba195043cfe"
METADATA_SHA = "e84e22f6af91a32a70ee3cb8464aa471c7fada3ab30d5a74ce6cb54bfb77535e"
ANCHOR_SHA = "b2d49c458659af647e844663f470e0510b9f837954f9a358161c7618eb1be6ab"
MANIFEST_SHA = "87b3ed60dd533f29e3b42447ada20846dda231f8b5f5478da59c9d7e1d822d0c"
ROOT = "7aba66ad246c75b1660c70c00dbf012526de72e1592892bee0fd1ea363a35711"
MARKER = "P10_PROVIDER_CONNECTOR_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Phase 10 provider acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(candidate.MANIFEST) != MANIFEST_SHA
    ):
        raise RuntimeError("Phase 10 provider acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Phase 10 provider acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["candidate_manifest_sha256"] != MANIFEST_SHA
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 570
        or metadata["results"]["subtests_passed"] != 80
        or claims.get("phase10_provider_connector_default_off_readonly_contract_complete")
        is not True
        or claims.get("route_pin_and_anti_spoof_enforced") is not True
        or claims.get("publish_authority_added") is not False
        or claims.get("live_network_exercised") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Phase 10 provider acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Phase 10 provider accepted candidate reproduction drift")
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
