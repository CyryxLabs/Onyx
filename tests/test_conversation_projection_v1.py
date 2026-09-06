"""Exercise actual Qt projection and owner history callback in isolation."""
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_latest_reply_and_full_history(tmp_path):
    code = '''
from PySide6.QtWidgets import QApplication, QWidget
import ui
app = QApplication([])
owner = QWidget()
owner._autonomy_enabled = False
for name in ('_submit_v5_command', '_set_v5_muted', '_request_v5_setup',
             '_request_v5_permissions'):
    setattr(owner, name, lambda *args: True)
owner._request_v5_history = lambda: ui.MainWindow._request_v5_history(owner)
p = ui._HudV5Projection(owner, 'Test owner')
owner._v5_projection = p
for i in range(60):
    p.append_log(f'SYS: entry {i}')
p.append_log('Onyx: Actual latest reply')
assert p.logText.splitlines()[0] == 'Onyx: Actual latest reply'
assert len(p.logText.splitlines()) == 6
assert len(p.historyText.splitlines()) == 48
assert p.transcriptTitle == 'ONYX'
assert p.transcriptText == 'Actual latest reply'
assert p.requestHistory() is True
assert p.contentTitle == 'SESSION ACTIVITY'
assert 'entry 13' in p.contentText
assert 'Actual latest reply' in p.contentText
assert not p.lastCallbackError
owner.deleteLater()
app.processEvents()
print('projection PASS')
'''
    env = dict(os.environ, ONYX_DATA_DIR=str(tmp_path), PYTHONPATH=str(ROOT),
               QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, '-B', '-c', code], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'projection PASS' in result.stdout
