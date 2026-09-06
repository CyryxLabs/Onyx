from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import verify_onyx_live_activation_v7_acceptance as acceptance


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def active_environment() -> dict[str, str]:
    result = dict(os.environ)
    for version in range(2, 8):
        result.pop(f"ONYX_LIVE_ACTIVATION_V{version}", None)
        result.pop(f"ONYX_LIVE_ROLLBACK_V{version}", None)
    result.update(
        {
            "ONYX_LIVE_ACTIVATION_V7": "1",
            "ONYX_OWNER_PROFILE_V8_LIVE": "1",
            "ONYX_HUD_V5_LIVE": "1",
            "ONYX_PHASE5_INTEGRATION_V3": "1",
            "ONYX_PHASE5_RUNTIME_V3": "1",
            "ONYX_PHASE5_GRANT_SHADOW_V3": "1",
            "ONYX_PHASE5_APPROVAL_INBOX_V3": "1",
            "ONYX_PHASE5_LOW_RISK_V3": "1",
            "ONYX_PHASE5_NEXUS_PROJECTION_V3": "1",
            "ONYX_PHASE5_LOCAL_CATALOG_READ_V3": "1",
            "ONYX_PHASE5_DASHBOARD_PROJECTION_V3": "1",
            "ONYX_PHASE5_PRINCIPAL_ID": "onyx-owner",
            "ONYX_PHASE5_WORKSPACE_ID": "onyx-local-workspace",
            "ONYX_PHASE5_ACCOUNT_ID": "cyryx-local-account",
            "ONYX_PHASE5_PROFILE_ID": "onyx-owner-profile",
            "PYTHONDONTWRITEBYTECODE": "1",
            "QT_QPA_PLATFORM": "offscreen",
            "QSG_RHI_BACKEND": "software",
        }
    )
    return result


def _pytest_count(files: tuple[str, ...], expected: int, temp_name: str) -> None:
    result = subprocess.run(
        [
            str(PYTHON),
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(ROOT / temp_name),
            *files,
        ],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=1200,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{expected} passed" in result.stdout


def test_external_acceptance_validates_exact_frozen_candidate():
    result = acceptance.verify()
    assert result["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert result["candidate_manifest_sha256"] == acceptance.MANIFEST_SHA256
    assert result["independent_root_sha256"] == acceptance.INDEPENDENT_ROOT_SHA256
    assert result["candidate_files"] == 19
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 2}
    assert result["focused"] == {"passed": 6, "failed": 0}
    assert result["v4_v7"] == {"passed": 31, "failed": 0}
    assert result["v2_v7"] == {"passed": 57, "failed": 0}
    assert result["scope"] == "activation-v7-default-off-not-live-handoff"


@pytest.mark.parametrize(
    ("relative", "expected"),
    (
        (acceptance.CANDIDATE_MANIFEST, acceptance.MANIFEST_SHA256),
        (acceptance.CHECKPOINT, acceptance.CHECKPOINT_SHA256),
        (acceptance.CORE, acceptance.CORE_SHA256),
        (acceptance.LAUNCHER, acceptance.LAUNCHER_SHA256),
        (acceptance.CANDIDATE_TEST, acceptance.CANDIDATE_TEST_SHA256),
        (acceptance.ACCEPTANCE_TEST, acceptance.ACCEPTANCE_TEST_SHA256),
    ),
)
def test_acceptance_anchors_are_exact(relative: str, expected: str):
    assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_independent_root_is_recomputed_in_sorted_path_order():
    payload = json.loads(
        acceptance._text(acceptance.PROJECT, acceptance.CANDIDATE_MANIFEST)
    )
    assert acceptance._independent_root(payload["files"]) == (
        acceptance.INDEPENDENT_ROOT_SHA256
    )


def test_one_line_sha_binds_only_external_record():
    digest, relative = acceptance._sha_line(
        acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_SHA)
    )
    assert relative == acceptance.ACCEPTANCE_RECORD
    assert digest == hashlib.sha256(
        (acceptance.PROJECT / relative).read_bytes()
    ).hexdigest()


def test_candidate_root_excludes_external_acceptance_paths():
    value = acceptance._text(acceptance.PROJECT, acceptance.CANDIDATE_MANIFEST)
    for forbidden in (
        acceptance.ACCEPTANCE_ID,
        acceptance.ACCEPTANCE_RECORD,
        acceptance.ACCEPTANCE_SHA,
        acceptance.ACCEPTANCE_TEST,
        acceptance.VERIFIER,
    ):
        assert forbidden not in value


def test_real_host_preflight_materializes_phase5_without_network():
    result = subprocess.run(
        [
            str(PYTHON),
            "-B",
            str(ROOT / acceptance.LAUNCHER),
            "--preflight-only",
        ],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ONYX_LIVE_V7_HOST_PREFLIGHT_OK" in result.stdout
    assert "bridge=core.phase5_integration_v3.Phase5IntegrationV3" in result.stdout
    assert "network_calls=0" in result.stdout


@pytest.mark.parametrize(
    ("relative", "marker"),
    (
        (acceptance.HOST_GATE, "ONYX_LIVE_ACTIVATION_V7_HOST_OK"),
        (acceptance.PROVIDER_GATE, "ONYX_LIVE_ACTIVATION_V7_PHASE5_E2E_OK"),
        (acceptance.CUMULATIVE_GATE, "ONYX_LIVE_ACTIVATION_V7_CUMULATIVE_OK"),
        (acceptance.MANIFEST_GATE, "ONYX_LIVE_ACTIVATION_V7_MANIFEST_OK"),
    ),
)
def test_reproduced_gate(relative: str, marker: str):
    result = subprocess.run(
        [str(PYTHON), "-B", str(ROOT / relative)],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=1200,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert marker in result.stdout


def test_focused_v7_is_six_of_six():
    _pytest_count(
        ("tests/test_onyx_live_activation_v7.py",),
        6,
        ".pytest-activation-v7-acceptance-focused",
    )


def test_v4_through_v7_real_count_is_thirty_one():
    _pytest_count(
        tuple(f"tests/test_onyx_live_activation_v{version}.py" for version in range(4, 8)),
        31,
        ".pytest-activation-v7-acceptance-v4-v7",
    )


def test_v2_through_v7_real_count_is_fifty_seven():
    _pytest_count(
        tuple(f"tests/test_onyx_live_activation_v{version}.py" for version in range(2, 8)),
        57,
        ".pytest-activation-v7-acceptance-v2-v7",
    )


def test_acceptance_boundary_and_two_p3_labels_are_explicit():
    record = acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_RECORD)
    assert "P0=0, P1=0, P2=0, P3=2" in record
    assert "31 passed, 0 failed" in record
    assert "57 passed, 0 failed" in record
    assert "core docstring" in record
    assert "checkpoint/manifest count label" in record
    assert "default-off" in record
    assert "No live activation" in record
