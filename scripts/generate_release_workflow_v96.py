"""Generate shortcut-bootstrap recovery Release V96 over immutable V95."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v95.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v96.json"
PREDECESSOR_SHA256 = "63d84c702535998084554d9647dd06178663b60ca5c21fb858ab8058ae3b4b3e"
CURRENT_CLOSURE_PATHS = (
    "core/graph_refresh_vault_v2.py",
    "core/phase8_microsoft_graph_oauth_v2.py",
    "core/dayops_graph_factory_v1.py",
    "core/dayops_connection_v19.py",
    "tests/test_graph_refresh_v2.py",
    "docs/onyx/INTEGRATION_GRAPH_LIVE_20260905.md",
    "docs/onyx/GUARDIAN_FFMPEG_REVIEW_FIXES_V1.md",
    "core/ffmpeg_runtime_v1.py",
    "tests/test_ffmpeg_runtime_v1.py",
    "tests/test_sysmetrics_com_lifecycle_v1.py",
    "core/social_official_adapter_v1.py",
    "scripts/onyx_social_cli.py",
    "tests/test_social_official_adapter_v1.py",
    "tests/test_social_official_host_v1.py",
    "tests/test_social_bootstrap_v1.py",
    "docs/onyx/SOCIAL_OFFICIAL_ADAPTER_V1.md",
    "docs/onyx/SYSMETRICS_COM_LIFECYCLE_V1_EVIDENCE.md",
    "core/network_guardian_v1.py",
    "tests/test_network_guardian_v1.py",
    "tests/test_humanoid_promotion_v47.py",
    "tests/test_mobile_humanoid_parity_v1.py",
    "tests/test_mission_memory_subprocess_v1.py",
    "dashboard/server.py",
    "dashboard/static/app.html",
    "packaging/onyx.spec",
    "scripts/package_hygiene.py",
    "core/onyx_hud_orb_v17.py",
    "core/onyx_hud_current_acceptance_v47.py",
    "core/onyx_packaged_runtime_hud_contract_v16.py",
    "core/onyx_packaged_runtime_hud_contract_v16.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V47-E6-001.manifest.json",
    "qml/OnyxLiveShellV16.qml",
    "qml/components/OnyxHumanoidEntityV13.qml",
    "qml/web/onyx-humanoid-three-v4.html",
    "qml/web/onyx-humanoid-three-v5.html",
    "tests/test_humanoid_transparency_v1.py",
    "docs/stories/ONYX-AGENT-EMPLOYEE-TWO-SPRINTS-V1.story.md",
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
    "scripts/generate_release_workflow_v96.py",
    "scripts/launch_onyx_live_google_workspace_v1.pyw",
    "tests/test_bootstrap_empty_windows_argument_v1.py",
    "tests/test_capability_expansion_layout_freeze_v1.py",
    "tests/test_desktop_shortcut.py",
    "tests/test_hud_source_frozen_selection_v1.py",
    "tests/test_google_workspace_host_v1.py",
    "tests/test_onyx_live_activation_google_workspace_v1.py",
    "tests/test_onyx_hud_current_acceptance_v46.py",
    "tests/test_packaged_runtime_hud_contract_v15.py",
    "tests/test_release_workflow_transition_v96.py",
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
        raise RuntimeError("Release V95 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v96",
        "issued_at": "2026-09-05T02:00:00-04:00",
        "logical_sequence": 96,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V96\0")
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
