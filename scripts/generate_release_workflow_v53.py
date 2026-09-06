"""Generate the additive Release V53 portable-test successor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v52.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v53.json"
PREDECESSOR_SHA256 = (
    "d267bda604226f0136638b5b20f9b2abe7d858e25b61ce4ba0a6214caf016e58"
)
ISSUED_AT = "2026-08-11T15:20:00-04:00"
LOGICAL_SEQUENCE = 53
ADDITIONAL_PATHS = (
    "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V14.json",
    "scripts/freeze_release_source.py",
    "scripts/generate_release_workflow_v53.py",
    "scripts/verify_current_successor_retirement_v1.py",
    "scripts/verify_phase5_exit_retirement_v1.py",
    "scripts/verify_source_freeze_v1.py",
    "tests/test_current_successor_retirement_v14.py",
    "tests/test_freeze_release_source_v53.py",
    "tests/test_portable_activation_injection_v1.py",
    "tests/test_release_workflow_transition_v53.py",
    "tests/test_verify_source_freeze_v1.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V52 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v52"
        or predecessor.get("logical_sequence") != 52
    ):
        raise RuntimeError("Release V52 predecessor contract drifted")
    current_paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *ADDITIONAL_PATHS,
        }
    )
    entries = [
        {"path": relative, "sha256": sha256(ROOT / relative)}
        for relative in current_paths
    ]
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v53",
        "issued_at": ISSUED_AT,
        "logical_sequence": LOGICAL_SEQUENCE,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256()
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V53\0")
    frame(digest, record["issued_at"])
    frame(digest, str(record["logical_sequence"]))
    frame(digest, record["predecessor"]["path"])
    frame(digest, record["predecessor"]["sha256"])
    for entry in entries:
        frame(digest, entry["path"])
        frame(digest, entry["sha256"])
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
                "paths": len(result["current_release_paths"]),
            },
            sort_keys=True,
        )
    )
