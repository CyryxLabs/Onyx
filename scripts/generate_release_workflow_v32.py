"""Generate the acyclic Release V32 transition over immutable V31."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v31.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v32.json"
CURRENT_PATHS = (
    "scripts/generate_release_workflow_v32.py",
    "scripts/verify_phase5_exit_retirement_v1.py",
    "scripts/verify_release_runtime_closure_v1.py",
    "tests/test_release_workflow_transition_v31.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    entries = [
        {"path": relative, "sha256": sha256(ROOT / relative)}
        for relative in CURRENT_PATHS
    ]
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v32",
        "issued_at": "2026-08-05T09:10:00-04:00",
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": sha256(PREDECESSOR),
        },
        "policy": {
            "predecessor_is_immutable": True,
            "historical_hashes_are_rebound": False,
            "current_release_paths_are_sha256_bound": True,
            "unsigned_windows_may_be_formal": False,
            "diagnostic_candidates_may_be_published": False,
        },
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256()
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V32\0")
    predecessor = record["predecessor"]
    frame(digest, predecessor["path"])
    frame(digest, predecessor["sha256"])
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
    print(json.dumps({
        "fixture_sha256": sha256(TARGET),
        "root_sha256": result["current_root_sha256"],
        "paths": len(result["current_release_paths"]),
    }, sort_keys=True))
