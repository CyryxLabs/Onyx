from __future__ import annotations

from pathlib import Path

import pytest

from core.onyx_packaged_runtime_hud_contract_v4 import (
    PackagedRuntimeHudContractV4Error,
    REQUIRED_RUNTIME_FILES,
    verify_packaged_runtime_hud_contract_v4,
)
from scripts.package_hygiene import CAPABILITY_RUNTIME_FILES, stage_runtime_sources

ROOT = Path(__file__).resolve().parents[1]


def _stage(tmp_path: Path) -> Path:
    stage = tmp_path / "runtime"
    stage_runtime_sources(ROOT, stage, allowed_build_root=tmp_path)
    return stage


def test_packaged_v4_authenticates_exact_current_runtime(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    result = verify_packaged_runtime_hud_contract_v4(stage, project=ROOT)
    assert REQUIRED_RUNTIME_FILES == frozenset(CAPABILITY_RUNTIME_FILES)
    assert result["required_runtime_files"] == len(CAPABILITY_RUNTIME_FILES)
    assert result["tests_in_runtime"] is False


def test_packaged_v4_rejects_runtime_tamper(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    target = stage / "core/capability_ports/budget_v1.py"
    target.write_text("tamper", encoding="utf-8")
    with pytest.raises(PackagedRuntimeHudContractV4Error, match="runtime drift"):
        verify_packaged_runtime_hud_contract_v4(stage, project=ROOT)


def test_packaged_v4_rejects_linked_runtime_input(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    port = stage / "core/capability_ports/budget_v1.py"
    target = port.with_name("budget_v1-real.py")
    port.replace(target)
    try:
        port.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(PackagedRuntimeHudContractV4Error, match="unavailable|linked"):
        verify_packaged_runtime_hud_contract_v4(stage, project=ROOT)
