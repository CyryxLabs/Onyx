from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import verify_phase5_integration_v3_acceptance as acceptance


def test_external_acceptance_executes_exact_frozen_transition() -> None:
    result = acceptance.verify()
    assert result["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert result["manifest_sha256"] == acceptance.MANIFEST_SHA256
    assert result["transition_marker"] == "P5_INTEGRATION_V3_TRANSITION_OK"
    assert result["focused_passed"] == 35
    assert result["cumulative_passed"] == 230
    assert result["severity"] == {"P0": 0, "P1": 0, "P2": 0}
    assert result["scope"] == "integration-v3-frozen-default-off-no-activation"


def test_candidate_history_and_anchor_closures_are_exact() -> None:
    expected = {
        **acceptance.CANDIDATE_FILES,
        **acceptance.V1_FROZEN,
        **acceptance.V2_FROZEN,
        **acceptance.ACCEPTED_ANCHORS,
        acceptance.MANIFEST: acceptance.MANIFEST_SHA256,
        acceptance.CHECKPOINT: acceptance.CHECKPOINT_SHA256,
        acceptance.ROOT_MANIFEST: acceptance.ROOT_MANIFEST_SHA256,
        **{
            value["path"]: value["sha256"]
            for value in acceptance.PROJECTIONS.values()
        },
    }
    for relative, digest in expected.items():
        acceptance._require_digest(acceptance.PROJECT, relative, digest)


def test_acceptance_manifest_binds_only_the_external_record() -> None:
    digest, relative = acceptance._manifest_line(
        acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST)
    )
    assert relative == acceptance.ACCEPTANCE_RECORD
    assert digest == hashlib.sha256(
        (acceptance.PROJECT / relative).read_bytes()
    ).hexdigest()


def test_manifest_contract_is_default_off_and_not_activated() -> None:
    result = acceptance._verify_candidate(acceptance.PROJECT)
    assert result == {
        "candidate_files": 5,
        "root_records": 10,
        "execution_closures": 3,
        "flags_default_false": 8,
    }


def test_exact_commands_bind_35_focused_and_230_cumulative() -> None:
    assert acceptance.FOCUSED_COMMAND == [
        "python", "-m", "pytest", "-q",
        "tests/test_phase5_integration_v3.py",
        "tests/test_phase5_integration_v3_transition.py",
        "--basetemp", ".pytest-p5-v3-acceptance-focused",
    ]
    assert acceptance.CUMULATIVE_COMMAND[:4] == ["python", "-m", "pytest", "-q"]
    assert acceptance.CUMULATIVE_COMMAND[-2:] == [
        "--basetemp", ".pytest-p5-v3-cumulative"
    ]
    assert "-k" not in acceptance.CUMULATIVE_COMMAND
    assert "--ignore" not in acceptance.CUMULATIVE_COMMAND


def test_malformed_and_noncanonical_acceptance_inputs_fail_closed() -> None:
    with pytest.raises(acceptance.IntegrationV3AcceptanceError):
        acceptance._manifest_line("bad\n")
    with pytest.raises(acceptance.IntegrationV3AcceptanceError):
        acceptance._canonical_relative("../main.py")
    with pytest.raises(acceptance.IntegrationV3AcceptanceError):
        acceptance._canonical_relative("core\\phase5_integration_v3.py")


def test_linked_acceptance_path_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("target\n", encoding="utf-8", newline="\n")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    with pytest.raises(acceptance.IntegrationV3AcceptanceError):
        acceptance._regular_path(tmp_path, "link.txt")
