"""Generate additive Release V55 after the V33 package-hygiene successor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v54.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v55.json"
PREDECESSOR_SHA256 = "c56bc179a032e5b0f94905b040e37aca8dd27413205c608b58f33eca5e6da739"
ADDITIONAL_PATHS = (
    "core/onyx_hud_current_acceptance_v33.py",
    "core/onyx_packaged_runtime_hud_contract_v2.py",
    "core/onyx_packaged_runtime_hud_contract_v2.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V33-E6-001.manifest.json",
    "scripts/generate_hud_v33_manifests.py",
    "scripts/generate_packaged_runtime_hud_contract_v2.py",
    "scripts/generate_release_workflow_v55.py",
    "scripts/package_hygiene.py",
    "scripts/verify_packaged_runtime_hud_contract_v2.py",
    "tests/test_onyx_hud_current_acceptance_v33.py",
    "tests/test_package_hygiene_v1.py",
    "tests/test_packaged_runtime_hud_contract_v2.py",
    "tests/test_release_workflow_transition_v55.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V54 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted({*(entry["path"] for entry in predecessor["current_release_paths"]), *ADDITIONAL_PATHS})
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {"schema": "onyx.release-workflow-transition.v55", "issued_at": "2026-08-23T17:00:00-04:00", "logical_sequence": 55, "predecessor": {"path": PREDECESSOR.relative_to(ROOT).as_posix(), "sha256": PREDECESSOR_SHA256}, "policy": predecessor["policy"], "current_release_paths": entries, "current_root_sha256": ""}
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V55\0")
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
