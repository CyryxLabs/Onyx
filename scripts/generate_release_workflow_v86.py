"""Generate voice-selector Release V86 over immutable V85."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v85.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v86.json"
PREDECESSOR_SHA256 = "891e63d0872eb033d620c9f5447ed863f6393995f37a5799c8b2d1c04296ed11"
CURRENT_CLOSURE_PATHS = (
    "core/onyx_hud_current_acceptance_v43.py",
    "core/onyx_packaged_runtime_hud_contract_v12.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v12.py",
    "core/version.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V43-E6-001.manifest.json",
    "docs/stories/ONYX-MARK-LII-OPERATIONAL-PARITY-V1.story.md",
    "packaging/onyx.spec",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v86.py",
    "scripts/package_hygiene.py",
    "tests/test_hud_source_frozen_selection_v1.py",
    "tests/test_onyx_hud_current_acceptance_v42.py",
    "tests/test_onyx_hud_current_acceptance_v43.py",
    "tests/test_packaged_runtime_hud_contract_v11.py",
    "tests/test_packaged_runtime_hud_contract_v12.py",
    "tests/test_release_workflow_transition_v86.py",
    "tests/test_voice_selection_ui_v1.py",
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
        raise RuntimeError("Release V85 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v86",
        "issued_at": "2026-09-02T21:35:51-04:00",
        "logical_sequence": 86,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V86\0")
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
