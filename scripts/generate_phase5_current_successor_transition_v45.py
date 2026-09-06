"""Generate Phase 5 current-successor V45 over immutable V44."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/phase5_current_successor_transition_v44.json"
TARGET = ROOT / "tests/fixtures/phase5_current_successor_transition_v45.json"
PREDECESSOR_SHA256 = (
    "fac94f38fd08f98e1699b73924c1ead59223228a118b8159152b0b5657942cb2"
)
ISSUED_AT = "2026-08-10T18:55:00-04:00"
PREDECESSOR_CLOCK_ANOMALY = {
    "predecessor_issued_at": "2026-08-10T18:30:00-04:00",
    "observed_at": "2026-08-10T15:55:00-04:00",
    "reason": "predecessor_future_dated",
}
DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V45\0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Phase 5 V44 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("schema") != "onyx.phase5-current-successor-transition.v44":
        raise RuntimeError("Phase 5 V44 predecessor contract drifted")

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
        "schema": "onyx.phase5-current-successor-transition.v45",
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
    for value in (
        PREDECESSOR_CLOCK_ANOMALY["predecessor_issued_at"],
        PREDECESSOR_CLOCK_ANOMALY["observed_at"],
        PREDECESSOR_CLOCK_ANOMALY["reason"],
    ):
        frame(digest, value)
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
