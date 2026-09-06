from pathlib import Path

import pytest

from core.onyx_packaged_runtime_hud_contract_v2 import PackagedRuntimeHudContractV2Error, REQUIRED_HOST_PORTS, verify_packaged_runtime_hud_contract_v2
from scripts.package_hygiene import stage_runtime_sources

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_v2_binds_capability_smoke_and_host_ports(tmp_path: Path) -> None:
    stage = tmp_path / "runtime"
    stage_runtime_sources(ROOT, stage, allowed_build_root=tmp_path)
    result = verify_packaged_runtime_hud_contract_v2(stage)
    assert result["tests_in_runtime"] is False
    assert result["checkout_fallback"] is False
    assert result["provider_dispatch"] is False
    assert all((stage / relative).is_file() for relative in REQUIRED_HOST_PORTS)


def test_packaged_v2_rejects_host_port_tamper(tmp_path: Path) -> None:
    stage = tmp_path / "runtime"
    stage_runtime_sources(ROOT, stage, allowed_build_root=tmp_path)
    (stage / "scripts/onyx_capabilities_cli.py").write_text("tamper", encoding="utf-8")
    with pytest.raises(PackagedRuntimeHudContractV2Error, match="input drift"):
        verify_packaged_runtime_hud_contract_v2(stage)
