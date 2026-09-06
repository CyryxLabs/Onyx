"""Generate humanoid render-stability Release V77 over immutable V76."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v76.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v77.json"
PREDECESSOR_SHA256 = "e36d919cd05671ce537d1774a33e8293f5678ed50be189fc209c48375a5388f5"
CURRENT_CLOSURE_PATHS = (
    "core/onyx_hud_current_acceptance_v41.py",
    "core/onyx_hud_orb_v15.py",
    "core/onyx_packaged_runtime_hud_contract_v10.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v10.py",
    "core/version.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V41-E6-001.manifest.json",
    "packaging/onyx.spec",
    "qml/OnyxLiveShellV14.qml",
    "qml/components/OnyxHumanoidEntityV11.qml",
    "qml/web/onyx-humanoid-three-v2.html",
    "scripts/build_release.py",
    "scripts/capture_hud_humanoid_v11_stable_evidence.py",
    "scripts/generate_release_workflow_v77.py",
    "scripts/package_hygiene.py",
    "scripts/verify_humanoid_temporal_stability_v1.py",
    "scripts/verify_humanoid_three_temporal_v1.py",
    "tests/test_hud_source_frozen_selection_v1.py",
    "tests/test_humanoid_temporal_stability_v1.py",
    "tests/test_onyx_hud_current_acceptance_v41.py",
    "tests/test_onyx_hud_orb_v15.py",
    "tests/test_onyx_humanoid_entity_v10.py",
    "tests/test_packaged_runtime_hud_contract_v10.py",
    "tests/test_release_workflow_transition_v77.py",
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
        raise RuntimeError("Release V76 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v77",
        "issued_at": "2026-09-02T02:15:00-04:00",
        "logical_sequence": 77,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V77\0")
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
