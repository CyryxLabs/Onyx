"""Verify Voice Session Authority V1 E6 acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_voice_session_authority_v1 as candidate  # noqa: E402

ID = "VE-VOICE-SESSION-AUTHORITY-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = (
    PROJECT / "docs/onyx/VE-ACCEPTANCE-VOICE-SESSION-AUTHORITY-V1-E6-001.sha256"
)
RECORD_SHA = "26c45b3813e8ed2fffefc0fec42d9e2f9f100934b1ba3df7df5acb028e8e8990"
METADATA_SHA = "f2947207bd1ba6057ca2518fd1b4f04d0010f81cb24543a47479255eadde45ad"
ANCHOR_SHA = "2edf2d8094dad3c261a900617df795874d875bdc5975e6d2ceeb82d5dd027bc8"
ROOT = "8d16f979db21395e3c3ba8896ca8e8442b2ecedfe548c1ebfb75a88faaf6e7aa"
MARKER = "VOICE_SESSION_AUTHORITY_V1_ACCEPTANCE_OK"


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Voice Session Authority acceptance artifact unavailable")
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
        raise RuntimeError("Voice Session Authority acceptance hash drift")
    expected_anchor = (
        f"{RECORD_SHA}  docs/onyx/acceptance/{ID}.md\n"
        f"{METADATA_SHA}  docs/onyx/acceptance/{ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise RuntimeError("Voice Session Authority acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    claims = metadata.get("claims", {})
    if (
        metadata["decision"] != "accepted"
        or metadata["findings"] != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 977
        or metadata["results"]["subtests_passed"] != 96
        or claims.get("voice_session_authority_default_off_contract_complete")
        is not True
        or claims.get("grants_authority_rather_than_shadowing") is not True
        or claims.get("always_explicit_gates_waived") is not False
        or claims.get("delete_authorizable_by_envelope") is not False
        or claims.get("speaker_verification_present") is not False
        or claims.get("spoofed_opening_prevented") is not False
        or claims.get("runtime_hook_installed") is not False
        or claims.get("network_or_process_opened") is not False
        or claims.get("independent_human_review_performed") is not False
        or claims.get("full_onyx_prd_complete") is not False
    ):
        raise RuntimeError("Voice Session Authority acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != ROOT:
        raise RuntimeError("Voice Session Authority accepted reproduction drift")
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
