"""Real staging byte/membership negatives; source admission stays separate.

Preparation exercises the pure slice validator against the real stager and
source hashes, not a claimed V100 seal. The final test additionally requires
the genuine V100 source authority. No frozen source or manifest is mutated.
"""

import hashlib
from pathlib import Path

import pytest

from scripts import package_hygiene
from scripts import verify_staged_capabilities_v1 as current

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    parent = tmp_path_factory.mktemp("current-capability-stage")
    stage = parent / "runtime"
    package_hygiene.stage_runtime_sources(ROOT, stage, allowed_build_root=parent)
    required = {*package_hygiene.CAPABILITY_RUNTIME_FILES, *package_hygiene.RUNTIME_TEST_EVIDENCE_FILES}
    bindings = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in required}
    current._verify_slice(stage, bindings)
    return stage, bindings


def test_preparation_actual_stager_preserves_current_capabilities_and_three_receipts(staged):
    stage, bindings = staged
    result = current._verify_slice(stage, bindings)
    assert result["capability_files"] == len(package_hygiene.CAPABILITY_RUNTIME_FILES)
    assert result["historical_receipt_files"] == 3
    assert result["development_tests"] is False
    assert result["provider_dispatch"] is False
    assert result["checkout_fallback"] is False


@pytest.mark.parametrize("relative", [
    "core/capability_ports/budget_v1.py", "scripts/onyx_capabilities_cli.py",
    "core/governed_capability_host_v1.py", *package_hygiene.RUNTIME_TEST_EVIDENCE_FILES,
])
def test_preparation_detects_staged_input_tamper_after_valid_baseline(staged, relative):
    stage, bindings = staged
    current._verify_slice(stage, bindings)
    target = stage / relative
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# unexpected stage mutation\n")
        with pytest.raises(current.StagedCapabilityError, match="staged input drifted: " + relative):
            current._verify_slice(stage, bindings)
    finally:
        target.write_bytes(original)
    current._verify_slice(stage, bindings)


def test_preparation_detects_omitted_host_port(staged):
    stage, bindings = staged
    relative = "core/capability_ports/budget_v1.py"
    original = stage / relative
    retained = original.with_suffix(".retained")
    current._verify_slice(stage, bindings)
    original.rename(retained)
    try:
        with pytest.raises(current.StagedCapabilityError, match="staged input unavailable or linked: " + relative):
            current._verify_slice(stage, bindings)
    finally:
        retained.rename(original)


def test_preparation_detects_physical_same_byte_host_port_link(staged):
    stage, bindings = staged
    relative = "core/capability_ports/budget_v1.py"
    original = stage / relative
    retained = original.with_suffix(".retained")
    current._verify_slice(stage, bindings)
    original.rename(retained)
    try:
        try:
            original.symlink_to(retained)
        except OSError as exc:
            if getattr(exc, "winerror", None) in {5, 1314}:
                pytest.skip("OS denied physical link; staged link protection not certified")
            raise
        with pytest.raises(current.StagedCapabilityError, match="staged input unavailable or linked: " + relative):
            current._verify_slice(stage, bindings)
    finally:
        if original.is_symlink():
            original.unlink()
        retained.rename(original)
    current._verify_slice(stage, bindings)


@pytest.mark.parametrize("relative,reason", [
    ("core/capability_ports/unapproved_v1.py", "port membership"),
    ("tests/test_unapproved.py", "receipt membership"),
])
def test_preparation_detects_undeclared_stage_members(staged, relative, reason):
    stage, bindings = staged
    current._verify_slice(stage, bindings)
    extra = stage / relative
    assert not extra.exists()
    try:
        with extra.open("xb") as stream:
            stream.write(b"# unexpected stage member\n")
        with pytest.raises(current.StagedCapabilityError, match=reason):
            current._verify_slice(stage, bindings)
    finally:
        if extra.exists():
            extra.unlink()


def test_current_source_admission_and_actual_staging(staged):
    stage, _bindings = staged
    result = current.verify(stage, project=ROOT)
    assert result["capability_files"] == len(package_hygiene.CAPABILITY_RUNTIME_FILES)
