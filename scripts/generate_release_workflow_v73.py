"""Generate stable calibrated-humanoid Release V73 over immutable V72."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v72.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v73.json"
PREDECESSOR_SHA256 = "b8519c0263f609adeb4cba032cf088b6e424cb5cb9a6709ed76ec36b42224137"
CURRENT_CLOSURE_PATHS = (
    "core/camera_gesture_attention_v1.py",
    "core/onyx_hud_current_acceptance_v38.py",
    "core/onyx_hud_current_acceptance_v39.py",
    "core/onyx_hud_current_acceptance_v40.py",
    "core/onyx_packaged_runtime_hud_contract_v7.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v7.py",
    "core/onyx_packaged_runtime_hud_contract_v8.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v8.py",
    "core/onyx_packaged_runtime_hud_contract_v9.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v9.py",
    "docs/onyx/acceptance/VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V38-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V39-E6-001.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V40-E6-001.manifest.json",
    "docs/stories/ONYX-BROWNFIELD-AUDIT-REMEDIATION-V1.story.md",
    "docs/stories/ONYX-LIVING-LIQUID-METAL-ORB-V1.story.md",
    "main.py",
    "packaging/onyx.spec",
    "qml/components/OnyxHumanoidEntityV10.qml",
    "scripts/generate_release_workflow_v73.py",
    "scripts/onyx_social_cli.py",
    "scripts/package_hygiene.py",
    "scripts/qt_bundle_probe_v1.py",
    "scripts/verify_capability_nexus_current_v1.py",
    "tests/test_camera_gesture_attention_v1.py",
    "tests/test_capability_nexus_current_v1.py",
    "tests/test_close_to_background_v1.py",
    "tests/test_hud_source_frozen_selection_v1.py",
    "tests/test_onyx_hud_current_acceptance_v38.py",
    "tests/test_onyx_hud_current_acceptance_v39.py",
    "tests/test_onyx_hud_current_acceptance_v40.py",
    "tests/test_onyx_humanoid_entity_v10.py",
    "tests/test_packaged_runtime_hud_contract_v7.py",
    "tests/test_packaged_runtime_hud_contract_v8.py",
    "tests/test_packaged_runtime_hud_contract_v9.py",
    "tests/test_release_workflow_transition_v73.py",
    "tests/test_runtime_shutdown_hardening_v1.py",
    "tests/test_social_publish_v1.py",
    "tests/test_windows_qt_bundle_toolchain_v1.py",
    "ui.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V72 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v73",
        "issued_at": "2026-09-01T12:30:00-04:00",
        "logical_sequence": 73,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V73\0")
    for value in (
        record["issued_at"],
        str(record["logical_sequence"]),
        record["predecessor"]["path"],
        record["predecessor"]["sha256"],
    ):
        frame(digest, value)
    for entry in entries:
        frame(digest, entry["path"])
        frame(digest, entry["sha256"])
    record["current_root_sha256"] = digest.hexdigest()
    TARGET.write_text(
        json.dumps(record, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return record


if __name__ == "__main__":
    print(json.dumps(generate(), sort_keys=True))
