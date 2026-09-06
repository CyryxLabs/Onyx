import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui import HudCanvas


class OrbPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_idle_orb_uses_bounded_ambient_timer_and_stops_when_hidden(self):
        hud = HudCanvas("")
        hud.resize(640, 480)
        hud.show()
        self.app.processEvents()

        hud.set_operational_state("LISTENING")
        hud.repaint()
        self.app.processEvents()
        self.assertTrue(hud._tmr.isActive())
        self.assertGreaterEqual(hud._tmr.interval(), 62)

        hud.set_operational_state("THINKING")
        self.assertTrue(hud._tmr.isActive())

        hud.set_operational_state("LISTENING")
        self.assertTrue(hud._tmr.isActive())
        hud.hide()
        self.app.processEvents()
        self.assertFalse(hud._tmr.isActive())
        hud.close()


if __name__ == "__main__":
    unittest.main()
