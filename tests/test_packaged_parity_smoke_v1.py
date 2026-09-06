from pathlib import Path

import pytest

from core import capability_parity_v1 as parity
from scripts import build_release


def test_packaged_parity_requires_frozen_runtime(tmp_path: Path) -> None:
    with pytest.raises(parity.CapabilityParityError, match="frozen"):
        parity.validate_packaged_parity_v1(tmp_path)


def test_release_pipeline_executes_packaged_parity_smoke() -> None:
    source = Path(build_release.__file__).read_text(encoding="utf-8")
    bootstrap = (
        Path(build_release.__file__).parents[1] / "scripts" / "bootstrap_onyx.pyw"
    ).read_text(encoding="utf-8")
    assert 'PARITY_SMOKE_ARGUMENT = "--parity-smoke-v1"' in source
    assert "package_parity_smoke_test(validation_bundle)" in source
    assert '["--parity-smoke-v1"]' in bootstrap


def test_spec_declares_parity_runtime_modules() -> None:
    spec = (Path(__file__).parents[1] / "packaging" / "onyx.spec").read_text(
        encoding="utf-8"
    )
    for module in parity.PACKAGED_RUNTIME_MODULES:
        assert f'"{module}"' in spec


def test_every_capability_has_importable_runtime_evidence() -> None:
    modules = {
        parity._module_name_from_evidence(relative)
        for row in parity.CAPABILITIES
        for relative in row.evidence
    }
    assert "main" in modules
    assert "ui" in modules
    assert "scripts.onyx_plugin_cli" in modules
    assert all(not module.startswith("tests.") for module in modules)
