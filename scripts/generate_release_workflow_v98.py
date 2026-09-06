"""Prepare V98 source authority without rewriting V97 or certifying operation."""

import json
from pathlib import Path

from scripts.generate_release_workflow_v97 import sha256
from scripts.verify_release_workflow_v70 import _root
from scripts.verify_release_workflow_v97 import V97_SHA256

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v97.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v98.json"
ADDITIONS = (
    "core/capability_expansion_runtime_v1.py",
    "core/capability_expansion_service_v1.py",
    "core/plugin_runtime_v1.py",
    "core/plugin_docker_sandbox_v1.py",
    "core/capability_ports/plugin_v1.py",
    "core/governed_capability_host_v1.py",
    "core/governance_nucleus_v1.py",
    "tests/test_plugin_cancellation_v1.py",
    "tests/test_governance_nonce_compatibility_v1.py",
    "tests/test_governance_nucleus_v1.py",
    "docs/onyx/V98_SOURCE_REMEDIATION_20260905.md",
    "tests/fixtures/release_workflow_transition_v97.json",
    "scripts/verify_release_workflow_v97.py",
    "core/onyx_hud_current_acceptance_v48.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V48-E6-001.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v17.py",
    "core/onyx_packaged_runtime_hud_contract_v17.manifest.json",
    "tests/test_hud_conversation_successor_v48.py",
    "tests/test_conversation_projection_v1.py",
    "scripts/generate_advanced_operations_source_acceptance_v24.py",
    "scripts/verify_advanced_operations_source_acceptance_v24.py",
    "docs/onyx/acceptance/VE-ADVANCED-OPS-V24-001.manifest.json",
    "tests/test_advanced_operations_source_acceptance_v24.py",
    "tests/conftest.py",

    "scripts/generate_release_workflow_v98.py",
    "tests/test_release_workflow_transition_v98.py",
    "memory/obsidian_v1.py", "memory/second_brain_config_v1.py",
    "memory/memory_manager.py", "core/deals_v1.py", "core/phone_brief_v1.py",
    "core/permission_broker.py", "core/readiness.py", "core/readiness_probe.py",
    "core/live_voice_continuity_v1.py", "main.py",
    "tests/test_obsidian_v1.py", "tests/test_second_brain_config_v1.py",
    "tests/test_deals_v1.py", "tests/test_phone_brief_v1.py",
    "tests/test_readiness.py", "tests/test_live_audio_stream_ownership_v1.py",
    "docs/onyx/GO_SINGLE_SPRINT_20260905.md",
    "docs/onyx/SECOND_BRAIN_PHONE_STATUS_20260905.md",
    "docs/stories/ONYX-SECOND-BRAIN-PHONE-TWO-SPRINTS-V1.story.md",
)


def generate():
    if sha256(PREDECESSOR) != V97_SHA256:
        raise RuntimeError("V97 predecessor changed")
    old = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted({*(row["path"] for row in old["current_release_paths"]), *ADDITIONS})
    record = {
        "schema": "onyx.release-workflow-transition.v98",
        "issued_at": "2026-09-05T20:11:00+00:00", "logical_sequence": 98,
        "predecessor": {"path": PREDECESSOR.relative_to(ROOT).as_posix(), "sha256": V97_SHA256},
        "policy": old["policy"],
        "current_release_paths": [{"path": path, "sha256": sha256(ROOT / path)} for path in paths],
        "current_root_sha256": "",
    }
    record["current_root_sha256"] = _root(record, 98)
    encoded = json.dumps(record, separators=(",", ":")) + "\n"
    if TARGET.exists():
        if TARGET.read_text(encoding="utf-8") != encoded:
            raise RuntimeError("V98 already exists with different bytes; create a successor")
    else:
        with TARGET.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
    return {"sha256": sha256(TARGET), "root_sha256": record["current_root_sha256"], "paths": len(paths)}


if __name__ == "__main__":
    print(json.dumps(generate()))
