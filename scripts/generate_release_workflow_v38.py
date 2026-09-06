"""Generate the acyclic Release V38 transition over immutable V37."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v37.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v38.json"
ISSUED_AT = "2026-08-10T16:30:00-04:00"
LOGICAL_SEQUENCE = 38
CURRENT_PATHS = (
    "core/onyx_packaged_runtime_hud_contract_v1.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v1.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json",
    "scripts/generate_hud_v26_manifests.py",
    "scripts/generate_release_workflow_v38.py",
    "scripts/launch_onyx_live_v24.pyw",
    "scripts/verify_phase5_exit_retirement_v1.py",
    "tests/test_launch_onyx_live_v24.py",
    "tests/test_release_workflow_transition_v32.py",
    "tests/test_release_workflow_transition_v33.py",
    "tests/test_release_workflow_transition_v34.py",
    "tests/test_release_workflow_transition_v35.py",
    "tests/test_release_workflow_transition_v36.py",
    "tests/test_release_workflow_transition_v37.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    entries = [
        {"path": relative, "sha256": sha256(ROOT / relative)}
        for relative in CURRENT_PATHS
    ]
    if [entry["path"] for entry in entries] != sorted(
        entry["path"] for entry in entries
    ):
        raise RuntimeError("Release V38 paths must remain sorted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v38",
        "issued_at": ISSUED_AT,
        "logical_sequence": LOGICAL_SEQUENCE,
        "predecessor_clock_anomaly": None,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": sha256(PREDECESSOR),
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256()
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V38\0")
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
