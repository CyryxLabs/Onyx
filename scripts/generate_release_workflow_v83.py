"""Generate current-upstream parity Release V83 over immutable V82."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v82.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v83.json"
PREDECESSOR_SHA256 = "0a34cd398d0af9db6cfbf66af8feb59aa306a2b12aaa34595f0466572cef4c34"
CURRENT_CLOSURE_PATHS = (
    "core/capability_parity_v1.py",
    "core/version.py",
    "docs/onyx/ONYX_FUNCTIONAL_PARITY_V1.md",
    "docs/stories/ONYX-MARK-LII-OPERATIONAL-PARITY-V1.story.md",
    "packaging/onyx.spec",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v83.py",
    "tests/test_capability_parity_v1.py",
    "tests/test_release_workflow_transition_v83.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V82 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v83",
        "issued_at": "2026-09-02T18:35:00-04:00",
        "logical_sequence": 83,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V83\0")
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
