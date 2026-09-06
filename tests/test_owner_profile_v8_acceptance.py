from __future__ import annotations

import hashlib
from pathlib import Path
import platform

import pytest

from scripts import verify_owner_profile_v8_acceptance as acceptance


def test_external_acceptance_validates_exact_frozen_candidate() -> None:
    result = acceptance.verify(run_windows_primitives=False)
    assert result["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert result["core_sha256"] == acceptance.CORE_SHA256
    assert result["tests_sha256"] == acceptance.TESTS_SHA256
    assert result["manifest_sha256"] == acceptance.MANIFEST_SHA256
    assert result["closure"] == {
        "candidate_files": 2,
        "historical_candidates": 7,
    }
    assert result["windows_primitives"] == {"status": "not-requested"}
    assert (
        result["scope"]
        == "owner-profile-v8-isolated-default-off-unwired-windows-handoff"
    )


@pytest.mark.parametrize(
    ("relative", "expected"),
    (
        (acceptance.CORE, acceptance.CORE_SHA256),
        (acceptance.TESTS, acceptance.TESTS_SHA256),
        (acceptance.CANDIDATE_MANIFEST, acceptance.MANIFEST_SHA256),
    ),
)
def test_three_candidate_anchors_are_exact(relative: str, expected: str) -> None:
    assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_acceptance_manifest_binds_only_the_external_record() -> None:
    digest, relative = acceptance._manifest_line(
        acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST)
    )
    assert relative == acceptance.ACCEPTANCE_RECORD
    assert (
        digest
        == hashlib.sha256((acceptance.PROJECT / relative).read_bytes()).hexdigest()
    )


def test_all_v1_through_v7_history_is_rehashed() -> None:
    for version, (core_digest, tests_digest) in acceptance.HISTORICAL.items():
        assert (
            acceptance._digest(acceptance.PROJECT, f"core/owner_profile_v{version}.py")
            == core_digest
        )
        assert (
            acceptance._digest(
                acceptance.PROJECT, f"tests/test_owner_profile_v{version}.py"
            )
            == tests_digest
        )


def test_candidate_root_excludes_external_acceptance_paths() -> None:
    manifest = acceptance._text(acceptance.PROJECT, acceptance.CANDIDATE_MANIFEST)
    assert acceptance.ACCEPTANCE_ID not in manifest
    assert acceptance.ACCEPTANCE_RECORD not in manifest
    assert acceptance.ACCEPTANCE_MANIFEST not in manifest


def test_owner_profile_v8_remains_default_off_and_unwired() -> None:
    assert acceptance._verify_unwired(acceptance.PROJECT) >= 2
    manifest = acceptance._text(acceptance.PROJECT, acceptance.CANDIDATE_MANIFEST)
    assert '"default_off": true' in manifest
    assert '"live_wired": false' in manifest


def test_noncanonical_and_linked_paths_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(acceptance.OwnerProfileV8AcceptanceError):
        acceptance._canonical_relative("../core/owner_profile_v8.py")
    target = tmp_path / "target.txt"
    target.write_text("target\n", encoding="utf-8", newline="\n")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    with pytest.raises(acceptance.OwnerProfileV8AcceptanceError):
        acceptance._regular_path(tmp_path, "link.txt")


def test_real_windows_primitives_use_unique_namespace_and_cleanup() -> None:
    result = acceptance._verify_windows_primitives(acceptance.PROJECT)
    if platform.system() != "Windows":
        assert result["status"] == "not-run-non-windows"
        return
    assert result == {
        "status": "pass",
        "platform": "Windows",
        "global_named_mutex": True,
        "credential_manager_cas": True,
        "terminal_sequence": 2,
    }
