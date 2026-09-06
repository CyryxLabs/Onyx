from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "qml/web/onyx-humanoid-three-v3.html"
QML = ROOT / "qml/components/OnyxHumanoidEntityV12.qml"


def test_three_renderer_exposes_a_real_frame_for_compositor_continuity() -> None:
    source = HTML.read_text(encoding="utf-8")

    assert 'src="onyx-humanoid-three-v2.html"' in source
    assert "sourceImageAtRuntime" not in source
    assert "context.drawImage(source" in source
    assert "captureCanvas.toDataURL('image/png')" in source
    assert "continuityFrame:true" in source


def test_qml_keeps_two_last_frame_buffers_behind_live_three_surface() -> None:
    source = QML.read_text(encoding="utf-8")

    assert 'objectName: "onyxHumanoidThreeWebGLV3"' in source
    assert 'backgroundColor: "transparent"' in source
    assert 'objectName: "onyxHumanoidContinuityA"' in source
    assert 'objectName: "onyxHumanoidContinuityB"' in source
    assert "window.OnyxEntity.captureFrame()" in source
    assert "interval: 750" in source
    assert "readinessAttempts >= 100" in source

