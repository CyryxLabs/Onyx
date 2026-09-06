from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_final_release_qualification_v1 import (
    FinalReleaseQualificationError,
    REQUIRED_LIFECYCLE_GATES,
    verify_final_release_qualification,
)


VERSION = "1.2.3"
BUILD_RUN_ID = "118"
QUALIFICATION_RUN_ID = "119"
BUILD_SHA = "b" * 40
QUALIFICATION_SHA = "c" * 40
TARGET = "Windows-x64"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8", newline="\n")


def _fixture(root: Path) -> None:
    setup = root / f"Onyx-{VERSION}-Windows-x64-Setup.exe"
    portable = root / f"Onyx-{VERSION}-Windows-x64-Portable.zip"
    setup.write_bytes(b"signed-setup")
    portable.write_bytes(b"signed-portable")
    setup_sha = hashlib.sha256(setup.read_bytes()).hexdigest()
    portable_sha = hashlib.sha256(portable.read_bytes()).hexdigest()
    manifest = {
        "system": "Windows",
        "architecture": "x64",
        "version": VERSION,
        "release_class": "formal",
        "diagnostic_exceptions": [],
        "bundle_inventory": {"bundle_root_sha256": "b" * 64},
        "artifacts": [
            {"name": setup.name, "size": setup.stat().st_size, "sha256": setup_sha},
            {
                "name": portable.name,
                "size": portable.stat().st_size,
                "sha256": portable_sha,
            },
        ],
    }
    manifest_path = root / f"release-manifest-{TARGET}.json"
    _write(manifest_path, manifest)
    sbom = root / "SBOM-Windows-x64.spdx.json"
    sbom.write_bytes(b"technical-sbom")
    aggregate_sbom = root / "SBOM.spdx.json"
    aggregate_sbom.write_bytes(b"aggregate-technical-sbom")
    aggregate_sha = hashlib.sha256(aggregate_sbom.read_bytes()).hexdigest()
    aggregate_digest = root / "SBOM.spdx.json.sha256"
    aggregate_digest.write_text(
        f"{aggregate_sha}  SBOM.spdx.json\n", encoding="utf-8", newline="\n"
    )
    events = [{"gate": gate} for gate in REQUIRED_LIFECYCLE_GATES]
    lifecycle = {
        "contract": "onyx.windows-lifecycle-evidence.v1",
        "host": {"system": "Windows", "architecture": "AMD64"},
        "current": {
            "version": VERSION,
            "sha256": setup_sha,
            "signature": {"status": "Valid", "thumbprint": "A" * 40},
        },
        "prior": {"version": "1.2.2", "sha256": "d" * 64},
        "events": events,
        "final_app_removed": True,
        "final_registry_removed": True,
        "final_owner_data_preserved": True,
    }
    _write(root / f"lifecycle-evidence-{TARGET}.json", lifecycle)
    long_session = {
        "contract": "OnyxWindowsLongSession.v1",
        "candidate": f"Onyx-{VERSION}-formal",
        "status": "passed",
        "executable_sha256": "e" * 64,
        "duration_required_seconds": 28_800,
        "duration_observed_seconds": 28_800.5,
        "sample_interval_seconds": 60,
        "sample_count": 480,
        "full_duration": True,
        "alive_at_update": True,
        "all_responsive": True,
        "average_whole_host_cpu_pct": 0.3,
        "maximum_working_set_bytes": 400_000_000,
        "maximum_private_memory_bytes": 1_100_000_000,
        "working_set_growth_bytes": 0,
        "application_error_count": 0,
        "failure_reason": None,
        "artifacts": {
            "setup_sha256": setup_sha,
            "portable_sha256": portable_sha,
            "bundle_root_sha256": "b" * 64,
            "source_transition_sha256": "f" * 64,
            "sbom_sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
        },
        "thresholds": {
            "average_whole_host_cpu_pct": 1.5,
            "maximum_working_set_bytes": 786_432_000,
            "maximum_private_memory_bytes": 1_610_612_736,
            "maximum_working_set_growth_bytes": 268_435_456,
            "maximum_application_errors": 0,
            "require_all_responsive": True,
        },
        "process_left_running": True,
    }
    _write(root / f"long-session-evidence-{TARGET}.json", long_session)
    _write(
        root / "final-qualification-provenance.json",
        {
            "aggregate_sbom": {
                "digest_name": aggregate_digest.name,
                "digest_sha256": hashlib.sha256(
                    aggregate_digest.read_bytes()
                ).hexdigest(),
                "name": aggregate_sbom.name,
                "sha256": aggregate_sha,
            },
            "build": {"run_id": BUILD_RUN_ID, "workflow_sha": BUILD_SHA},
            "contract": "onyx.final-qualification-provenance.v1",
            "manifests": [
                {
                    "name": manifest_path.name,
                    "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    "target": TARGET,
                }
            ],
            "qualification": {
                "run_id": QUALIFICATION_RUN_ID,
                "workflow_sha": QUALIFICATION_SHA,
            },
            "targets": [TARGET],
            "version": VERSION,
        },
    )


def _verify(root: Path) -> dict[str, object]:
    return verify_final_release_qualification(
        release_dir=root,
        version=VERSION,
        required_targets=(TARGET,),
        build_run_id=BUILD_RUN_ID,
        build_sha=BUILD_SHA,
        qualification_run_id=QUALIFICATION_RUN_ID,
        qualification_sha=QUALIFICATION_SHA,
        independent_review_approval="true",
        independent_review_reference=(
            f"https://github.com/CyryxLabs/Onyx/actions/runs/{QUALIFICATION_RUN_ID}"
        ),
    )


def test_final_qualification_passes_exact_lifecycle_soak_and_review(tmp_path: Path) -> None:
    _fixture(tmp_path)
    result = _verify(tmp_path)
    assert result["lifecycle_passed"] is True
    assert result["windows_long_session_passed"] is True
    assert result["independent_review_approved"] is True


def test_missing_lifecycle_and_soak_fail_closed(tmp_path: Path) -> None:
    _fixture(tmp_path)
    (tmp_path / f"lifecycle-evidence-{TARGET}.json").unlink()
    (tmp_path / f"long-session-evidence-{TARGET}.json").unlink()
    with pytest.raises(FinalReleaseQualificationError) as caught:
        _verify(tmp_path)
    assert f"missing {TARGET} lifecycle evidence" in str(caught.value)
    assert f"missing {TARGET} long-session evidence" in str(caught.value)


def test_tampered_artifact_binding_and_nonterminal_soak_fail_closed(tmp_path: Path) -> None:
    _fixture(tmp_path)
    lifecycle_path = tmp_path / f"lifecycle-evidence-{TARGET}.json"
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    lifecycle["current"]["sha256"] = "0" * 64
    _write(lifecycle_path, lifecycle)
    soak_path = tmp_path / f"long-session-evidence-{TARGET}.json"
    soak = json.loads(soak_path.read_text(encoding="utf-8"))
    soak["status"] = "in_progress"
    soak["full_duration"] = False
    _write(soak_path, soak)
    (tmp_path / f"Onyx-{VERSION}-Windows-x64-Setup.exe").write_bytes(b"tampered")
    with pytest.raises(FinalReleaseQualificationError) as caught:
        _verify(tmp_path)
    message = str(caught.value)
    assert "current artifact binding drifted" in message
    assert "exact primary artifact bytes drifted" in message
    assert "terminal pass contract is absent" in message


def test_independent_review_must_bind_same_workflow(tmp_path: Path) -> None:
    _fixture(tmp_path)
    with pytest.raises(FinalReleaseQualificationError) as caught:
        verify_final_release_qualification(
            release_dir=tmp_path,
            version=VERSION,
            required_targets=(TARGET,),
            build_run_id=BUILD_RUN_ID,
            build_sha=BUILD_SHA,
            qualification_run_id=QUALIFICATION_RUN_ID,
            qualification_sha=QUALIFICATION_SHA,
            independent_review_approval="false",
            independent_review_reference="https://github.com/CyryxLabs/Onyx/actions/runs/999",
        )
    message = str(caught.value)
    assert "independent final evidence review is not approved" in message
    assert "independent review durable workflow reference is absent" in message


def test_aggregate_sbom_must_be_the_exact_qualified_bytes(tmp_path: Path) -> None:
    _fixture(tmp_path)
    (tmp_path / "SBOM.spdx.json").write_bytes(b"publish-time-regeneration")
    with pytest.raises(FinalReleaseQualificationError, match="aggregate SBOM binding"):
        _verify(tmp_path)


def test_publish_workflow_is_fail_closed_on_final_qualification() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/release-packages.yml"
    ).read_text(encoding="utf-8")
    for token in (
        "name: onyx-public-release",
        "publish_qualified",
        "qualified_build_run_id",
        "qualification_run_id",
        "onyx-final-qualification-evidence",
        "onyx-formal-sbom",
        "qualified build contains an unexpected artifact set",
        "scripts.verify_final_release_qualification_v1",
        "ONYX_INDEPENDENT_REVIEW_APPROVED",
        "lifecycle, soak and independent-review qualification",
    ):
        assert token in workflow
    assert workflow.index("scripts.verify_final_release_qualification_v1") < (
        workflow.index('gh release view "$RELEASE_TAG"')
    )
    assert "Generate exact technical SPDX inventory" not in workflow[
        workflow.index("  publish:") :
    ]


def test_qualification_workflow_requires_native_lifecycle_soak_and_review() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/release-qualification.yml"
    ).read_text(encoding="utf-8")
    for token in (
        "onyx-ephemeral",
        "build run contains an unexpected artifact set",
        "qualification run contains an unexpected artifact set",
        "scripts.windows_lifecycle_validation",
        "scripts.macos_lifecycle_validation",
        "scripts.linux_lifecycle_validation",
        "scripts.monitor_windows_long_session",
        "--duration 28800",
        "name: onyx-final-evidence-review",
        "final-qualification-provenance.json",
        "onyx-final-qualification-evidence",
    ):
        assert token in workflow
    assert workflow.index("--duration 28800") < workflow.index(
        "onyx-final-qualification-evidence"
    )
