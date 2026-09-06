"""Generate the acyclic Release V41 transition over immutable V40."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v40.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v41.json"
PREDECESSOR_SHA256 = (
    "19886157609e46aad4372947cf79853012b3032f09676d08595d77da0a57c05e"
)
ISSUED_AT = "2026-08-10T19:00:00-04:00"
LOGICAL_SEQUENCE = 41
CURRENT_PATHS = (
    "docs/onyx/acceptance/VE-HUD-CURRENT-V27-E6-001.manifest.json",
    "packaging/windows/onyx.iss",
    "scripts/build_release.py",
    "scripts/generate_phase5_current_successor_transition_v43.py",
    "scripts/generate_release_workflow_v41.py",
    "scripts/verify_phase5_exit_retirement_v1.py",
    "tests/fixtures/phase5_current_successor_transition_v43.json",
    "tests/test_installer_lifecycle_v1.py",
    "tests/test_phase5_current_successor_transition_v42.py",
    "tests/test_phase5_current_successor_transition_v43.py",
    "tests/test_release_preparation_v110.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V40 predecessor digest drifted")
    entries = [
        {"path": relative, "sha256": sha256(ROOT / relative)}
        for relative in CURRENT_PATHS
    ]
    if [entry["path"] for entry in entries] != sorted(
        entry["path"] for entry in entries
    ):
        raise RuntimeError("Release V41 paths must remain sorted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("schema") != "onyx.release-workflow-transition.v40":
        raise RuntimeError("Release V40 predecessor contract drifted")
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v41",
        "issued_at": ISSUED_AT,
        "logical_sequence": LOGICAL_SEQUENCE,
        "predecessor_clock_anomaly": None,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256()
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V41\0")
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
