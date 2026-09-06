from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import monitor_windows_long_session as monitor


def test_atomic_evidence_replace_retries_transient_reader_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "receipt.json"
    destination.write_text("old", encoding="utf-8")
    temporary = tmp_path / "receipt.json.tmp"
    temporary.write_text("new", encoding="utf-8")
    real_replace = Path.replace
    calls = 0

    def flaky_replace(self: Path, target: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("simulated reader lock")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr(monitor.time, "sleep", lambda _delay: None)

    monitor._replace_with_retry(temporary, destination)

    assert calls == 3
    assert destination.read_text(encoding="utf-8") == "new"


def test_atomic_evidence_replace_fails_closed_after_retry_budget(
    monkeypatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "receipt.json"
    temporary = tmp_path / "receipt.json.tmp"
    temporary.write_text("new", encoding="utf-8")

    def locked_replace(_self: Path, _target: Path) -> Path:
        raise PermissionError("persistent reader lock")

    monkeypatch.setattr(Path, "replace", locked_replace)
    monkeypatch.setattr(monitor.time, "sleep", lambda _delay: None)

    with pytest.raises(PermissionError, match="persistent reader lock"):
        monitor._replace_with_retry(temporary, destination, attempts=3)

    assert temporary.read_text(encoding="utf-8") == "new"


def test_rotation_gate_requires_observed_voice_channels() -> None:
    class Args:
        rotation_receives = 0
        microphone_starts = 0
        playback_starts = 0
        rotation_application_errors = 0

    args = Args()
    assert monitor._rotation_gate_proven(args) is False

    args.rotation_receives = 1
    args.microphone_starts = 1
    args.playback_starts = 1
    assert monitor._rotation_gate_proven(args) is True


@pytest.mark.skipif(os.name != "nt", reason="Windows window health contract")
def test_hidden_resident_onyx_window_is_responsive(monkeypatch) -> None:
    class User32:
        def GetWindowThreadProcessId(self, _hwnd, owner) -> None:
            owner._obj.value = 41

        def EnumWindows(self, callback, parameter) -> None:
            callback(1001, parameter)
            callback(1002, parameter)

        def IsHungAppWindow(self, _hwnd) -> int:
            return 0

        def IsWindowVisible(self, _hwnd) -> int:
            raise AssertionError("visibility must not define resident health")

    monkeypatch.setattr(monitor.ctypes.windll, "user32", User32())
    assert monitor._process_responding(41) is True


@pytest.mark.skipif(os.name != "nt", reason="Windows window health contract")
def test_any_hung_process_window_fails_responsiveness(monkeypatch) -> None:
    class User32:
        def GetWindowThreadProcessId(self, _hwnd, owner) -> None:
            owner._obj.value = 41

        def EnumWindows(self, callback, parameter) -> None:
            callback(1001, parameter)
            callback(1002, parameter)

        def IsHungAppWindow(self, hwnd) -> int:
            return int(hwnd == 1002)

    monkeypatch.setattr(monitor.ctypes.windll, "user32", User32())
    assert monitor._process_responding(41) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows window health contract")
def test_process_without_top_level_window_fails_responsiveness(monkeypatch) -> None:
    class User32:
        def EnumWindows(self, _callback, _parameter) -> None:
            return None

    monkeypatch.setattr(monitor.ctypes.windll, "user32", User32())
    assert monitor._process_responding(41) is False
