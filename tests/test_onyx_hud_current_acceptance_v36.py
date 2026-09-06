from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v35 import (
    CURRENT_RUNTIME_PATHS as V35_RUNTIME_PATHS,
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
)
from core.onyx_hud_current_acceptance_v36 import (
    MANIFEST_RELATIVE,
    CurrentHudAcceptanceV36Error,
    verify_current_hud_acceptance,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v36_authenticates_living_liquid_metal_without_palette_change() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert result == {
        "candidate": "onyx-hud-v36-1.1.10-living-liquid-metal-001",
        "runtime_inputs": 8,
        "predecessor": "onyx-hud-v35-1.1.10-packaged-runtime-v4-001",
        "palette_changed": False,
        "published": False,
    }


def test_v36_rejects_manifest_tamper(tmp_path: Path) -> None:
    manifest = __import__("json").loads(
        (ROOT / MANIFEST_RELATIVE).read_text(encoding="utf-8")
    )
    relatives = {
        MANIFEST_RELATIVE,
        Path("core/onyx_hud_current_acceptance_v35.py"),
        Path("docs/onyx/acceptance/VE-HUD-CURRENT-V35-E6-001.manifest.json"),
        PREDECESSOR_ACCEPTANCE_RELATIVE,
        PREDECESSOR_MANIFEST_RELATIVE,
        *V35_RUNTIME_PATHS,
        *(Path(entry["path"]) for entry in manifest["runtime_inputs"]),
    }
    for relative in relatives:
        copied = tmp_path / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, copied)
    target = tmp_path / MANIFEST_RELATIVE
    with target.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV36Error, match="predecessor|manifest"):
        verify_current_hud_acceptance(tmp_path)
