"""Generate complete current HUD retirement Release V66 over immutable V65."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v65.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v66.json"
PREDECESSOR_SHA256 = "c1e5009460ab129c08881710e287cc8aa6d093196ba8f228c72df531d109ddfa"
CURRENT_CLOSURE_PATHS = (
    "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V25.json",
    "scripts/build_release.py",
    "scripts/generate_current_successor_retirement_v25.py",
    "scripts/generate_release_workflow_v66.py",
    "scripts/verify_current_successor_retirement_v25.py",
    "scripts/verify_release_workflow_v65.py",
    "tests/conftest.py",
    "tests/test_current_successor_retirement_v25.py",
    "tests/test_release_workflow_transition_v66.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V65 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted({*(entry["path"] for entry in predecessor["current_release_paths"]), *CURRENT_CLOSURE_PATHS})
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v66",
        "issued_at": "2026-08-24T19:15:00-04:00",
        "logical_sequence": 66,
        "predecessor": {"path": PREDECESSOR.relative_to(ROOT).as_posix(), "sha256": PREDECESSOR_SHA256},
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V66\0")
    for value in (record["issued_at"], str(record["logical_sequence"]), record["predecessor"]["path"], record["predecessor"]["sha256"]):
        frame(digest, value)
    for entry in entries:
        frame(digest, entry["path"])
        frame(digest, entry["sha256"])
    record["current_root_sha256"] = digest.hexdigest()
    TARGET.write_text(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    return record


if __name__ == "__main__":
    print(json.dumps(generate(), sort_keys=True))
