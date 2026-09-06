"""Prepare V97 source authority without rewriting V96 or certifying operation."""

import json
from pathlib import Path

from scripts.generate_release_workflow_v96 import sha256
from scripts.verify_release_workflow_v70 import _root
from scripts.verify_release_workflow_v96 import V96_SHA256

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v96.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v97.json"
ADDITIONS = (
    "scripts/generate_release_workflow_v97.py",
    "tests/test_release_workflow_transition_v97.py",
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
    if sha256(PREDECESSOR) != V96_SHA256:
        raise RuntimeError("V96 predecessor changed")
    old = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted({*(row["path"] for row in old["current_release_paths"]), *ADDITIONS})
    record = {
        "schema": "onyx.release-workflow-transition.v97",
        "issued_at": "2026-09-05T19:42:01+00:00", "logical_sequence": 97,
        "predecessor": {"path": PREDECESSOR.relative_to(ROOT).as_posix(), "sha256": V96_SHA256},
        "policy": old["policy"],
        "current_release_paths": [{"path": path, "sha256": sha256(ROOT / path)} for path in paths],
        "current_root_sha256": "",
    }
    record["current_root_sha256"] = _root(record, 97)
    encoded = json.dumps(record, separators=(",", ":")) + "\n"
    if TARGET.exists():
        if TARGET.read_text(encoding="utf-8") != encoded:
            raise RuntimeError("V97 already exists with different bytes; create a successor")
    else:
        with TARGET.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
    return {"sha256": sha256(TARGET), "root_sha256": record["current_root_sha256"], "paths": len(paths)}


if __name__ == "__main__":
    print(json.dumps(generate()))
