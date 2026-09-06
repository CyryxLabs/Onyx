"""Generate the acyclic Release V45 transition over immutable V44."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v44.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v45.json"
PREDECESSOR_SHA256 = (
    "0d89a2a5eff3a6e0bc155ede25000a331921ae4096f952c3f1c70644e112804d"
)
ISSUED_AT = "2026-08-10T19:05:00-04:00"
LOGICAL_SEQUENCE = 45
CURRENT_PATHS = (
    ".github/workflows/release-packages.yml",
    "core/onyx_hud_current_acceptance_v29.py",
    "core/onyx_packaged_runtime_hud_contract_v1.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v1.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V29-E6-001.manifest.json",
    "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections/0fc6da87140a3f5455eab5995ab5736edf998fd63f98d860359da850efe61724.snapshot",
    "docs/onyx/operations/ONYX_1_1_9_V44_LINUX_DIAGNOSTIC_ACCEPTANCE_2026-08-10.md",
    "docs/onyx/operations/ONYX_1_1_9_V44_SOURCE_FREEZE_2026-08-10.md",
    "packaging/linux/Dockerfile.release-validation",
    "packaging/linux/com.cyryxlabs.onyx.metainfo.xml",
    "packaging/linux/onyx.desktop",
    "qml/OnyxLiveShellV7.qml",
    "qml/components/OnyxOrbEntityV7.qml",
    "scripts/build_release.py",
    "scripts/freeze_release_source.py",
    "scripts/generate_hud_v29_manifests.py",
    "scripts/generate_phase5_current_successor_transition_v45.py",
    "scripts/generate_release_workflow_v45.py",
    "scripts/package_hygiene.py",
    "scripts/verify_phase5_exit_retirement_v1.py",
    "scripts/verify_r11_projection_retirement_v1.py",
    "tests/fixtures/phase5_current_successor_transition_v45.json",
    "tests/test_close_to_background_v1.py",
    "tests/test_documentation_precedence_v1.py",
    "tests/test_hud_source_frozen_selection_v1.py",
    "tests/test_native_release_gate_v1.py",
    "tests/test_onyx_hud_current_acceptance_v29.py",
    "tests/test_package_hygiene_v1.py",
    "tests/test_packaged_runtime_hud_contract_v1.py",
    "tests/test_phase5_current_successor_transition_v43.py",
    "tests/test_phase5_current_successor_transition_v44.py",
    "tests/test_phase5_current_successor_transition_v45.py",
    "tests/test_release_workflow_transition_v44.py",
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
        raise RuntimeError("Release V44 predecessor digest drifted")
    entries = [
        {"path": relative, "sha256": sha256(ROOT / relative)}
        for relative in CURRENT_PATHS
    ]
    if [entry["path"] for entry in entries] != sorted(
        entry["path"] for entry in entries
    ):
        raise RuntimeError("Release V45 paths must remain sorted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("schema") != "onyx.release-workflow-transition.v44":
        raise RuntimeError("Release V44 predecessor contract drifted")
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v45",
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
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V45\0")
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
