"""Generate governed continuous-intelligence Release V87 over immutable V86."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v86.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v87.json"
PREDECESSOR_SHA256 = "18bf445b1e40d213efaa46f82a16d48f8838c7b6702fc2efbbc0284ef6a2c5ed"
CURRENT_CLOSURE_PATHS = (
    "core/aexos_department_router_v1.py",
    "core/aexos_engine_adapter_v1.py",
    "core/capability_expansion_runtime_v1.py",
    "core/capability_expansion_service_v1.py",
    "core/continuous_learning_v1.py",
    "core/governed_personalization_v1.py",
    "core/opportunity_economics_v1.py",
    "core/opportunity_queue_v1.py",
    "core/permission_broker.py",
    "core/version.py",
    "core/web_opportunity_research_v1.py",
    "docs/onyx/ONYX_CONTINUOUS_INTELLIGENCE_V1.md",
    "docs/stories/ONYX-CL-01-CONTINUOUS-LEARNING-ONBOARDING-V1.story.md",
    "docs/stories/ONYX-CL-02-AEXOS-DEPARTMENTAL-AUTONOMY-V1.story.md",
    "docs/stories/ONYX-CL-03-OPPORTUNITY-INTELLIGENCE-ECONOMICS-V1.story.md",
    "docs/stories/ONYX-CONTINUOUS-INTELLIGENCE-AUTONOMY-V1.epic.md",
    "main.py",
    "packaging/onyx.spec",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v87.py",
    "scripts/onyx_agentic_cli.py",
    "scripts/onyx_learning_cli.py",
    "tests/test_aexos_department_router_v1.py",
    "tests/test_aexos_engine_adapter_v1.py",
    "tests/test_continuous_learning_v1.py",
    "tests/test_opportunity_economics_v1.py",
    "tests/test_opportunity_queue_v1.py",
    "tests/test_regressions.py",
    "tests/test_release_workflow_transition_v87.py",
    "tests/test_web_opportunity_research_v1.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V86 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v87",
        "issued_at": "2026-09-04T12:13:53-04:00",
        "logical_sequence": 87,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V87\0")
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
