"""Current HUD selection, immutable anatomy and package integrity regression."""
import json
import shutil
from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v47 import verify_current_hud_acceptance
from core.onyx_packaged_runtime_hud_contract_v16 import (
    MANIFEST_RELATIVE, PackagedRuntimeHudContractV16Error,
    verify_packaged_runtime_hud_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def test_current_source_and_package_accept_transparent_successor():
    assert verify_current_hud_acceptance(ROOT)["candidate"] == "onyx-hud-transparent-humanoid-001"
    assert verify_packaged_runtime_hud_contract(ROOT)["current_presence"] == "humanoid-presence-v13-transparent"


def test_live_selector_installs_successor_and_rolls_back():
    import ui
    try:
        assert ui.install_current_hud_v10() is True
        assert ui._CinematicHudV5Host.__module__ == "core.onyx_hud_orb_v17"
        assert ui.install_current_hud_v10() is True
    finally:
        assert ui.uninstall_current_hud_v10() is True


def test_package_rejects_changed_transparent_renderer(tmp_path):
    manifest = json.loads((ROOT / MANIFEST_RELATIVE).read_text())
    paths = {e["path"] for e in manifest["runtime_inputs"]}
    paths.update({str(MANIFEST_RELATIVE), "core/onyx_packaged_runtime_hud_contract_v15.py",
                  "core/onyx_packaged_runtime_hud_contract_v15.manifest.json"})
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    verify_packaged_runtime_hud_contract(tmp_path)
    target = tmp_path / "qml/web/onyx-humanoid-three-v4.html"
    target.write_text(target.read_text() + "<!-- altered -->")
    with pytest.raises(PackagedRuntimeHudContractV16Error, match="input drifted"):
        verify_packaged_runtime_hud_contract(tmp_path)
