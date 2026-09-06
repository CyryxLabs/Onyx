"""Generate mobile-humanoid and current-test Release V81 over immutable V80."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v80.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v81.json"
PREDECESSOR_SHA256 = "35bdfed6a1999291897b63a921c6653991da9e3dee75efc73b51ee4ae48e96ce"
CURRENT_CLOSURE_PATHS = (
    "core/version.py",
    "dashboard/server.py",
    "dashboard/static/app.html",
    "docs/stories/ONYX-MOBILE-HUMANOID-AST-SIGNING-V1.story.md",
    "packaging/onyx.spec",
    "scripts/generate_release_workflow_v81.py",
    "tests/conftest.py",
    "tests/test_mobile_humanoid_parity_v1.py",
    "tests/test_release_workflow_transition_v81.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V80 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v81",
        "issued_at": "2026-09-02T17:20:00-04:00",
        "logical_sequence": 81,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V81\0")
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
