"""Generate packaged-runtime Release V91 over immutable V90."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v90.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v91.json"
PREDECESSOR_SHA256 = "d0abf73f16ff8e960a3bd6eb868e03877d9d21d2143f0182b6ef5b9041a24df8"
CURRENT_CLOSURE_PATHS = (
    "core/version.py",
    "core/onyx_hud_current_acceptance_v44.py",
    "core/onyx_packaged_runtime_hud_contract_v13.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v13.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V44-E6-001.manifest.json",
    "docs/stories/ONYX-SETUP-QT-REENTRANCY-V1.story.md",
    "packaging/onyx.spec",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v91.py",
    "scripts/package_hygiene.py",
    "tests/test_onyx_hud_v5_live_integration.py",
    "tests/test_onyx_hud_current_acceptance_v44.py",
    "tests/test_packaged_runtime_hud_contract_v13.py",
    "tests/test_release_workflow_transition_v91.py",
    "ui.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V90 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v91",
        "issued_at": "2026-09-04T15:55:35-04:00",
        "logical_sequence": 91,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V91\0")
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
