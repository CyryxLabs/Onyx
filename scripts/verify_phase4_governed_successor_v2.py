"""Verify the corrected current Phase 4 governed-authority closure."""

from __future__ import annotations

import json
import sys

from scripts import verify_phase4_governed_successor_v1 as predecessor
from scripts.verify_legacy_evidence_retirement_v1 import LegacyEvidenceRetirementError


STATUS = "P4_GOVERNED_SUCCESSOR_V2_OK"
EXPECTED_AUTHORITY = [
    "core.control_plane",
    "core.domain_ledger",
    "core.workspaces",
]


def verify() -> dict[str, object]:
    result = predecessor.verify()
    if result.get("static_authority") != EXPECTED_AUTHORITY:
        raise LegacyEvidenceRetirementError("V2 static authority closure drifted")
    if result.get("fresh_import_authority") != EXPECTED_AUTHORITY:
        raise LegacyEvidenceRetirementError("V2 fresh authority closure drifted")
    return result | {
        "status": STATUS,
        "predecessor_status": predecessor.STATUS,
        "authority_closure_consistent": True,
    }


def main() -> int:
    try:
        result = verify()
    except (LegacyEvidenceRetirementError, RuntimeError, OSError, ValueError) as exc:
        print(f"P4_GOVERNED_SUCCESSOR_V2_FAILED {exc}", file=sys.stderr)
        return 1
    print(f"{STATUS} {json.dumps(result, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
