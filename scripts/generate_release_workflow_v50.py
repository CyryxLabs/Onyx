"""Generate the acyclic post-R10B Release V50 evidence transition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v49.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v50.json"
PREDECESSOR_SHA256 = (
    "7282fdb38d77607b58fceb965a0dac218629e8a4f1d0d2e995c27f31f8fabfad"
)
ISSUED_AT = "2026-08-11T10:45:00-04:00"
LOGICAL_SEQUENCE = 50
ADDITIONAL_PATHS = (
    "docs/onyx/DOCUMENTATION_INDEX.md",
    "docs/onyx/DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md",
    "docs/onyx/FINAL_EVIDENCE_INDEX_1.1.9.md",
    "docs/onyx/checkpoints/LEGAL_DECISION_PACKET_R10B_V1.json",
    "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_2026-08-04.md",
    "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V23_2026-08-04.md",
    "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V24_2026-08-04.md",
    "docs/onyx/operations/ONYX_1_1_9_V31_WINDOWS_ACCEPTANCE_2026-08-04.md",
    "docs/onyx/operations/ONYX_1_1_9_V41_LINUX_BUILD_FAILURE_2026-08-10.md",
    "docs/onyx/operations/ONYX_1_1_9_V41_SBOM_RECONCILIATION_2026-08-10.md",
    "docs/onyx/operations/ONYX_1_1_9_V41_WINDOWS_ACCEPTANCE_2026-08-10.md",
    "docs/stories/ONYX-REL-1.1.9.md",
    "scripts/generate_release_workflow_v50.py",
    "scripts/generate_phase5_current_successor_transition_v50.py",
    "scripts/verify_legal_decision_packet_r10b_v1.py",
    "scripts/monitor_windows_long_session.py",
    "scripts/reconcile_release_compliance_v1.py",
    "tests/test_current_release_documentation_r10b.py",
    "tests/fixtures/phase5_current_successor_transition_v50.json",
    "tests/test_monitor_windows_long_session.py",
    "tests/test_legal_decision_packet_r10b_v1.py",
    "tests/test_phase5_current_successor_transition_v50.py",
    "tests/test_release_compliance_reconciliation_v1.py",
    "tests/test_release_workflow_transition_v50.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V49 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v49"
        or predecessor.get("logical_sequence") != 49
    ):
        raise RuntimeError("Release V49 predecessor contract drifted")
    current_paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *ADDITIONAL_PATHS,
        }
    )
    entries = [
        {"path": relative, "sha256": sha256(ROOT / relative)}
        for relative in current_paths
    ]
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v50",
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
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V50\0")
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
