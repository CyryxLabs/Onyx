"""Generate shortcut-bootstrap recovery Release V95 over immutable V94."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v94.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v95.json"
PREDECESSOR_SHA256 = "2fa11978b0b19228603b6593928e94d7daf5e5bd31634bcd1d90d5c790ad8b6b"
CURRENT_CLOSURE_PATHS = (
    "core/google_workspace_host_v1.py",
    "core/onyx_live_activation_google_workspace_v1.py",
    "core/onyx_hud_current_acceptance_v46.py",
    "core/onyx_packaged_runtime_hud_contract_v15.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v15.py",
    "core/version.py",
    "docs/onyx/CAPABILITY_AUDIT_2026-09-04.md",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V46-E6-001.manifest.json",
    "docs/onyx/evidence/ONYX_GWS_1_0_1_1_SOURCE_PROVENANCE_20260905.json",
    "docs/stories/ONYX-MARK-LII-OPERATIONAL-PARITY-V1.story.md",
    "packaging/windows/onyx.iss",
    "scripts/bootstrap_onyx.pyw",
    "scripts/bootstrap_onyx_live_v24.pyw",
    "scripts/bootstrap_onyx_live_google_workspace_v1.pyw",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v95.py",
    "scripts/launch_onyx_live_google_workspace_v1.pyw",
    "tests/test_bootstrap_empty_windows_argument_v1.py",
    "tests/test_capability_expansion_layout_freeze_v1.py",
    "tests/test_desktop_shortcut.py",
    "tests/test_hud_source_frozen_selection_v1.py",
    "tests/test_google_workspace_host_v1.py",
    "tests/test_onyx_live_activation_google_workspace_v1.py",
    "tests/test_onyx_hud_current_acceptance_v46.py",
    "tests/test_packaged_runtime_hud_contract_v15.py",
    "tests/test_release_workflow_transition_v95.py",
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
        raise RuntimeError("Release V94 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v95",
        "issued_at": "2026-09-04T23:20:00-04:00",
        "logical_sequence": 95,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V95\0")
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
