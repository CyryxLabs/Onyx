from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from scripts import verify_onyx_live_activation_v6_acceptance as acceptance


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def active_environment():
    result = dict(os.environ)
    for version in range(4, 7):
        result.pop(f"ONYX_LIVE_ACTIVATION_V{version}", None)
        result.pop(f"ONYX_LIVE_ROLLBACK_V{version}", None)
    result.update(
        {
            "ONYX_LIVE_ACTIVATION_V6": "1",
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
            "PYTHONDONTWRITEBYTECODE": "1",
            "QT_QPA_PLATFORM": "offscreen",
            "QSG_RHI_BACKEND": "software",
        }
    )
    return result


def test_external_acceptance_validates_exact_frozen_candidate():
    result = acceptance.verify()
    assert result["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert result["candidate_manifest_sha256"] == acceptance.MANIFEST_SHA256
    assert result["independent_root_sha256"] == acceptance.INDEPENDENT_ROOT_SHA256
    assert result["candidate_files"] == 34
    assert result["historical"] == {"passed": 224, "failed": 0}
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert result["focused"] == {"passed": 6, "failed": 0}
    assert result["combined"] == {"passed": 35, "failed": 0}
    assert result["scope"] == "activation-v6-default-off-not-live-handoff"


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
def test_acceptance_anchors_are_exact(relative, expected):
    assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_independent_root_is_recomputed_in_sorted_path_order():
    import json

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


def test_real_host_preflight_is_clean_and_provider_free():
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
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ONYX_LIVE_V6_HOST_PREFLIGHT_OK" in result.stdout


@pytest.mark.parametrize(
    ("relative", "marker"),
    (
        (acceptance.HOST_GATE, "ONYX_LIVE_ACTIVATION_V6_REAL_HOST_OK"),
        (acceptance.PROVIDER_GATE, "ONYX_LIVE_ACTIVATION_V6_FAKE_PROVIDER_OK"),
        (acceptance.QT_GATE, "ONYX_LIVE_ACTIVATION_V6_QT_OK"),
        (acceptance.CUMULATIVE_GATE, "ONYX_LIVE_ACTIVATION_V6_CUMULATIVE_OK"),
    ),
)
def test_reproduced_gate(relative, marker):
    result = subprocess.run(
        [str(PYTHON), "-B", str(ROOT / relative)],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert marker in result.stdout


def test_acceptance_is_default_off_and_real_live_is_next_gate():
    record = acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_RECORD)
    assert "P0=0, P1=0, P2=0, P3=0" in record
    assert "fake provider" in record
    assert "offscreen" in record
    assert "default-off" in record
    assert "real live activation is the next gate" in record
    assert "No live activation" in record
