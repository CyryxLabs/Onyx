"""Generate the additive Phase 5 V56 current-successor transition over V55.

V55 tracked `ui.py`, `main.py` and `dashboard/server.py` as historical
artifacts whose *current* form is tracked by SHA-256.  Those current forms have
now advanced: the approval prompt surfaces its window before blocking (an
unseen prompt timed out and was recorded as a refusal), and the dashboard
accepts a mesh address so a phone can reach the host from outside the LAN.

Nothing historical is rewritten.  Identity tuples — path, historical hash,
state and successor — are carried across unchanged, and only the
`current_sha256` pointers advance, which is exactly what a current-successor
transition exists to record.  The new root is bound under its own V56 domain so
it can never be confused with its predecessor.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.verify_phase5_exit_retirement_v1 import (  # noqa: E402
    CURRENT_TRANSITION_V55,
    CURRENT_TRANSITION_V55_SHA256,
)

TARGET = PROJECT / "tests/fixtures/phase5_current_successor_transition_v56.json"
SCHEMA = "onyx.phase5-current-successor-transition.v56"
ISSUED_AT = "2026-08-22T12:30:00-04:00"
DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V56\0"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _frame(hasher: "hashlib._Hash", value: str) -> None:
    encoded = value.encode("utf-8")
    hasher.update(len(encoded).to_bytes(8, "big"))
    hasher.update(encoded)


def _current(relative: str) -> str:
    return _sha((PROJECT / relative).read_bytes())


def build() -> dict[str, object]:
    raw = CURRENT_TRANSITION_V55.read_bytes()
    if _sha(raw) != CURRENT_TRANSITION_V55_SHA256:
        raise SystemExit("refusing to build on a drifted V55 predecessor")
    predecessor = json.loads(raw.decode("utf-8"))

    historical = [
        {
            "path": entry["path"],
            "historical_sha256": entry["historical_sha256"],
            "current_sha256": _current(entry["path"]),
            "state": entry["state"],
            "successor": entry["successor"],
        }
        for entry in predecessor["historical_bindings"]
    ]
    successors = [
        {
            "path": entry["path"],
            "predecessor_sha256": entry["predecessor_sha256"],
            "current_sha256": _current(entry["path"]),
        }
        for entry in predecessor["named_successors"]
    ]

    root = hashlib.sha256()
    root.update(DOMAIN)
    for entry in historical:
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(root, value)
    for entry in successors:
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(root, value)

    return {
        "schema": SCHEMA,
        "issued_at": ISSUED_AT,
        "predecessor_clock_anomaly": None,
        "predecessor": {
            "path": "tests/fixtures/phase5_current_successor_transition_v55.json",
            "sha256": CURRENT_TRANSITION_V55_SHA256,
        },
        "policy": predecessor["policy"],
        "historical_bindings": historical,
        "named_successors": successors,
        "current_root_sha256": root.hexdigest(),
    }


def main() -> int:
    record = build()
    # Canonical on every platform: UTF-8, LF only, no BOM, trailing newline.
    payload = (json.dumps(record, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    if b"\r" in payload:
        raise SystemExit("refusing to write a non-canonical transition")
    TARGET.write_bytes(payload)
    print(f"wrote {TARGET.relative_to(PROJECT).as_posix()}")
    print(f"transition sha256 : {_sha(payload)}")
    print(f"current root      : {record['current_root_sha256']}")
    for entry in record["historical_bindings"]:
        if entry["state"] == "unavailable-tombstoned":
            print(f"  tracked current   : {entry['path']} -> {entry['current_sha256'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
