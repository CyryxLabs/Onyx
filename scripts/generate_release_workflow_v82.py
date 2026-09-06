"""Generate Mark-LII operational-parity Release V82 over immutable V81."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v81.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v82.json"
PREDECESSOR_SHA256 = "35fcaf2743ed7144ea9bfed5b013230f2815b17d1d8bb361f1d13bcf92437d9e"
CURRENT_CLOSURE_PATHS = (
    "actions/computer_settings.py",
    "actions/file_controller.py",
    "core/audio_contract.py",
    "core/audio_device_selection_v1.py",
    "core/capability_parity_v1.py",
    "core/live_voice_continuity_v1.py",
    "core/live_voice_preference_v1.py",
    "core/permission_broker.py",
    "core/undo_journal_v1.py",
    "core/version.py",
    "docs/onyx/ONYX_FUNCTIONAL_PARITY_V1.md",
    "docs/stories/ONYX-MARK-LII-OPERATIONAL-PARITY-V1.story.md",
    "main.py",
    "memory/memory_manager.py",
    "memory/store.py",
    "packaging/onyx.spec",
    "packaging/windows/onyx.iss",
    "scripts/bootstrap_onyx.pyw",
    "scripts/bootstrap_onyx_live_v24.pyw",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v82.py",
    "scripts/onyx_audio_cli.py",
    "scripts/verify_humanoid_temporal_stability_v1.py",
    "tests/test_bootstrap_empty_windows_argument_v1.py",
    "tests/test_capability_parity_v1.py",
    "tests/test_hud_source_frozen_selection_v1.py",
    "tests/test_installer_lifecycle_v1.py",
    "tests/test_live_audio_stream_ownership_v1.py",
    "tests/test_mark_lii_audio_parity_v1.py",
    "tests/test_mark_lii_undo_confirmation_parity_v1.py",
    "tests/test_onyx_humanoid_entity_v10.py",
    "tests/test_native_release_gate_v1.py",
    "tests/test_regressions.py",
    "tests/test_release_workflow_transition_v82.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V81 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v82",
        "issued_at": "2026-09-02T17:21:00-04:00",
        "logical_sequence": 82,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V82\0")
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
