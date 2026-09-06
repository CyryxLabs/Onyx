"""Conversation-only promotion: real hashes, unchanged visuals, fail-closed tampering."""

import json
import shutil
from pathlib import Path

import pytest

from core import onyx_hud_current_acceptance_v48 as source
from core import onyx_packaged_runtime_hud_contract_v17 as packaged

ROOT = Path(__file__).resolve().parents[1]


def test_current_selector_keeps_humanoid_host_and_is_reversible():
    import ui
    try:
        assert ui.install_current_hud_v10() is True
        assert ui._CinematicHudV5Host.__module__ == "core.onyx_hud_orb_v17"
        assert ui.install_current_hud_v10() is True
    finally:
        assert ui.uninstall_current_hud_v10() is True


@pytest.mark.parametrize("module,verify", [
    (source, source.verify_current_hud_acceptance),
    (packaged, packaged.verify_packaged_runtime_hud_contract),
])
def test_real_source_and_packaged_contracts(module, verify):
    result = verify(ROOT)
    assert result["primary_layout_changed"] is False
    assert result["live_renderer"] == "three.js-webgl"
    current = json.loads((ROOT / module.MANIFEST_RELATIVE).read_text())
    previous = json.loads((ROOT / module.PREDECESSOR_MANIFEST).read_text())
    old = {row["path"]: row["sha256"] for row in previous["runtime_inputs"]}
    for row in current["runtime_inputs"]:
        if row["path"].startswith("qml/") or row["path"] == "core/live_voice_preference_v1.py":
            assert row["sha256"] == old[row["path"]]
    assert current["semantics"]["humanoid_runtime_changed"] is False
    assert current["semantics"]["conversation_projection_changed"] is True


@pytest.mark.parametrize("module,verify,error", [
    (source, source.verify_current_hud_acceptance, source.CurrentHudAcceptanceV48Error),
    (packaged, packaged.verify_packaged_runtime_hud_contract, packaged.PackagedRuntimeHudContractV17Error),
])
@pytest.mark.parametrize("changed", ["runtime", "manifest", "predecessor", "visual"])
def test_rejects_real_byte_tampering(tmp_path, module, verify, error, changed):
    manifest = json.loads((ROOT / module.MANIFEST_RELATIVE).read_text())
    predecessor_module = getattr(module, "PREDECESSOR_ACCEPTANCE", None) or module.PREDECESSOR_MODULE
    paths = {module.MANIFEST_RELATIVE, module.PREDECESSOR_MANIFEST, predecessor_module}
    paths.update(Path(row["path"]) for row in manifest["runtime_inputs"])
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    verify(tmp_path)
    target = {
        "runtime": Path("ui.py"), "manifest": module.MANIFEST_RELATIVE,
        "predecessor": module.PREDECESSOR_MANIFEST,
        "visual": Path("qml/OnyxLiveShellV16.qml"),
    }[changed]
    with (tmp_path / target).open("ab") as stream:
        stream.write(b"\n# unexpected bytes")
    with pytest.raises(error):
        verify(tmp_path)
