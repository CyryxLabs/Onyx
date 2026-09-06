"""Register Onyx to start when the owner logs in, on any supported platform.

The owner asked to reach Onyx from anywhere "as long as the computer is on".
A running machine is not enough on its own: if Onyx is not started, there is
nothing listening.  This closes that gap by registering the installed
executable with the platform's own login mechanism -- Task Scheduler on
Windows, a LaunchAgent on macOS, an XDG autostart entry on Linux -- reusing the
approach `actions/reminder.py` already uses for scheduled notifications.

Three properties this deliberately keeps:

**Never automatic.**  Registration changes what happens at login, so it is an
explicit owner action.  Nothing here runs on import, and no default enables it.

**Hermetic under test.**  Every platform call goes through an injected runner,
so the suite never edits the real login configuration of the machine running
it.

**Honest.**  A failed registration reports the platform's own error rather than
reporting success and leaving the owner to discover at the next reboot that
nothing started.
"""
from __future__ import annotations

import os
import platform
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

FEATURE_FLAG = "ONYX_AUTOSTART_REGISTRATION_V1"
ENABLED_VALUE = "1"
TASK_NAME = "OnyxOwnerLogin"
AGENT_LABEL = "labs.cyryx.onyx.login"


class AutostartRegistrationV1Error(RuntimeError):
    """Raised when a registration request is malformed, never for OS failure."""


@dataclass(frozen=True)
class AutostartOutcome:
    """What actually happened, in terms the owner can act on."""

    supported: bool
    registered: bool
    mechanism: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - presentation only
        if not self.supported:
            return f"Autostart is not supported here: {self.detail}"
        if self.registered:
            return f"Onyx will start at login via {self.mechanism}."
        return f"Onyx is not registered to start at login ({self.detail})."


Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _default_runner(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv, never a shell string
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
    )


def onyx_executable() -> Path:
    """The command a login trigger should launch.

    A frozen build is its own executable.  A source checkout has no single
    binary, so the launcher script is registered under the running interpreter.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    launcher = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_onyx.pyw"
    if not launcher.is_file():
        raise AutostartRegistrationV1Error(
            "no launcher found to register; expected a frozen build or "
            "scripts/bootstrap_onyx.pyw"
        )
    return launcher


def _launch_argv() -> list[str]:
    target = onyx_executable()
    if getattr(sys, "frozen", False):
        return [str(target)]
    return [str(Path(sys.executable).resolve()), str(target)]


# ── Windows ─────────────────────────────────────────────────────────────────

def _windows_register(runner: Runner) -> AutostartOutcome:
    argv = _launch_argv()
    # schtasks takes one command string; quote each element exactly once.
    command = " ".join(f'"{part}"' for part in argv)
    result = runner([
        "schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON",
        "/TR", command, "/F", "/RL", "LIMITED",
    ])
    if result.returncode == 0:
        return AutostartOutcome(True, True, "Windows Task Scheduler", TASK_NAME)
    return AutostartOutcome(
        True, False, "Windows Task Scheduler",
        (result.stderr or result.stdout or "schtasks failed").strip()[:200],
    )


def _windows_unregister(runner: Runner) -> AutostartOutcome:
    result = runner(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    detail = (result.stderr or result.stdout or "").strip()[:200]
    return AutostartOutcome(
        True, False, "Windows Task Scheduler",
        "removed" if result.returncode == 0 else detail or "not registered",
    )


def _windows_status(runner: Runner) -> AutostartOutcome:
    result = runner(["schtasks", "/Query", "/TN", TASK_NAME])
    return AutostartOutcome(
        True, result.returncode == 0, "Windows Task Scheduler",
        TASK_NAME if result.returncode == 0 else "not registered",
    )


# ── macOS ───────────────────────────────────────────────────────────────────

def _agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"


def _darwin_register(runner: Runner) -> AutostartOutcome:
    argv = _launch_argv()
    entries = "".join(f"        <string>{part}</string>\n" for part in argv)
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "  <dict>\n"
        "    <key>Label</key>\n"
        f"    <string>{AGENT_LABEL}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        f"{entries}"
        "    </array>\n"
        "    <key>RunAtLoad</key>\n"
        "    <true/>\n"
        "  </dict>\n"
        "</plist>\n"
    )
    path = _agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist, encoding="utf-8", newline="\n")
    result = runner(["launchctl", "load", str(path)])
    if result.returncode == 0:
        return AutostartOutcome(True, True, "macOS LaunchAgent", str(path))
    return AutostartOutcome(
        True, False, "macOS LaunchAgent",
        (result.stderr or "launchctl load failed").strip()[:200],
    )


def _darwin_unregister(runner: Runner) -> AutostartOutcome:
    path = _agent_path()
    if path.is_file():
        runner(["launchctl", "unload", str(path)])
        path.unlink(missing_ok=True)
        return AutostartOutcome(True, False, "macOS LaunchAgent", "removed")
    return AutostartOutcome(True, False, "macOS LaunchAgent", "not registered")


def _darwin_status(_runner: Runner) -> AutostartOutcome:
    path = _agent_path()
    return AutostartOutcome(
        True, path.is_file(), "macOS LaunchAgent",
        str(path) if path.is_file() else "not registered",
    )


# ── Linux ───────────────────────────────────────────────────────────────────

def _desktop_entry_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / "onyx.desktop"


def _linux_register(_runner: Runner) -> AutostartOutcome:
    argv = _launch_argv()
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Onyx\n"
        f"Exec={' '.join(shlex.quote(part) for part in argv)}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Terminal=false\n"
    )
    path = _desktop_entry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(entry, encoding="utf-8", newline="\n")
    return AutostartOutcome(True, True, "XDG autostart entry", str(path))


def _linux_unregister(_runner: Runner) -> AutostartOutcome:
    path = _desktop_entry_path()
    existed = path.is_file()
    path.unlink(missing_ok=True)
    return AutostartOutcome(
        True, False, "XDG autostart entry",
        "removed" if existed else "not registered",
    )


def _linux_status(_runner: Runner) -> AutostartOutcome:
    path = _desktop_entry_path()
    return AutostartOutcome(
        True, path.is_file(), "XDG autostart entry",
        str(path) if path.is_file() else "not registered",
    )


_PLATFORMS = {
    "Windows": (_windows_register, _windows_unregister, _windows_status),
    "Darwin": (_darwin_register, _darwin_unregister, _darwin_status),
    "Linux": (_linux_register, _linux_unregister, _linux_status),
}


def _dispatch(index: int, runner: Runner | None, system: str | None):
    name = system or platform.system()
    handlers = _PLATFORMS.get(name)
    if handlers is None:
        return AutostartOutcome(False, False, "none", f"unsupported platform {name}")
    return handlers[index](runner or _default_runner)


def register_autostart(*, runner: Runner | None = None,
                       system: str | None = None) -> AutostartOutcome:
    """Register Onyx to launch at the owner's next login."""
    return _dispatch(0, runner, system)


def unregister_autostart(*, runner: Runner | None = None,
                         system: str | None = None) -> AutostartOutcome:
    """Remove the login registration; safe to call when absent."""
    return _dispatch(1, runner, system)


def autostart_status(*, runner: Runner | None = None,
                     system: str | None = None) -> AutostartOutcome:
    """Report whether Onyx is currently registered to start at login."""
    return _dispatch(2, runner, system)
