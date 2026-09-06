from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v35 import (
    CURRENT_RUNTIME_PATHS,
    MANIFEST_RELATIVE,
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
    CurrentHudAcceptanceV35Error,
    verify_current_hud_acceptance,
)
from scripts.package_hygiene import CAPABILITY_RUNTIME_FILES

ROOT = Path(__file__).resolve().parents[1]


def _copy_closure(destination: Path) -> None:
    for relative in {MANIFEST_RELATIVE, PREDECESSOR_ACCEPTANCE_RELATIVE, PREDECESSOR_MANIFEST_RELATIVE, *CURRENT_RUNTIME_PATHS}:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def test_v35_authenticates_v4_current_runtime() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert result["candidate"] == "onyx-hud-v35-1.1.10-packaged-runtime-v4-001"
    assert result["runtime_inputs"] == len(CURRENT_RUNTIME_PATHS)
    assert result["capability_runtime_files"] == len(CAPABILITY_RUNTIME_FILES)
    assert result["packaged_test_sources"] is False


@pytest.mark.parametrize("relative", [Path("scripts/package_hygiene.py"), Path("core/onyx_packaged_runtime_hud_contract_v4.py"), PREDECESSOR_MANIFEST_RELATIVE])
def test_v35_rejects_current_or_predecessor_tamper(tmp_path: Path, relative: Path) -> None:
    _copy_closure(tmp_path)
    with (tmp_path / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV35Error, match="source input drift|predecessor drift"):
        verify_current_hud_acceptance(tmp_path)


def test_v35_rejects_linked_v4_input(tmp_path: Path) -> None:
    _copy_closure(tmp_path)
    source = tmp_path / "core/onyx_packaged_runtime_hud_contract_v4.py"
    target = source.with_name("onyx_packaged_runtime_hud_contract_v4-real.py")
    source.replace(target)
    try:
        source.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(CurrentHudAcceptanceV35Error, match="unavailable|linked"):
        verify_current_hud_acceptance(tmp_path)
