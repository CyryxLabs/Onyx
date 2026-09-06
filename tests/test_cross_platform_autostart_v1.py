from __future__ import annotations

import plistlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_linux_user_unit_is_bounded_and_package_owned() -> None:
    unit = (ROOT / "packaging/linux/onyx.service").read_text(encoding="utf-8")
    assert "ExecStart=/opt/cyryx-labs/onyx/Onyx" in unit
    assert "WantedBy=default.target" in unit
    assert "Restart=no" in unit
    assert "User=root" not in unit
    assert "/bin/sh" not in unit
    build = (ROOT / "scripts/build_release.py").read_text(encoding="utf-8")
    assert '"packaging/linux/onyx.service"' in build
    assert 'root / "usr" / "lib" / "systemd" / "user"' in build
    assert '"./usr/lib/systemd/user/onyx.service"' in build


def test_macos_launch_agent_is_exact_app_login_item() -> None:
    path = ROOT / "packaging/macos/labs.cyryx.onyx.plist"
    payload = plistlib.loads(path.read_bytes())
    assert payload == {
        "Label": "labs.cyryx.onyx",
        "ProgramArguments": ["/Applications/Onyx.app/Contents/MacOS/Onyx"],
        "LimitLoadToSessionType": "Aqua",
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Interactive",
    }
    spec = (ROOT / "packaging/onyx.spec").read_text(encoding="utf-8")
    assert '"macos" / "labs.cyryx.onyx.plist"' in spec
    assert '"autostart"' in spec


def test_native_lifecycle_gates_enable_observe_and_remove_autostart() -> None:
    linux = (ROOT / "scripts/linux_lifecycle_validation.py").read_text(
        encoding="utf-8"
    )
    macos = (ROOT / "scripts/macos_lifecycle_validation.py").read_text(
        encoding="utf-8"
    )
    for token in (
        '"--user", "enable", "--now", "onyx.service"',
        '"--user", "is-active", "onyx.service"',
        '"--user", "disable", "--now", "onyx.service"',
    ):
        assert token in linux
    for token in (
        '"launchctl", "bootstrap"',
        '"launchctl", "print"',
        '"launchctl", "bootout"',
        "final_launch_agent_removed",
    ):
        assert token in macos


def test_windows_autostart_is_owner_opt_in_user_scoped_and_reversible() -> None:
    installer = (ROOT / "packaging/windows/onyx.iss").read_text(encoding="utf-8")
    assert 'Name: "autostart"' in installer
    assert 'Flags: unchecked' in installer
    assert 'Root: HKCU' in installer
    assert 'Software\\Microsoft\\Windows\\CurrentVersion\\Run' in installer
    assert 'ValueName: "Cyryx Labs Onyx"' in installer
    assert 'ValueData: """{app}\\Onyx.exe"""' in installer
    assert 'Flags: uninsdeletevalue; Tasks: autostart' in installer
    assert "Root: HKLM" not in installer
    assert "runascurrentuser" not in installer
