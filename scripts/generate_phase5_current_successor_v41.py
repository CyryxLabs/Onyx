"""Generate the immutable Phase 5 current-successor V41 receipt over V40."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/phase5_current_successor_transition_v40.json"
TARGET = ROOT / "tests/fixtures/phase5_current_successor_transition_v41.json"
ISSUED_AT = "2026-08-10T12:00:00-04:00"
DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V41\0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    historical = []
    for entry in predecessor["historical_bindings"]:
        current = dict(entry)
        current["current_sha256"] = sha256(ROOT / current["path"])
        historical.append(current)
    successors = []
    for entry in predecessor["named_successors"]:
        current = dict(entry)
        current["current_sha256"] = sha256(ROOT / current["path"])
        successors.append(current)

    record: dict[str, object] = {
        "schema": "onyx.phase5-current-successor-transition.v41",
        "issued_at": ISSUED_AT,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": sha256(PREDECESSOR),
        },
        "policy": predecessor["policy"],
        "historical_bindings": historical,
        "named_successors": successors,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256()
    digest.update(DOMAIN)
    for entry in historical:
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            frame(digest, value)
    for entry in successors:
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            frame(digest, value)
    record["current_root_sha256"] = digest.hexdigest()
    TARGET.write_text(
        json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return record


if __name__ == "__main__":
    result = generate()
    print(
        json.dumps(
            {
                "fixture_sha256": sha256(TARGET),
                "root_sha256": result["current_root_sha256"],
            },
            sort_keys=True,
        )
    )
