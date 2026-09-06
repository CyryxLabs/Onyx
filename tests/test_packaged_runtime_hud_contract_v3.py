from __future__ import annotations

from pathlib import Path

import pytest

from core.onyx_packaged_runtime_hud_contract_v3 import (
    MANIFEST_RELATIVE,
    PackagedRuntimeHudContractV3Error,
    REQUIRED_HOST_PORTS,
    verify_packaged_runtime_hud_contract_v3,
)
from scripts.package_hygiene import CAPABILITY_RUNTIME_FILES, stage_runtime_sources

ROOT = Path(__file__).resolve().parents[1]


def _stage(tmp_path: Path) -> Path:
    stage = tmp_path / "runtime"
    stage_runtime_sources(ROOT, stage, allowed_build_root=tmp_path)
    return stage


def test_packaged_v3_binds_exact_current_capabilities_and_hygiene(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path)
    result = verify_packaged_runtime_hud_contract_v3(stage, project=ROOT)
    assert REQUIRED_HOST_PORTS == frozenset(CAPABILITY_RUNTIME_FILES)
    assert result["required_host_ports"] == len(CAPABILITY_RUNTIME_FILES)
    assert result["tests_in_runtime"] is False
    assert result["checkout_fallback"] is False
    assert result["provider_dispatch"] is False


@pytest.mark.parametrize(
    "relative",
    [Path("core/capability_ports/budget_v1.py"), Path("scripts/onyx_capabilities_cli.py")],
)
def test_packaged_v3_rejects_current_host_port_tamper(
    tmp_path: Path, relative: Path
) -> None:
    stage = _stage(tmp_path)
    (stage / relative).write_text("tamper", encoding="utf-8")
    with pytest.raises(PackagedRuntimeHudContractV3Error, match="host port drift"):
        verify_packaged_runtime_hud_contract_v3(stage, project=ROOT)


def test_packaged_v3_rejects_manifest_tamper(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    for relative in (
        MANIFEST_RELATIVE,
        Path("core/onyx_packaged_runtime_hud_contract_v2.manifest.json"),
        Path("scripts/package_hygiene.py"),
    ):
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    with (project / MANIFEST_RELATIVE).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(PackagedRuntimeHudContractV3Error, match="unreadable"):
        verify_packaged_runtime_hud_contract_v3(stage, project=project)
