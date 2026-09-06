"""Generate compositor-continuity Release V78 over immutable V77."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v77.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v78.json"
PREDECESSOR_SHA256 = "97fdd81b2a81c6cfe150a503b52e1dd3008521141252e0601d9d3d38871ef055"
CURRENT_CLOSURE_PATHS = (
    "core/onyx_hud_current_acceptance_v42.py",
    "core/onyx_hud_orb_v16.py",
    "core/onyx_packaged_runtime_hud_contract_v11.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v11.py",
    "core/version.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V42-E6-001.manifest.json",
    "packaging/onyx.spec",
    "qml/OnyxLiveShellV15.qml",
    "qml/components/OnyxHumanoidEntityV12.qml",
    "qml/web/onyx-humanoid-three-v3.html",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v78.py",
    "scripts/package_hygiene.py",
    "tests/test_humanoid_compositor_continuity_v1.py",
    "tests/test_onyx_hud_current_acceptance_v42.py",
    "tests/test_packaged_runtime_hud_contract_v11.py",
    "tests/test_release_workflow_transition_v78.py",
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
        raise RuntimeError("Release V77 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v78",
        "issued_at": "2026-09-02T04:05:00-04:00",
        "logical_sequence": 78,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V78\0")
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

