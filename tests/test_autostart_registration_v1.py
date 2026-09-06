"""The login registration must be explicit, honest, and never touch the host."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core import autostart_registration_v1 as autostart


def _runner(returncode=0, stderr="", stdout=""):
    calls: list[list[str]] = []

    def run(command: list[str]) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_nothing_registers_on_import() -> None:
    """Registration changes what happens at login; it is never a side effect."""
    source = Path(autostart.__file__).read_text(encoding="utf-8")
    for forbidden in ("register_autostart()", "schtasks", "launchctl load"):
        assert f"\n{forbidden}" not in source


def test_windows_registers_at_logon() -> None:
    run = _runner()
    outcome = autostart.register_autostart(runner=run, system="Windows")
    assert outcome.registered is True
    command = run.calls[0]  # type: ignore[attr-defined]
    assert "schtasks" == command[0]
    assert "/SC" in command and "ONLOGON" in command
    assert autostart.TASK_NAME in command


def test_windows_failure_is_reported_not_swallowed() -> None:
    """A silent failure is discovered at the next reboot; that is unacceptable."""
    run = _runner(returncode=1, stderr="ERROR: Access is denied.")
    outcome = autostart.register_autostart(runner=run, system="Windows")
    assert outcome.registered is False
    assert "Access is denied" in outcome.detail


def test_windows_status_reflects_the_scheduler() -> None:
    assert autostart.autostart_status(
        runner=_runner(), system="Windows").registered is True
    assert autostart.autostart_status(
        runner=_runner(returncode=1), system="Windows").registered is False


def test_unregister_is_safe_when_absent() -> None:
    outcome = autostart.unregister_autostart(
        runner=_runner(returncode=1), system="Windows")
    assert outcome.registered is False


def test_linux_writes_an_xdg_entry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    outcome = autostart.register_autostart(runner=_runner(), system="Linux")
    entry = tmp_path / "autostart" / "onyx.desktop"
    assert outcome.registered is True and entry.is_file()
    body = entry.read_text(encoding="utf-8")
    assert "Type=Application" in body and "Exec=" in body
    autostart.unregister_autostart(runner=_runner(), system="Linux")
    assert not entry.is_file()


def test_darwin_writes_a_launch_agent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    outcome = autostart.register_autostart(runner=_runner(), system="Darwin")
    plist = tmp_path / "Library" / "LaunchAgents" / f"{autostart.AGENT_LABEL}.plist"
    assert outcome.registered is True and plist.is_file()
    body = plist.read_text(encoding="utf-8")
    assert "<key>RunAtLoad</key>" in body and "<true/>" in body


def test_unsupported_platform_says_so_plainly() -> None:
    outcome = autostart.register_autostart(runner=_runner(), system="Plan9")
    assert outcome.supported is False and outcome.registered is False
    assert "Plan9" in outcome.detail


@pytest.mark.parametrize("system", ["Windows", "Darwin", "Linux"])
def test_the_launch_target_is_always_absolute(system, tmp_path, monkeypatch) -> None:
    """A relative command in a login trigger resolves against the wrong cwd."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    autostart.register_autostart(runner=_runner(), system=system)
    for part in autostart._launch_argv():
        assert Path(part).is_absolute(), part
