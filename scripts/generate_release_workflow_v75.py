"""Generate live-qualification Release V75 over immutable V74."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v74.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v75.json"
PREDECESSOR_SHA256 = "28ee9c94ac978506c1fc0a67bf187188bf51a991208bb7921f184b4588213634"
CURRENT_CLOSURE_PATHS = (
    "core/capability_expansion_service_v1.py",
    "core/plugin_docker_sandbox_v1.py",
    "core/version.py",
    "docs/stories/ONYX-REL-1.1.11-PARITY-LIVE-SUCCESSOR-V1.story.md",
    "packaging/onyx.spec",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v75.py",
    "scripts/onyx_plugin_cli.py",
    "scripts/verify_original_voice_live.py",
    "tests/test_original_voice_contract_v1.py",
    "tests/test_plugin_docker_sandbox_v1.py",
    "tests/test_release_workflow_transition_v75.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V74 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v75",
        "issued_at": "2026-09-01T23:41:35-04:00",
        "logical_sequence": 75,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V75\0")
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
