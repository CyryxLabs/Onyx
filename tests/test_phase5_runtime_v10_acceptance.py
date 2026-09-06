from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import verify_phase5_runtime_v10_acceptance as acceptance


def test_external_acceptance_validates_exact_frozen_candidate() -> None:
    result = acceptance.verify()
    assert result["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert result["core_sha256"] == acceptance.CORE_SHA256
    assert result["tests_sha256"] == acceptance.TESTS_SHA256
    assert result["manifest_sha256"] == acceptance.MANIFEST_SHA256
    assert result["checkpoint_sha256"] == acceptance.CHECKPOINT_SHA256
    assert result["closure"] == {"current_files": 2, "historical_files": 18}
    assert result["scope"] == "runtime-v10-isolated-default-off-unwired-handoff"


@pytest.mark.parametrize(
    ("relative", "expected"),
    (
        (acceptance.CORE, acceptance.CORE_SHA256),
        (acceptance.TESTS, acceptance.TESTS_SHA256),
        (acceptance.CANDIDATE_MANIFEST, acceptance.MANIFEST_SHA256),
        (acceptance.CHECKPOINT, acceptance.CHECKPOINT_SHA256),
    ),
)
def test_four_candidate_anchors_are_exact(relative: str, expected: str) -> None:
    assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_acceptance_manifest_binds_only_the_external_record() -> None:
    digest, relative = acceptance._manifest_line(
        acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST)
    )
    assert relative == acceptance.ACCEPTANCE_RECORD
    assert digest == hashlib.sha256(
        (acceptance.PROJECT / relative).read_bytes()
    ).hexdigest()


def test_malformed_or_tampered_acceptance_manifest_fails_closed() -> None:
    with pytest.raises(acceptance.RuntimeV10AcceptanceError):
        acceptance._manifest_line("bad\n")
    record = acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_RECORD)
    assert acceptance.CORE_SHA256 in record
    assert acceptance.MANIFEST_SHA256 in record


def test_candidate_root_excludes_external_acceptance_paths() -> None:
    manifest = acceptance._text(acceptance.PROJECT, acceptance.CANDIDATE_MANIFEST)
    assert acceptance.ACCEPTANCE_ID not in manifest
    assert acceptance.ACCEPTANCE_RECORD not in manifest
    assert acceptance.ACCEPTANCE_MANIFEST not in manifest


def test_runtime_v10_remains_default_off_and_unwired() -> None:
    assert acceptance._verify_unwired(acceptance.PROJECT) >= 2
    manifest = acceptance._text(acceptance.PROJECT, acceptance.CANDIDATE_MANIFEST)
    assert '"default_off": true' in manifest
    assert '"live_wired": false' in manifest


def test_noncanonical_and_linked_paths_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(acceptance.RuntimeV10AcceptanceError):
        acceptance._canonical_relative("../core/phase5_runtime_v10.py")
    target = tmp_path / "target.txt"
    target.write_text("target\n", encoding="utf-8", newline="\n")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    with pytest.raises(acceptance.RuntimeV10AcceptanceError):
        acceptance._regular_path(tmp_path, "link.txt")
