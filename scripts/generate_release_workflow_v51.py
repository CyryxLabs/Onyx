"""Generate the additive Release V51 exact-qualification transition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v50.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v51.json"
PREDECESSOR_SHA256 = (
    "b300c424f9d816b6c6061917882c61a07cfcff72496ea3f98539c93805be1814"
)
ISSUED_AT = "2026-08-11T12:42:00-04:00"
LOGICAL_SEQUENCE = 51
ADDITIONAL_PATHS = (
    ".github/workflows/release-qualification.yml",
    "docs/onyx/FINAL_EVIDENCE_REVIEW_PROTOCOL.md",
    "docs/onyx/FORMAL_RELEASE_CONTRACT.md",
    "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V11.json",
    "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V12.json",
    "scripts/generate_final_qualification_provenance_v1.py",
    "scripts/check_release_eligibility.py",
    "scripts/generate_phase5_current_successor_transition_v51.py",
    "scripts/generate_release_sbom.py",
    "scripts/generate_release_workflow_v51.py",
    "scripts/linux_lifecycle_validation.py",
    "scripts/macos_lifecycle_validation.py",
    "scripts/prepare_qualification_artifacts_v1.py",
    "scripts/run_linux_deb_clean_install_validation.sh",
    "scripts/verify_v19_pytest_collection.py",
    "scripts/verify_final_release_qualification_v1.py",
    "scripts/verify_source_freeze_v1.py",
    "scripts/windows_lifecycle_validation.py",
    "scripts/windows_native_eligibility.py",
    "tests/fixtures/phase5_current_successor_transition_v51.json",
    "tests/test_final_release_qualification_v1.py",
    "tests/test_formal_release_contract_v1.py",
    "tests/test_current_successor_retirement_v11.py",
    "tests/test_current_successor_retirement_v12.py",
    "tests/test_freeze_release_source_v51.py",
    "tests/test_phase5_current_successor_transition_v51.py",
    "tests/test_release_qualification_artifacts_v1.py",
    "tests/test_release_workflow_transition_v51.py",
    "tests/test_verify_source_freeze_v1.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V50 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v50"
        or predecessor.get("logical_sequence") != 50
    ):
        raise RuntimeError("Release V50 predecessor contract drifted")
    current_paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *ADDITIONAL_PATHS,
        }
    )
    entries = [
        {"path": relative, "sha256": sha256(ROOT / relative)}
        for relative in current_paths
    ]
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v51",
        "issued_at": ISSUED_AT,
        "logical_sequence": LOGICAL_SEQUENCE,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256()
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V51\0")
    frame(digest, record["issued_at"])
    frame(digest, str(record["logical_sequence"]))
    frame(digest, record["predecessor"]["path"])
    frame(digest, record["predecessor"]["sha256"])
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
    print(
        json.dumps(
            {
                "fixture_sha256": sha256(TARGET),
                "root_sha256": result["current_root_sha256"],
                "paths": len(result["current_release_paths"]),
            },
            sort_keys=True,
        )
    )
