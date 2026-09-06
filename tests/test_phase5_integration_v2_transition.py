from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import verify_phase5_integration_v2_transition as transition


ROOT = Path(__file__).resolve().parents[1]


def test_transition_verifier_proves_history_before_v2() -> None:
    result = transition.verify()
    assert result["historical"]["acceptance_id"] == "VE-P5-RUNTIME-V10-E6-001"
    assert result["historical"]["historical_state"] == (
        "isolated-default-off-unwired"
    )
    assert result["candidate"] == "phase5-integration-v2"
    assert result["boundary"] == {
        "main_imports": ["core.phase5_integration_v2"],
        "default_off": True,
        "v1_reachable": False,
        "ui_dependency": False,
        "ui_scope": "out-of-scope-concurrent-transition",
    }
    assert result["compatibility"]["scope"] == (
        "secondary-closed-historical-compatibility-projection"
    )


def test_frozen_v10_verifier_is_loaded_only_after_exact_hash_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = transition._digest

    def drifted(project: Path, relative: str) -> str:
        if relative == transition.V10_VERIFIER:
            return "0" * 64
        return real(project, relative)

    monkeypatch.setattr(transition, "_digest", drifted)
    with pytest.raises(
        transition.Phase5IntegrationV2TransitionError, match="anchor drifted"
    ):
        transition._load_frozen_v10_verifier(ROOT)


def test_historical_v10_v1_and_in_scope_anchors_are_byte_exact() -> None:
    expected = {
        **transition.V10_FROZEN,
        **transition.V1_FROZEN,
        **transition.ACCEPTED_ANCHORS,
        **transition.UNCHANGED_SURFACES,
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
    assert transition.RESERVED_UI_PRE_PARALLEL_SHA256 == (
        "60bea0ac313efa7c77dfbc1e3bffec885a0dad010b6f3e9e332761d6cd0de043"
    )


def test_runtime_reference_scan_is_an_exact_allowlist() -> None:
    result = transition._scan_transition_surfaces(ROOT)
    assert set(result["runtime_references"]) == transition._RUNTIME_REFERENCE_ALLOWLIST
    assert result["files_checked"] >= 300


def test_v2_manifest_and_root_manifest_close_all_transition_files() -> None:
    result = transition._verify_v2_manifest(ROOT)
    assert result["files"] == 5
    assert result["root_records"] == 7


@pytest.mark.parametrize(
    "relative",
    (
        "../main.py",
        "/main.py",
        "core\\phase5_integration_v2.py",
        "core/../main.py",
    ),
)
def test_noncanonical_transition_paths_fail_closed(relative: str) -> None:
    with pytest.raises(transition.Phase5IntegrationV2TransitionError):
        transition._canonical_relative(relative)
