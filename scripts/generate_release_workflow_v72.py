"""Generate humanoid-presence Release V72 over immutable V71."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v71.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v72.json"
PREDECESSOR_SHA256 = "cb368372543f2ddb07735a472c3d81dd5cdc87150f07d50a247ef944c326fe38"
CURRENT_CLOSURE_PATHS = (
    "core/onyx_hud_current_acceptance_v37.py",
    "core/onyx_hud_orb_v14.py",
    "core/onyx_packaged_runtime_hud_contract_v6.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v6.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V37-E6-001.manifest.json",
    "docs/stories/ONYX-LIVING-LIQUID-METAL-ORB-V1.story.md",
    "qml/OnyxLiveShellV13.qml",
    "qml/assets/onyx-humanoid-cyryx-v11.png",
    "qml/components/OnyxHumanoidEntityV10.qml",
    "qml/web/onyx-humanoid-three-v1.html",
    "qml/web/data/onyx-humanoid-pointcloud-v1.js",
    "qml/web/vendor/three/LICENSE",
    "qml/web/vendor/three/three.module.min.js",
    "qml/web/vendor/three/three.core.min.js",
    "scripts/capture_hud_humanoid_v10_evidence.py",
    "scripts/capture_humanoid_three_motion_v2.py",
    "scripts/generate_humanoid_pointcloud_v1.py",
    "scripts/generate_release_workflow_v72.py",
    "tests/test_onyx_hud_current_acceptance_v37.py",
    "tests/test_onyx_hud_orb_v14.py",
    "tests/test_onyx_humanoid_entity_v10.py",
    "tests/test_text_command_latency_v1.py",
    "ui.py",
    "tests/test_packaged_runtime_hud_contract_v6.py",
    "tests/test_release_workflow_transition_v72.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V71 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v72",
        "issued_at": "2026-08-31T22:15:00-04:00",
        "logical_sequence": 72,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V72\0")
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
