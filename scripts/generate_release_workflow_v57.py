"""Generate additive Release V57 for the current runtime closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v56.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v57.json"
PREDECESSOR_SHA256 = "381ad6b56ae33cd81237e70dc4870c56b966d999574e8dcff298d77aec165bbf"
CURRENT_CLOSURE_PATHS = (
    "core/onyx_hud_current_acceptance_v34.py",
    "core/onyx_packaged_runtime_hud_contract_v3.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v3.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V34-E6-001.manifest.json",
    "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V16.json",
    "scripts/generate_release_workflow_v57.py",
    "scripts/verify_current_successor_retirement_v16.py",
    "tests/test_current_successor_retirement_v16.py",
    "tests/test_onyx_hud_current_acceptance_v34.py",
    "tests/test_packaged_runtime_hud_contract_v3.py",
    "tests/test_release_workflow_transition_v57.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V56 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v57",
        "issued_at": "2026-08-23T19:00:00-04:00",
        "logical_sequence": 57,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V57\0")
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
