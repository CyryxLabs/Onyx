"""V101 SOURCE qualification: actual link negatives, never substituted old hashes.

Run only '-k test_preparation' before the real seal. All other tests require genuine
V101 pins and a fully valid current source copy first. A physical OS permission
denial is reported as a skip, explicitly NOT link-rejection qualification.
Registry authentication is post-seal qualification; pre-seal preparation does
not require unfinished registry/helper source or fabricate its bindings.
"""

from contextlib import contextmanager
import errno
import os
from importlib import import_module
from pathlib import Path
import re
import shutil
import stat

import pytest

from scripts import verify_release_workflow_v101 as verifier
from scripts import generate_release_workflow_v101 as generator
from scripts.generate_release_workflow_v99 import R11_SNAPSHOTS
from scripts import generate_release_workflow_v100 as predecessor_generator
from scripts.verify_release_workflow_v99 import V99
from scripts.verify_release_workflow_v101 import (
    PROJECT, V100, V101, ReleaseWorkflowV101Error, verify_release_workflow_v101,
)

# Exact 53-target V99 tamper contract, retained without importing test99 or
# executing its fixtures. V99's generator supplies only its immutable snapshot
# path constants; no historical bytes, hashes, or runtime gates are rebound.
V99_TAMPER_PATHS = (
    "tests/fixtures/release_workflow_transition_v98.json",
    "tests/fixtures/release_workflow_transition_v99.json",
    "core/live_voice_continuity_v1.py",
    "core/telegram_official_connector_v1.py",
    "core/business_document_delivery_v1.py",
    "scripts/verify_release_workflow_v98.py",
    "scripts/generate_release_workflow_v99.py",
    "tests/test_release_workflow_transition_v99.py",
    "scripts/source_test_succession_v1.py",
    "tests/fixtures/source_test_succession_v1.json",
    "scripts/hud_test_succession_v1.py",
    "tests/fixtures/hud_test_succession_v1.json",
    "tests/test_hud_test_succession_v1.py",
    "tests/test_onyx_hud_current_acceptance_v36.py",
    "tests/test_packaged_runtime_hud_contract_v5.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V36-E6-001.manifest.json",
    "core/onyx_packaged_runtime_hud_contract_v5.manifest.json",
    "docs/onyx/CURRENT_CAPABILITY_STATUS_V1.md",
    "tests/test_current_capability_status_v1.py",
    "tests/test_current_capability_status_v2.py",
    "tests/test_hud_conversation_successor_v48.py",
    "tests/test_humanoid_promotion_v47.py",
    *R11_SNAPSHOTS,
    *(f"tests/fixtures/release_workflow_transition_v{sequence}.json" for sequence in range(71, 98)),
)

V100_TAMPER_PATHS = tuple(sorted({
    V99.as_posix(), V100.as_posix(), "ui.py", "scripts/build_release.py",
    "core/permission_broker.py", "core/live_voice_continuity_v1.py",
    "core/capability_ports/budget_v1.py", "scripts/onyx_capabilities_cli.py",
    "scripts/source_test_succession_v1.py", "scripts/hud_test_succession_v1.py",
    "tests/fixtures/source_test_succession_v1.json",
    "tests/fixtures/hud_test_succession_v1.json",
    *V99_TAMPER_PATHS,
    *predecessor_generator.ADDITIONS,
}))


TAMPER_PATHS = tuple(sorted({V101.as_posix(), *V100_TAMPER_PATHS, *generator.ADDITIONS}))

def test_preparation_all_53_predecessor_tamper_targets_are_retained():
    assert len(V99_TAMPER_PATHS) == len(set(V99_TAMPER_PATHS)) == 53
    assert set(V99_TAMPER_PATHS).issubset(TAMPER_PATHS)
    assert len(R11_SNAPSHOTS) == 4
    assert set(R11_SNAPSHOTS).issubset(V99_TAMPER_PATHS)
    assert "tests/fixtures/release_workflow_transition_v98.json" in TAMPER_PATHS


def test_preparation_capability_slice_and_exact_receipts_are_in_path_plan():
    from scripts.package_hygiene import CAPABILITY_RUNTIME_FILES, RUNTIME_TEST_EVIDENCE_FILES

    old = verifier._json(PROJECT / V100)
    assert verifier._sha256(PROJECT / V100) == verifier.V100_SHA256
    assert verifier._root(old, 100) == verifier.V100_ROOT_SHA256
    assert len(verifier._entries(old)) == 687
    # Empty registry here tests only the already-known inherited/additive plan;
    # it is not registry authentication or authorization to generate a fixture.
    paths = set(generator.planned_paths(old, {"bindings": {}}))
    assert len(CAPABILITY_RUNTIME_FILES) == 26
    assert len(RUNTIME_TEST_EVIDENCE_FILES) == 3
    assert set(generator.HISTORICAL_RECEIPTS) == set(RUNTIME_TEST_EVIDENCE_FILES)
    assert (set(CAPABILITY_RUNTIME_FILES) | set(RUNTIME_TEST_EVIDENCE_FILES)).issubset(paths)
    assert all((PROJECT / path).is_file() for path in generator.ADDITIONS
               if path not in {*generator.REGISTRY_SOURCES, generator.REPORT})
    assert V101.as_posix() not in paths
    assert "scripts/verify_release_workflow_v101.py" not in paths
    assert set(TAMPER_PATHS).issubset(paths | {V101.as_posix()})
    pending = {*generator.REGISTRY_SOURCES, generator.REPORT, V101.as_posix()}
    assert all((PROJECT / path).is_file() for path in TAMPER_PATHS if path not in pending)


def test_preparation_generation_requires_parent_authority(monkeypatch):
    monkeypatch.setattr(generator, "FINAL_FILE_LIST_CONFIRMED", False)
    with pytest.raises(RuntimeError, match="V101 unsealed: awaiting parent"):
        generator.generate()


def test_preparation_generator_authenticates_registry_before_source_reads(monkeypatch):
    monkeypatch.setattr(generator, "FINAL_FILE_LIST_CONFIRMED", True)

    def reject_registry(root):
        assert root == PROJECT
        raise RuntimeError("registry V3 authentication failed")

    def forbidden_read(*args):
        pytest.fail("Invalid registry must stop before source reads")

    monkeypatch.setattr(generator, "load_record", reject_registry)
    monkeypatch.setattr(generator, "_file", forbidden_read)
    with pytest.raises(RuntimeError, match="^registry V3 authentication failed$"):
        generator.generate()


@pytest.mark.parametrize("sequence", range(71, 101))
def test_preparation_historical_fixtures_keep_original_pins(sequence):
    authority = import_module(f"scripts.verify_release_workflow_v{sequence}")
    path = PROJECT / f"tests/fixtures/release_workflow_transition_v{sequence}.json"
    assert verifier._sha256(path) == getattr(authority, f"V{sequence}_SHA256")


@pytest.mark.parametrize("pin", ["V101_SHA256", "V101_ROOT_SHA256"])
def test_preparation_unsealed_verifier_rejects_before_reading_inputs(monkeypatch, pin):
    monkeypatch.setattr(verifier, pin, "UNSEALED_PENDING_PARENT_SEAL_NOW")

    def forbidden_read(*args):
        pytest.fail("Unsealed V101 must reject before reading any fixture")

    monkeypatch.setattr(verifier, "_json", forbidden_read)
    with pytest.raises(ReleaseWorkflowV101Error, match="^V101 unsealed:"):
        verify_release_workflow_v101()


def test_current_source_pins_membership_and_registry_are_source_only():
    current = verify_release_workflow_v101(PROJECT)
    record = current["transition"]
    assert record["logical_sequence"] == 101
    assert record["schema"] == "onyx.release-workflow-transition.v101"
    assert current["publishable"] is False
    assert current["formal_release_ready"] is False
    assert verifier._sha256(PROJECT / V101) == verifier.V101_SHA256
    assert verifier._root(record, 101) == verifier.V101_ROOT_SHA256
    old = verifier._json(PROJECT / V100)
    succession = generator.load_record(PROJECT)
    bindings = {row["path"]: row["sha256"] for row in record["current_release_paths"]}
    assert set(bindings) == set(generator.planned_paths(old, succession))
    assert {V101.as_posix(), "scripts/verify_release_workflow_v101.py"}.isdisjoint(bindings)
    assert all(bindings[path] == digest for path, digest in succession["bindings"].items())


@pytest.fixture(scope="module")
def verified_source_copy(tmp_path_factory):
    # Qualification supplies a fresh private external pytest basetemp. Never
    # copy installed owner data, and never modify any file in PROJECT.
    current = verify_release_workflow_v101(PROJECT)
    root = tmp_path_factory.mktemp("v101-private-source") / "v101-source"
    assert not root.exists()
    paths = {V100, V101, *(Path(row["path"]) for row in current["transition"]["current_release_paths"])}
    for relative in sorted(paths):
        original = verifier._file(PROJECT, relative)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
    baseline = verify_release_workflow_v101(root)
    assert baseline["transition"]["logical_sequence"] == 101
    assert baseline["publishable"] is False
    assert baseline["formal_release_ready"] is False
    return root


@pytest.mark.parametrize("relative", TAMPER_PATHS)
def test_rejects_tampered_source_predecessor_registry_and_history(verified_source_copy, relative):
    root = verified_source_copy
    verify_release_workflow_v101(root)
    target = root / relative
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# unexpected V101 qualification bytes\n")
        with pytest.raises(ReleaseWorkflowV101Error):
            verify_release_workflow_v101(root)
    finally:
        target.write_bytes(original)
    verify_release_workflow_v101(root)


@pytest.mark.parametrize("pin", ["V101_SHA256", "V101_ROOT_SHA256", "V100_SHA256", "V100_ROOT_SHA256"])
def test_rejects_wrong_strong_pins(monkeypatch, pin):
    verify_release_workflow_v101(PROJECT)
    monkeypatch.setattr(verifier, pin, "0" * 64)
    with pytest.raises(ReleaseWorkflowV101Error):
        verify_release_workflow_v101(PROJECT)


@contextmanager
def _real_link_in_private_copy(root, relative, *, directory=False):
    root = root.resolve(strict=True)
    assert not os.path.samefile(root, PROJECT)
    original = root / relative
    target = original.with_name(original.name + ".real-v101-link-target")
    # Validate both exact mutation targets remain inside this test-owned copy.
    original.resolve(strict=True).relative_to(root)
    target.parent.resolve(strict=True).relative_to(root)
    assert not target.exists()
    info = original.lstat()
    assert not getattr(info, "st_file_attributes", 0) & 0x400
    assert not stat.S_ISLNK(info.st_mode)
    original.rename(target)
    try:
        try:
            original.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            # Do not hide path mistakes, missing files, unsupported operations,
            # verifier failures, or unrelated I/O errors behind a blanket skip.
            if getattr(exc, "winerror", None) in {5, 1314} or exc.errno in {errno.EACCES, errno.EPERM}:
                pytest.skip(
                    "Physical OS denied real symlink creation; "
                    "V101 link rejection NOT CERTIFIED "
                    f"(winerror={getattr(exc, 'winerror', None)}, errno={exc.errno})"
                )
            raise
        assert stat.S_ISLNK(original.lstat().st_mode)
        # Check physical identity, not Windows substitution-path spelling.
        # Both the recorded target and the link itself must identify our copy.
        assert os.path.samefile(original.readlink(), target)
        assert os.path.samefile(original, target)
        yield
    finally:
        if original.is_symlink():
            original.unlink()
        assert not original.exists()
        target.rename(original)


def _require_typed_link_rejection(root, relative):
    # Match the actual inherited path-check error for THIS target. Earlier
    # source/version drift is not evidence that the introduced link was caught.
    message = (
        r"^V101 input unavailable or invalid: Release V65 input unavailable: "
        + re.escape(relative.as_posix()) + r"$"
    )
    with pytest.raises(ReleaseWorkflowV101Error, match=message):
        verify_release_workflow_v101(root)


def test_rejects_linked_permission_broker(verified_source_copy):
    root = verified_source_copy
    relative = Path("core/permission_broker.py")
    verify_release_workflow_v101(root)
    with _real_link_in_private_copy(root, relative):
        _require_typed_link_rejection(root, relative)
    verify_release_workflow_v101(root)


@pytest.mark.parametrize("relative", [Path("ui.py"), V100, V101], ids=["current-ui", "predecessor100", "current101"])
def test_rejects_linked_current_and_predecessor_inputs(verified_source_copy, relative):
    root = verified_source_copy
    verify_release_workflow_v101(root)
    with _real_link_in_private_copy(root, relative):
        _require_typed_link_rejection(root, relative)
    verify_release_workflow_v101(root)


def test_rejects_linked_core_ancestor(verified_source_copy):
    root = verified_source_copy
    baseline = verify_release_workflow_v101(root)
    first_core_input = next(
        Path(row["path"]) for row in baseline["transition"]["current_release_paths"]
        if row["path"].startswith("core/")
    )
    with _real_link_in_private_copy(root, Path("core"), directory=True):
        _require_typed_link_rejection(root, first_core_input)
    verify_release_workflow_v101(root)

def test_preparation_all_76_v100_tamper_targets_are_retained():
    assert len(V100_TAMPER_PATHS) == len(set(V100_TAMPER_PATHS)) == 76
    assert set(V100_TAMPER_PATHS).issubset(TAMPER_PATHS)
    assert {V100.as_posix(), V101.as_posix()}.issubset(TAMPER_PATHS)


@pytest.mark.parametrize("relative,directory", [
    (Path("core/permission_broker.py"), False),
    (Path("ui.py"), False),
    (V100, False),
    (V101, False),
    (Path("core"), True),
], ids=["broker", "ui", "predecessor100", "current101", "core-ancestor"])
def test_preparation_physical_link_helper_handles_windows_substitution_paths(
    tmp_path, relative, directory,
):
    # This is synthetic helper qualification, NOT a fabricated release frame.
    # No source fixture, release pin, or verifier result is created or patched.
    root = tmp_path / "synthetic-link-helper"
    original = root / relative
    if directory:
        original.mkdir(parents=True)
        payload = original / "synthetic.txt"
    else:
        original.parent.mkdir(parents=True)
        payload = original
    payload.write_bytes(b"synthetic physical-link probe\n")
    assert not original.is_symlink()
    before = payload.read_bytes()
    with _real_link_in_private_copy(root, relative, directory=directory):
        assert original.is_symlink()
        assert stat.S_ISLNK(original.lstat().st_mode)
        assert payload.read_bytes() == before
    assert not original.is_symlink()
    assert payload.read_bytes() == before
