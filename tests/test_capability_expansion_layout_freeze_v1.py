"""Regression boundary between capability expansion and the accepted Onyx HUD."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/onyx/acceptance/VE-HUD-CURRENT-V48-E6-001.manifest.json"
PREDECESSOR = ROOT / "docs/onyx/acceptance/VE-HUD-CURRENT-V47-E6-001.manifest.json"
VISUAL_RUNTIME_INPUTS = frozenset(
    {
        "core/onyx_hud_orb_v17.py",
        "qml/OnyxLiveShellV16.qml",
        "qml/components/OnyxHumanoidEntityV13.qml",
        "qml/web/data/onyx-humanoid-pointcloud-v1.js",
        "qml/web/onyx-humanoid-three-v4.html",
        "qml/web/onyx-humanoid-three-v5.html",
        "qml/web/vendor/three/three.core.min.js",
        "qml/web/vendor/three/three.module.min.js",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_capability_expansion_preserves_owner_accepted_layout() -> None:
    """Any content drift in the owner-accepted presentation must fail."""

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = {entry["path"]: entry["sha256"] for entry in manifest["runtime_inputs"]}

    assert manifest["decision"] == "accepted-source"
    assert manifest["current_root"] == "qml/OnyxLiveShellV16.qml"
    assert manifest["semantics"]["palette_changed"] is False
    assert manifest["semantics"]["humanoid_anatomy_changed"] is False
    assert manifest["semantics"]["humanoid_runtime_changed"] is False
    assert manifest["semantics"]["conversation_projection_changed"] is True
    assert manifest["semantics"]["live_renderer"] == "three.js-webgl"
    assert manifest["semantics"]["voice_pipeline_changed"] is False
    assert VISUAL_RUNTIME_INPUTS <= entries.keys()
    previous = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    old_entries = {entry["path"]: entry["sha256"] for entry in previous["runtime_inputs"]}
    for relative in VISUAL_RUNTIME_INPUTS:
        assert _sha256(ROOT / relative) == entries[relative]
        assert entries[relative] == old_entries[relative]

    # ui.py also remains bound to the current accepted authority. Non-visual
    # changes must create a successor manifest instead of silently bypassing the
    # owner-accepted presentation contract.
    assert _sha256(ROOT / "ui.py") == entries["ui.py"]
