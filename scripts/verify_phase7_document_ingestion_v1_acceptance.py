"""Verify the Document Ingestion V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import verify_phase7_document_ingestion_v1 as candidate  # noqa: E402

ACCEPTANCE_ID = "VE-P7-DOCUMENT-INGESTION-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P7-DOCUMENT-INGESTION-V1-E6-001.sha256"
RECORD_SHA256 = "3d6cea680bb591ade10f1cde819fa773658078c5f782c182abadf38a5bf48cd5"
METADATA_SHA256 = "d24640d28cd5c420d5b4b0f714cce5fc38544a230616ea5ac961915882978bc3"
ANCHOR_SHA256 = "db44bdd6c76333300c241f24f52de210756881f254511ac4ac61b6f452c7937f"
CANDIDATE_MANIFEST_SHA256 = (
    "20efa9f6125d881eab60e4edbd04d103196608cd26875634af06ee47793b8a03"
)
CANDIDATE_ROOT = "8b7749f3228667eb15e66011129549b569caf9adbdd079a50368ae0967b8a513"
MARKER = "P7_DOCUMENT_INGESTION_V1_ACCEPTANCE_OK"


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
        f"{METADATA_SHA256}  docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise AcceptanceError("acceptance anchor drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    if (
        metadata.get("acceptance_id") != ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT
        or metadata.get("results", {}).get("passed") != 178
        or metadata.get("results", {}).get("subtests_passed") != 77
        or metadata.get("claims", {}).get("document_ingestion_v1_accepted") is not True
        or metadata.get("claims", {}).get("instruction_authority") is not False
        or metadata.get("claims", {}).get("phase7_exit") is not False
    ):
        raise AcceptanceError("acceptance semantic drift")
    reproduced = candidate.verify(run_tests=run_tests)
    if reproduced["artifact_root_sha256"] != CANDIDATE_ROOT:
        raise AcceptanceError("accepted candidate reproduction drift")
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "decision": "accepted",
        "findings": metadata["findings"],
        "claims": metadata["claims"],
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
