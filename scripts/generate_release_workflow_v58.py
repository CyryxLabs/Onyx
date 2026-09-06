"""Generate additive Release V58 for the V4/V35 runtime closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v57.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v58.json"
PREDECESSOR_SHA256 = "7b866cac1987c43466d00118c1a81dc3761c307ec6455d51a9f46a01b1b0e16d"
CURRENT_CLOSURE_PATHS = (
    "core/onyx_hud_current_acceptance_v35.py",
    "core/onyx_packaged_runtime_hud_contract_v4.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v4.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V35-E6-001.manifest.json",
    "packaging/onyx.spec",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v58.py",
    "scripts/package_hygiene.py",
    "tests/test_onyx_hud_current_acceptance_v35.py",
    "tests/test_packaged_runtime_hud_contract_v4.py",
    "tests/test_release_workflow_transition_v58.py",
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
        raise RuntimeError("Release V57 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted({*(entry["path"] for entry in predecessor["current_release_paths"]), *CURRENT_CLOSURE_PATHS})
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v58",
        "issued_at": "2026-08-23T20:00:00-04:00",
        "logical_sequence": 58,
        "predecessor": {"path": PREDECESSOR.relative_to(ROOT).as_posix(), "sha256": PREDECESSOR_SHA256},
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V58\0")
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
