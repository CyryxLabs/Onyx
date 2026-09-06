from __future__ import annotations

from pathlib import Path

from core.onyx_packaged_runtime_hud_contract_v5 import (
    verify_packaged_runtime_hud_contract,
)
from scripts.package_hygiene import LIQUID_METAL_RUNTIME_FILES, stage_runtime_sources


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_v5_authenticates_liquid_metal_runtime() -> None:
    result = verify_packaged_runtime_hud_contract(ROOT)
    assert result["runtime_inputs"] == 9
    assert result["current_orb"] == "liquid-metal-V9"
    assert result["formal_release_ready"] is False


def test_package_hygiene_includes_every_liquid_metal_runtime_file(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "runtime"
    stage_runtime_sources(ROOT, destination, allowed_build_root=tmp_path)
    assert all(
        (destination / relative).is_file() for relative in LIQUID_METAL_RUNTIME_FILES
    )
