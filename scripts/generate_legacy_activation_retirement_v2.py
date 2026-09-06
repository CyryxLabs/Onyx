"""Generate the append-only legacy activation retirement V2 descriptor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
PREDECESSOR = PROJECT / "docs/onyx/checkpoints/LEGACY_ACTIVATION_RETIREMENT_V1.json"
OUTPUT = PROJECT / "docs/onyx/checkpoints/LEGACY_ACTIVATION_RETIREMENT_V2.json"
CURRENT_SUCCESSOR = "tests/test_phase6_current_v1.py"
RETIRED_CLAIM = "activation-v1-v11-historical-closures"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, object]:
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    claims = json.loads(json.dumps(predecessor["claims"]))
    for claim in claims:
        if claim["id"] == RETIRED_CLAIM:
            claim["successor_tests"] = [
                {
                    "path": CURRENT_SUCCESSOR,
                    "sha256": _sha256(PROJECT / CURRENT_SUCCESSOR),
                }
            ]
            claim["reason"] = (
                "The immutable V1-V11 closures and their retired V19 successor "
                "remain historical; the Phase 6 current verifier proves the "
                "active V24 activation chain."
            )
    return {
        "schema": "onyx.legacy-activation-retirement.v2",
        "issued_at": "2026-08-23T17:00:00-04:00",
        "predecessor": {
            "path": "docs/onyx/checkpoints/LEGACY_ACTIVATION_RETIREMENT_V1.json",
            "sha256": _sha256(PREDECESSOR),
        },
        "policy": predecessor["policy"]
        | {
            "retired_successor_generations_cannot_be_current": True,
        },
        "claims": claims,
    }


def main() -> None:
    payload = json.dumps(build(), indent=2, ensure_ascii=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8", newline="\n")
    print("LEGACY_ACTIVATION_RETIREMENT_V2_GENERATED", _sha256(OUTPUT))


if __name__ == "__main__":
    main()
