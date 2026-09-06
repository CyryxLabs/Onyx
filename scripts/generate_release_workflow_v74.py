"""Generate packaged-parity Release V74 over immutable V73."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v73.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v74.json"
PREDECESSOR_SHA256 = "fb22c460f153782af60a300cf3973507b54f04946351e5142826c3a98132a7a0"
CURRENT_CLOSURE_PATHS = (
    "core/assistant_identity_profile_v1.py",
    "core/capability_parity_v1.py",
    "core/social_content_strategy_v1.py",
    "core/spoken_language_memory_v1.py",
    "core/version.py",
    "packaging/onyx.spec",
    "scripts/bootstrap_onyx.pyw",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v74.py",
    "scripts/onyx_identity_cli.py",
    "scripts/onyx_parity_cli.py",
    "tests/test_assistant_identity_profile_v1.py",
    "tests/test_capability_parity_v1.py",
    "tests/test_packaged_parity_smoke_v1.py",
    "tests/test_release_workflow_transition_v74.py",
    "tests/test_social_content_strategy_v1.py",
    "tests/test_spoken_language_memory_v1.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V73 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v74",
        "issued_at": "2026-09-01T20:30:00-04:00",
        "logical_sequence": 74,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V74\0")
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
