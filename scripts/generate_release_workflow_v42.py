"""Generate the acyclic Release V42 transition over immutable V41."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v41.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v42.json"
PREDECESSOR_SHA256 = (
    "8bce34bf6b5b18c3f1b369633501b4eb8d02cec1a5898694d126bb89398115af"
)
ISSUED_AT = "2026-08-10T16:10:00-04:00"
LOGICAL_SEQUENCE = 42
PREDECESSOR_CLOCK_ANOMALY = {
    "predecessor_issued_at": "2026-08-10T19:00:00-04:00",
    "observed_at": ISSUED_AT,
    "reason": "predecessor_future_dated",
}
CURRENT_PATHS = (
    "core/missions.py",
    "core/onyx_hud_current_acceptance_v28.py",
    "core/onyx_packaged_runtime_hud_contract_v1.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v1.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V28-E6-001.manifest.json",
    "scripts/build_release.py",
    "scripts/freeze_release_source.py",
    "scripts/generate_hud_v28_manifests.py",
    "scripts/generate_phase5_current_successor_transition_v44.py",
    "scripts/generate_release_workflow_v42.py",
    "scripts/monitor_windows_long_session.py",
    "scripts/package_hygiene.py",
    "scripts/verify_phase5_exit_retirement_v1.py",
    "tests/fixtures/phase5_current_successor_transition_v44.json",
    "tests/test_hud_source_frozen_selection_v1.py",
    "tests/test_missions.py",
    "tests/test_monitor_windows_long_session.py",
    "tests/test_native_release_gate_v1.py",
    "tests/test_onyx_hud_current_acceptance_v28.py",
    "tests/test_packaged_runtime_hud_contract_v1.py",
    "tests/test_phase5_current_successor_transition_v43.py",
    "tests/test_phase5_current_successor_transition_v44.py",
    "tests/test_portable_current_release_gate_v1.py",
    "ui.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V41 predecessor digest drifted")
    entries = [
        {"path": relative, "sha256": sha256(ROOT / relative)}
        for relative in CURRENT_PATHS
    ]
    if [entry["path"] for entry in entries] != sorted(
        entry["path"] for entry in entries
    ):
        raise RuntimeError("Release V42 paths must remain sorted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("schema") != "onyx.release-workflow-transition.v41":
        raise RuntimeError("Release V41 predecessor contract drifted")
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v42",
        "issued_at": ISSUED_AT,
        "logical_sequence": LOGICAL_SEQUENCE,
        "predecessor_clock_anomaly": PREDECESSOR_CLOCK_ANOMALY,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256()
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V42\0")
    frame(digest, record["issued_at"])
    frame(digest, str(record["logical_sequence"]))
    anomaly = record["predecessor_clock_anomaly"]
    frame(digest, anomaly["predecessor_issued_at"])
    frame(digest, anomaly["observed_at"])
    frame(digest, anomaly["reason"])
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
