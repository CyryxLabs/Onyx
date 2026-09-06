import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication

from core.orb_state import (
    OrbStateBridge,
    QUALITY_BUDGETS,
    configured_quality,
    configured_reduced_motion,
)
from core.paths import resource_root
from main import _run_package_smoke_test
from ui import MainWindow, OrbHost


class OrbStateTests(unittest.TestCase):
    def test_quality_is_validated_with_safe_default(self):
        with patch.dict(os.environ, {"ONYX_ORB_QUALITY": "ultra"}):
            self.assertEqual(configured_quality(), "low")

    def test_quality_and_reduced_motion_can_come_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({"orb_quality": "high", "reduced_motion": True}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(configured_quality(path), "high")
                self.assertTrue(configured_reduced_motion(path))

    def test_bridge_runs_only_for_visible_active_cognition(self):
        bridge = OrbStateBridge(quality="medium", reduced_motion=False)
        bridge.set_surface_active(True)
        bridge.set_state("LISTENING")
        self.assertFalse(bridge.active)
        bridge.set_state("THINKING")
        self.assertTrue(bridge.active)
        bridge.set_muted(True)
        self.assertFalse(bridge.active)
        bridge.set_muted(False)
        bridge.set_state("SPEAKING")
        self.assertTrue(bridge.active)
        bridge.set_surface_active(False)
        self.assertFalse(bridge.active)
        self.assertEqual(bridge.particleBudget, QUALITY_BUDGETS["medium"])

    def test_reduced_motion_never_starts_simulation(self):
        bridge = OrbStateBridge(reduced_motion=True)
        bridge.set_surface_active(True)
        bridge.set_state("PROCESSING")
        self.assertFalse(bridge.active)


class OrbHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_safe_mode_uses_only_still_software_renderer(self):
        host = OrbHost("", force_fallback=True)
        host.show()
        self.app.processEvents()
        host.set_operational_state("THINKING")
        self.assertEqual(host.renderer_mode, "fallback")
        self.assertFalse(host.bridge.active)
        self.assertTrue(host.fallback._tmr.isActive())
        host.hide()
        self.app.processEvents()
        self.assertFalse(host.fallback._tmr.isActive())

    def test_reduced_motion_stops_software_renderer_for_every_active_state(self):
        host = OrbHost("", force_fallback=True)
        host.show()
        self.app.processEvents()
        host.set_reduced_motion(True)
        for state in ("THINKING", "PROCESSING", "SPEAKING"):
            host.set_operational_state(state)
            self.assertFalse(host.bridge.active)
            self.assertFalse(host.fallback._animation_required())
            self.assertFalse(host.fallback._tmr.isActive())
        host.close()

    def test_qml_error_switches_to_fallback(self):
        missing = resource_root() / "qml" / "missing.qml"
        with patch.object(OrbHost, "_gpu_api_unavailable", return_value=False):
            host = OrbHost("", qml_path=missing, force_fallback=False)
            self.app.processEvents()
        self.assertEqual(host.renderer_mode, "fallback")
        self.assertFalse(host.bridge.active)

    def test_packaged_qml_component_is_ready_and_exposes_root(self):
        qml_path = resource_root() / "qml" / "OnyxOrb.qml"
        self.assertTrue(qml_path.is_file())
        engine = QQmlEngine()
        bridge = OrbStateBridge(engine, reduced_motion=False)
        engine.rootContext().setContextProperty("orbBridge", bridge)
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_path)))
        errors = "\n".join(error.toString() for error in component.errors())
        self.assertEqual(component.status(), QQmlComponent.Status.Ready, errors)
        root = component.create()
        self.assertIsNotNone(root, errors)
        self.assertEqual(root.objectName(), "onyxOrbRoot")
        self.assertEqual(
            root.property("configuredParticleBudget"), bridge.particleBudget
        )
        root.deleteLater()

    def test_package_smoke_test_instantiates_quick3d_root(self):
        _run_package_smoke_test()

    def test_main_window_minimize_and_restore_resync_orb_lifecycle(self):
        with patch.dict(os.environ, {"ONYX_ORB_RENDERER": "software"}):
            window = MainWindow("")
        window.show()
        self.app.processEvents()
        window.hud.set_operational_state("THINKING")
        timer = (
            window.hud._motion_timer
            if hasattr(window.hud, "_motion_timer")
            else window.hud.fallback._tmr
        )
        self.assertTrue(timer.isActive())

        with patch.object(
            window.hud, "sync_animation", wraps=window.hud.sync_animation
        ) as sync:
            window.showMinimized()
            self.app.processEvents()
            self.assertTrue(sync.called)
            bridge_active = (
                window.hud.bridge.animationRunning
                if hasattr(window.hud.bridge, "animationRunning")
                else window.hud.bridge.active
            )
            self.assertFalse(bridge_active)
            self.assertFalse(timer.isActive())

            sync.reset_mock()
            window.showNormal()
            self.app.processEvents()
            self.assertTrue(sync.called)
            self.assertTrue(timer.isActive())
        window.close()


if __name__ == "__main__":
    unittest.main()
