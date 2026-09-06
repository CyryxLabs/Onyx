"""Generate the acyclic Release V47 transition over immutable V46."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v46.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v47.json"
PREDECESSOR_SHA256 = (
    "e9c25fb4716a511b28e58f4c6d9dd492db9dd242673dd580082725f423238261"
)
ISSUED_AT = "2026-08-11T01:50:00-04:00"
LOGICAL_SEQUENCE = 47
CURRENT_PATHS = (
    ".github/workflows/release-packages.yml",
    "core/google_workspace_connector_v1.py",
    "core/onyx_hud_current_acceptance_v30.py",
    "core/onyx_hud_orb_v11.py",
    "core/onyx_live_activation_google_workspace_v1.py",
    "core/onyx_packaged_runtime_hud_contract_v1.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v1.py",
    "docs/onyx/CURRENT_RELEASE_STATUS.md",
    "docs/onyx/LEGAL_RELEASE_APPROVAL_1.1.9.md",
    "docs/onyx/THIRD_PARTY_LICENSE_REVIEW_WORKLIST_1.1.9.md",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V30-E6-001.manifest.json",
    "docs/onyx/checkpoints/CURRENT_RUFF_SECURITY_EXCEPTIONS_V1.json",
    "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V9.json",
    "main.py",
    "packaging/onyx.spec",
    "qml/OnyxLiveShellGuardedV1.qml",
    "qml/OnyxLiveShellV11.qml",
    "qml/OnyxLiveShellV7.qml",
    "qml/components/OnyxOrbEntityV7.qml",
    "qml/components/OnyxOrbEntityV8.qml",
    "requirements-dev.txt",
    "requirements.lock",
    "requirements.txt",
    "ruff.toml",
    "scripts/bootstrap_onyx_live_google_workspace_v1.pyw",
    "scripts/build_release.py",
    "scripts/freeze_release_source.py",
    "scripts/generate_hud_v30_manifests.py",
    "scripts/generate_phase5_current_successor_transition_v47.py",
    "scripts/generate_release_workflow_v47.py",
    "scripts/launch_onyx_live_google_workspace_v1.pyw",
    "scripts/missing_distribution_license_bundle.py",
    "scripts/package_hygiene.py",
    "scripts/primp_license_bundle.py",
    "scripts/verify_current_successor_retirement_v1.py",
    "scripts/verify_phase5_exit_retirement_v1.py",
    "tests/fixtures/phase5_current_successor_transition_v47.json",
    "tests/test_cinematic_operations_hud_v1.py",
    "tests/test_close_to_background_v1.py",
    "tests/test_current_release_documentation_v46.py",
    "tests/test_current_release_documentation_v47.py",
    "tests/test_current_successor_retirement_v9.py",
    "tests/test_freeze_release_source_v47.py",
    "tests/test_hud_source_frozen_selection_v1.py",
    "tests/test_macos_release_pipeline_v1.py",
    "tests/test_missing_distribution_license_bundle_v1.py",
    "tests/test_native_release_gate_v1.py",
    "tests/test_onyx_hud_accessibility_stability_v1.py",
    "tests/test_onyx_hud_current_acceptance_v30.py",
    "tests/test_onyx_live_activation_google_workspace_v1.py",
    "tests/test_onyx_live_activation_v24.py",
    "tests/test_package_hygiene_v1.py",
    "tests/test_packaged_runtime_hud_contract_v1.py",
    "tests/test_phase5_current_successor_transition_v47.py",
    "tests/test_primp_license_bundle_v1.py",
    "tests/test_ruff_historical_immutable_ignores.py",
    "ui.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V46 predecessor digest drifted")
    entries = [
        {"path": relative, "sha256": sha256(ROOT / relative)}
        for relative in CURRENT_PATHS
    ]
    if [entry["path"] for entry in entries] != sorted(
        entry["path"] for entry in entries
    ):
        raise RuntimeError("Release V47 paths must remain sorted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("schema") != "onyx.release-workflow-transition.v46":
        raise RuntimeError("Release V46 predecessor contract drifted")
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v47",
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
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V47\0")
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
