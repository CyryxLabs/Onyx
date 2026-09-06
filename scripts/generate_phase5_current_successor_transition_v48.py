"""Generate Phase 5 current-successor V48 over immutable V47."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/phase5_current_successor_transition_v47.json"
TARGET = ROOT / "tests/fixtures/phase5_current_successor_transition_v48.json"
PREDECESSOR_SHA256 = "aabe894a896d89bfbdcda7d0c0e78d0952676612af0ee70512c706f1327f1e80"
ISSUED_AT = "2026-08-11T03:15:00-04:00"
PREDECESSOR_CLOCK_ANOMALY = None
DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V48\0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Phase 5 V47 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("schema") != "onyx.phase5-current-successor-transition.v47":
        raise RuntimeError("Phase 5 V47 predecessor contract drifted")

    historical = []
    for prior in predecessor["historical_bindings"]:
        entry = dict(prior)
        entry["current_sha256"] = sha256(ROOT / entry["path"])
        historical.append(entry)
    successors = []
    for prior in predecessor["named_successors"]:
        entry = dict(prior)
        entry["current_sha256"] = sha256(ROOT / entry["path"])
        successors.append(entry)

    record: dict[str, object] = {
        "schema": "onyx.phase5-current-successor-transition.v48",
        "issued_at": ISSUED_AT,
        "predecessor_clock_anomaly": PREDECESSOR_CLOCK_ANOMALY,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
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
                "historical_bindings": len(result["historical_bindings"]),
                "named_successors": len(result["named_successors"]),
            },
            sort_keys=True,
        )
    )
