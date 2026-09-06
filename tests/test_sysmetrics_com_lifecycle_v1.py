"""Process-isolated metrics/COM lifecycle checks, without live account access."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROCESS_TIMEOUT = 20


class SysMetricsLifecycleTests(unittest.TestCase):
    def run_child(self, code):
        with tempfile.TemporaryDirectory(prefix="onyx-metrics-") as directory:
            env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                       ONYX_DATA_DIR=directory, PYTHONUTF8="1", QT_QPA_PLATFORM="offscreen")
            result = subprocess.run(
                [sys.executable, "-B", "-c", textwrap.dedent(code)],
                cwd=directory, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=PROCESS_TIMEOUT,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("releasing IUnknown", result.stdout + result.stderr)
        self.assertNotIn("Exception in thread", result.stderr)
        self.assertNotIn("Exception ignored", result.stderr)
        return json.loads(result.stdout.splitlines()[-1])

    def test_host_import_does_not_start_sampling_or_import_wmi(self):
        result = self.run_child("""
            import json, sys, threading
            import main, ui
            assert ui._metrics._thread is None
            assert 'wmi' not in sys.modules
            assert not any(t.name == 'onyx-system-metrics' for t in threading.enumerate())
            print(json.dumps(ui._metrics.snapshot()))
        """)
        self.assertEqual(set(result), {"cpu", "mem", "net", "gpu", "tmp"})

    @unittest.skipUnless(sys.platform == "win32", "real Windows COM required")
    def test_real_com_queries_restart_and_release_on_the_worker_thread(self):
        result = self.run_child("""
            import json, threading, time, sys
            import ui, pythoncom, win32com.client
            events = []
            baseline_interfaces = pythoncom._GetInterfaceCount()
            init, uninit = pythoncom.CoInitializeEx, pythoncom.CoUninitialize
            get_object = win32com.client.GetObject
            def initialize(flags):
                init(flags)
                events.append(('initialize', threading.get_ident()))
            def uninitialize():
                events.append(('uninitialize', threading.get_ident()))
                uninit()
            def connect(*args, **kwargs):
                obj = get_object(*args, **kwargs)
                events.append(('connected', threading.get_ident()))
                return obj
            pythoncom.CoInitializeEx = initialize
            pythoncom.CoUninitialize = uninitialize
            win32com.client.GetObject = connect
            metrics = ui._SysMetrics()
            for cycle in range(2):
                assert metrics.start()
                assert not metrics.start()
                deadline = time.monotonic() + 6
                while metrics.snapshot()['mem'] <= 0 or len(events) < cycle * 3 + 2:
                    assert time.monotonic() < deadline, events
                    time.sleep(0.02)
                assert metrics.stop()
                assert metrics.stop()
                assert not metrics._thread.is_alive()
                assert pythoncom._GetInterfaceCount() == baseline_interfaces
            assert [e[0] for e in events] == ['initialize', 'connected', 'uninitialize'] * 2, events
            for offset in (0, 3):
                assert len({e[1] for e in events[offset:offset+3]}) == 1
                assert events[offset][1] != threading.get_ident()
            assert 'wmi' not in sys.modules
            print(json.dumps({'events': events, 'snapshot': metrics.snapshot()}))
        """)
        self.assertGreater(result["snapshot"]["mem"], 0)
        self.assertEqual(len(result["events"]), 6)

    def test_blocked_sample_stop_is_bounded_and_prevents_duplicate_worker(self):
        self.run_child("""
            import json, threading, time
            import ui
            entered, release = threading.Event(), threading.Event()
            metrics = ui._SysMetrics()
            def blocked():
                entered.set()
                release.wait(5)
            metrics._update = blocked
            assert metrics.start()
            assert entered.wait(3)
            before = time.monotonic()
            assert not metrics.stop(timeout=0.05)
            assert time.monotonic() - before < 0.5
            assert not metrics.start()
            release.set()
            assert metrics.stop()
            print(json.dumps({'stopped': not metrics._thread.is_alive()}))
        """)

    def test_qt_about_to_quit_stops_real_metrics_worker(self):
        result = self.run_child("""
            import json
            import ui
            from PySide6.QtCore import QTimer
            app = ui.QApplication([])
            # Construct the real window: it must own metrics startup and the
            # aboutToQuit hookup. No runtime, voice session or accounts started.
            window = ui.MainWindow('')
            metrics = ui._metrics
            assert metrics._thread is not None and metrics._thread.is_alive()
            QTimer.singleShot(500, app.quit)
            app.exec()
            assert not metrics._thread.is_alive()
            print(json.dumps({'stopped': True}))
        """)
        self.assertTrue(result["stopped"])

    def test_resident_close_keeps_sampling_and_accepted_close_stops_it(self):
        self.run_child("""
            import json
            import ui
            from PySide6.QtGui import QCloseEvent
            app = ui.QApplication([])
            window = ui.MainWindow('')
            window._close_to_background = True
            window._tray_available = True
            background = QCloseEvent()
            window.closeEvent(background)
            assert not background.isAccepted()
            assert ui._metrics._thread.is_alive()
            window._exit_requested = True
            accepted = QCloseEvent()
            window.closeEvent(accepted)
            assert accepted.isAccepted()
            assert not ui._metrics._thread.is_alive()
            print(json.dumps({'resident_preserved': True, 'exit_stopped': True}))
        """)


if __name__ == "__main__":
    unittest.main()
