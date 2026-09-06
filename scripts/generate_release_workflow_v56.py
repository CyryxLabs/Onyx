"""Generate additive Release V56 for exact capability runtime closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v55.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v56.json"
PREDECESSOR_SHA256 = "161b84b2c7bbb607d6221219037d665889c3579cd395417955e1ff727f093584"
AUTHORITY_PATHS = (
    "core/capability_composition_v1.py",
    "core/capability_ports/__init__.py",
    "core/capability_ports/argos_v1.py",
    "core/capability_ports/budget_v1.py",
    "core/capability_ports/command_center_v1.py",
    "core/capability_ports/evidence_v1.py",
    "core/capability_ports/google_workspace_v1.py",
    "core/capability_ports/graph_v1.py",
    "core/capability_ports/guild_v1.py",
    "core/capability_ports/intelligence_v1.py",
    "core/capability_ports/knowledge_refinery_v1.py",
    "core/capability_ports/mission_context_v1.py",
    "core/capability_ports/model_router_v1.py",
    "core/capability_ports/nexus_v1.py",
    "core/capability_ports/plugin_v1.py",
    "core/capability_ports/project_execution_v1.py",
    "core/capability_ports/social_v1.py",
    "core/capability_ports/strategy_v1.py",
    "core/capability_ports/unified_router_v1.py",
    "core/capability_ports/workspace_v1.py",
    "core/governed_capability_host_v1.py",
    "scripts/onyx_capabilities_cli.py",
)
ADDITIONAL_PATHS = (
    *AUTHORITY_PATHS,
    "packaging/onyx.spec",
    "scripts/generate_release_workflow_v56.py",
    "scripts/package_hygiene.py",
    "scripts/verify_release_runtime_closure_v2.py",
    "tests/test_package_hygiene_v1.py",
    "tests/test_release_runtime_closure_v2.py",
    "tests/test_release_workflow_transition_v56.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V55 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *ADDITIONAL_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v56",
        "issued_at": "2026-08-23T18:00:00-04:00",
        "logical_sequence": 56,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V56\0")
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
        json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return record


if __name__ == "__main__":
    print(json.dumps(generate(), sort_keys=True))
