from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import verify_hud_orb_v5_live_acceptance as acceptance


def test_external_acceptance_rehashes_exact_candidate_and_boundary() -> None:
    result = acceptance.verify()
    assert result["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert result["candidate"]["manifest_sha256"] == (
        acceptance.CANDIDATE_MANIFEST_SHA256
    )
    assert result["candidate"]["checkpoint_sha256"] == (
        acceptance.CANDIDATE_CHECKPOINT_SHA256
    )
    assert result["default_off_boundary"] == {
        "flag_default_false": True,
        "exact_opt_in": "ONYX_HUD_V5_LIVE=1",
        "host_boundaries": 3,
        "live_activated": False,
    }
    assert result["focused_passed"] == 15
    assert result["representative_passed"] == 66
    assert result["matrix_anchors"] == 11
    assert result["severity"] == {"P0": 0, "P1": 0, "P2": 0}


def test_candidate_manifest_closure_and_v3_anchors_are_exact() -> None:
    expected = {**acceptance.CANDIDATE_FILES, **acceptance.ACCEPTED_V3_ANCHORS}
    for relative, (size, digest) in expected.items():
        payload = (acceptance.PROJECT / relative).read_bytes()
        assert len(payload) == size
        assert hashlib.sha256(payload).hexdigest() == digest


def test_rejected_candidate_002_snapshot_is_retired_and_not_accepted() -> None:
    result = acceptance._verify_rejected_snapshot(acceptance.PROJECT)
    assert result["rejected"] is True
    assert result["storage"] == "retired-absent"
    assert result["files"] == 13
    assert result["bytes"] == 2095770
    assert result["manifest_sha256"] == (
        "8daf7a43fd08ee6d7548992f4a8ef2da48c4271142dabae4e8fb0ee76c50d495"
    )
    assert result["checkpoint_sha256"] == (
        "42148552f863791979812f19b1019921ce9b785153f511f80803e40d127126d5"
    )
    assert result["screenshot_sha256"] == (
        "03b99d56a542d48680c5baa42ffd818e20c6e87043dc82333d098be662ee57a1"
    )


def test_retired_candidate_002_cannot_reappear(tmp_path: Path) -> None:
    ledger = tmp_path / acceptance.RETIREMENT_LEDGER
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes((acceptance.PROJECT / acceptance.RETIREMENT_LEDGER).read_bytes())
    (tmp_path / acceptance.SNAPSHOT_ROOT).mkdir(parents=True)
    with pytest.raises(
        acceptance.HudV5AcceptanceError,
        match="retired Candidate 002 snapshot was restored",
    ):
        acceptance._verify_rejected_snapshot(tmp_path)


def test_retirement_ledger_drift_fails_closed(tmp_path: Path) -> None:
    ledger = tmp_path / acceptance.RETIREMENT_LEDGER
    ledger.parent.mkdir(parents=True)
    payload = (acceptance.PROJECT / acceptance.RETIREMENT_LEDGER).read_text(
        encoding="utf-8"
    )
    ledger.write_text(
        payload.replace(
            "8daf7a43fd08ee6d7548992f4a8ef2da48c4271142dabae4e8fb0ee76c50d495",
            "0" * 64,
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        acceptance.HudV5AcceptanceError,
        match="Candidate 002 retirement record drifted",
    ):
        acceptance._verify_rejected_snapshot(tmp_path)


def test_acceptance_manifest_binds_only_the_external_record() -> None:
    digest, relative = acceptance._manifest_line(
        acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST)
    )
    assert relative == acceptance.ACCEPTANCE_RECORD
    assert digest == hashlib.sha256(
        (acceptance.PROJECT / relative).read_bytes()
    ).hexdigest()


def test_reproduction_commands_have_exact_unfiltered_membership() -> None:
    assert acceptance.FOCUSED_FILES == [
        "tests/test_onyx_hud_v5_live_integration.py"
    ]
    assert len(acceptance.REPRESENTATIVE_FILES) == 11
    assert "tests/test_orb_3d.py" in acceptance.REPRESENTATIVE_FILES
    assert len(set(acceptance.REPRESENTATIVE_FILES)) == 11
    assert acceptance._verify_matrix_anchors(acceptance.PROJECT) == 11


def test_malformed_or_noncanonical_inputs_fail_closed() -> None:
    with pytest.raises(acceptance.HudV5AcceptanceError):
        acceptance._manifest_line("bad\n")
    with pytest.raises(acceptance.HudV5AcceptanceError):
        acceptance._canonical_relative("../ui.py")
    with pytest.raises(acceptance.HudV5AcceptanceError):
        acceptance._canonical_relative("qml\\OnyxLiveShellV5.qml")


def test_linked_acceptance_path_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("target\n", encoding="utf-8", newline="\n")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    with pytest.raises(acceptance.HudV5AcceptanceError):
        acceptance._regular_path(tmp_path, "link.txt")
