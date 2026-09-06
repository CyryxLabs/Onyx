from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "qml/components/OnyxHumanoidEntityV10.qml"
SHELL = ROOT / "qml/OnyxLiveShellV13.qml"
HTML = ROOT / "qml/web/onyx-humanoid-three-v1.html"
THREE = ROOT / "qml/web/vendor/three/three.module.min.js"
THREE_CORE = ROOT / "qml/web/vendor/three/three.core.min.js"
LICENSE = ROOT / "qml/web/vendor/three/LICENSE"
POINTS = ROOT / "qml/web/data/onyx-humanoid-pointcloud-v1.js"


def test_humanoid_uses_local_three_webgl_as_authoritative_renderer() -> None:
    source = QML.read_text(encoding="utf-8")
    assert "import QtWebEngine" in source
    assert 'objectName: "onyxHumanoidThreeWebGLV1"' in source
    assert 'url: Qt.resolvedUrl("../web/onyx-humanoid-three-v1.html")' in source
    assert "localContentCanAccessRemoteUrls: false" in source
    assert "visible: !entity.webglFailed" in source
    assert 'objectName: "onyxHumanoidWebGLFallbackV1"' in source
    assert "visible: entity.webglFailed" in source


def test_three_scene_is_real_geometry_not_a_textured_image() -> None:
    source = HTML.read_text(encoding="utf-8")
    for token in (
        "new THREE.WebGLRenderer",
        "new THREE.BufferGeometry",
        "new THREE.Points",
        "new THREE.ShaderMaterial",
        "decodeOnyxPointCloud",
        "ONYX_POINT_COUNT",
        "window.OnyxEntity",
    ):
        assert token in source
    assert "TextureLoader" not in source
    assert "onyx-humanoid-cyryx" not in source
    assert "new THREE.SphereGeometry" not in source
    assert "new THREE.CylinderGeometry" not in source
    assert "Source SHA-256:" in POINTS.read_text(encoding="utf-8")
    assert POINTS.stat().st_size > 200_000
    assert THREE.stat().st_size > 300_000
    assert THREE_CORE.stat().st_size > 300_000
    assert "MIT License" in LICENSE.read_text(encoding="utf-8")


def test_three_state_bridge_preserves_live_projection_contract() -> None:
    source = QML.read_text(encoding="utf-8")
    for token in (
        'operationalState === "SPEAKING"',
        "projection.reducedMotion",
        "projection.audioLevel",
        "projection.animationRunning",
        "window.OnyxEntity.setState",
        "onOperationalStateChanged",
        "onAudioChanged",
    ):
        assert token in source


def test_three_renderer_is_offline_deterministic_and_gpu_bounded() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "https://" not in source
    assert "http://" not in source
    assert "Math.random" not in source
    assert "Math.min(devicePixelRatio,1.5)" in source
    assert "const haloCount=2600" in source


def test_paused_or_resized_renderer_preserves_a_static_entity_frame() -> None:
    source = HTML.read_text(encoding="utf-8")
    assert "if(!state.active)state.formation=1" in source
    assert "requestAnimationFrame(now=>renderFrame(now,true))" in source
    assert "if(state.active)renderFrame(now)" in source


def test_humanoid_replaces_the_retired_orb_voice_lamp() -> None:
    shell = SHELL.read_text(encoding="utf-8")
    source = HTML.read_text(encoding="utf-8")
    assert 'root.findObject(root, "onyxOrbVoiceLayerV8")' in shell
    assert "predecessorVoiceLayer.visible = false" in shell
    assert "float faceEnergy=headMask*speaking" in source
    assert "vec3 cyryxTeal=vec3(.098,.780,.753)" in source
    assert "there is intentionally no centre-origin radial lamp" in source


def test_face_tracks_host_attention_with_bounded_cranial_and_body_motion() -> None:
    source = HTML.read_text(encoding="utf-8")
    qml = QML.read_text(encoding="utf-8")
    shell = SHELL.read_text(encoding="utf-8")
    for token in (
        "window.addEventListener('pointermove'",
        "document.addEventListener('pointerleave'",
        "setAttention(x,y,source)",
        "float headMask=smoothstep",
        "float yaw=uPointer.x*.220",
        "float pitch=-uPointer.y*.135",
        "entity.position.x=state.reduced?0:state.pointerX*.060",
        "material.uniforms.uPointer.value.set",
    ):
        assert token in source
    assert "const pointerTargetX=state.reduced?0:state.pointerTargetX" in source
    assert "function setAttention(x, y, source)" in qml
    assert "window.OnyxEntity.setAttention" in qml
    assert "function setVisualAttention(x, y, source)" in shell


def test_attention_bridge_coalesces_unchanged_cross_process_updates() -> None:
    qml = QML.read_text(encoding="utf-8")
    assert "Math.abs(boundedX - deliveredAttentionX) < 0.012" in qml
    assert "id: attentionFlush" in qml
    assert "interval: 66" in qml
    assert "repeat: false" in qml
    assert "if (!attentionFlush.running)" in qml
    assert qml.count("window.OnyxEntity.setAttention") == 1


def test_normal_source_launch_bootstraps_the_current_renderer(monkeypatch) -> None:
    import ui

    calls: list[tuple[str, int, object]] = []

    class Hud:
        def __init__(self, version: int) -> None:
            self.version = version
            self.FLAG_NAME = f"TEST_HUD_V{version}"

        def install_candidate(self, module) -> bool:
            calls.append(("candidate", self.version, module))
            return True

        def install_current(self, module) -> bool:
            calls.append(("current", self.version, module))
            return True

        def uninstall_candidate(self, _module) -> bool:
            return True

    modules = {f"core.onyx_hud_orb_v{version}": Hud(version) for version in range(6, 18)}

    monkeypatch.setattr(ui, "_verify_current_hud_contract", lambda _root: {})
    monkeypatch.setattr(ui.importlib, "import_module", modules.__getitem__)
    for version in range(6, 18):
        monkeypatch.delattr(ui, f"_ONYX_HUD_V{version}_INSTALLATION", raising=False)
    ui._CURRENT_HUD_OWNED_MODULES.clear()

    assert ui.install_current_hud_v10() is True
    assert calls == [
        *(('candidate', version, ui) for version in range(6, 10)),
        ('current', 17, ui),
    ]
    assert ui.uninstall_current_hud_v10() is True
