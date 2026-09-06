"""Validate or repair Windows Onyx shortcuts after a packaged install.

The release contract permits only the installed ``Onyx.exe`` as the Desktop
and Start Menu target. Repository virtualenvs and versioned bootstraps are
explicitly rejected so an upgrade cannot reopen an older source checkout.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Final


class ShortcutContractError(RuntimeError):
    """Raised when a release shortcut does not target the installed binary."""


EXPECTED_EXECUTABLE: Final = "Onyx.exe"


def _normalized(path: object) -> str:
    value = os.path.expandvars(str(path or "").strip().strip('"'))
    return os.path.normcase(os.path.abspath(value)) if value else ""


def validate_shortcut_values(
    *,
    target: object,
    arguments: object,
    working_directory: object,
    install_root: Path,
) -> None:
    expected_root = install_root.resolve()
    expected_target = expected_root / EXPECTED_EXECUTABLE
    if _normalized(target) != _normalized(expected_target):
        raise ShortcutContractError(
            "Onyx shortcut target is not the installed executable"
        )
    if str(arguments or "").strip():
        raise ShortcutContractError("Onyx release shortcut arguments must be empty")
    if _normalized(working_directory) != _normalized(expected_root):
        raise ShortcutContractError(
            "Onyx shortcut working directory is not the install root"
        )


def _default_install_root() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        raise ShortcutContractError("LOCALAPPDATA is required")
    return Path(local) / "Programs" / "Cyryx Labs" / "Onyx"


def verify_installed_shortcuts(
    install_root: Path,
    *,
    repair_desktop: bool = False,
    shell: object | None = None,
) -> dict[str, object]:
    if os.name != "nt" and shell is None:
        raise ShortcutContractError("Windows shortcut verification requires Windows")
    root = install_root.resolve()
    executable = root / EXPECTED_EXECUTABLE
    if not executable.is_file():
        raise ShortcutContractError(f"installed Onyx executable is missing: {executable}")
    if shell is None:
        from win32com.client import Dispatch  # type: ignore

        shell = Dispatch("WScript.Shell")
    desktop_value = shell.SpecialFolders("Desktop")
    if not desktop_value:
        raise ShortcutContractError("active Windows Desktop is unavailable")
    appdata = os.environ.get("APPDATA", "").strip()
    if not appdata:
        raise ShortcutContractError("APPDATA is required")
    links = {
        "desktop": Path(str(desktop_value)) / "Onyx.lnk",
        "start_menu": (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Cyryx Labs"
            / "Onyx"
            / "Onyx.lnk"
        ),
    }
    results: dict[str, str] = {}
    for name, path in links.items():
        if name == "desktop" and repair_desktop:
            path.parent.mkdir(parents=True, exist_ok=True)
            shortcut = shell.CreateShortcut(str(path))
            shortcut.TargetPath = str(executable)
            shortcut.Arguments = ""
            shortcut.WorkingDirectory = str(root)
            shortcut.IconLocation = f"{executable},0"
            shortcut.Save()
        if not path.is_file():
            raise ShortcutContractError(f"Onyx {name} shortcut is missing: {path}")
        shortcut = shell.CreateShortcut(str(path))
        validate_shortcut_values(
            target=shortcut.TargetPath,
            arguments=shortcut.Arguments,
            working_directory=shortcut.WorkingDirectory,
            install_root=root,
        )
        results[name] = str(path)
    return {
        "contract": "OnyxWindowsReleaseShortcuts.v1",
        "install_root": str(root),
        "executable": str(executable),
        "repaired_desktop": repair_desktop,
        "shortcuts": results,
        "status": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-root", type=Path, default=_default_install_root())
    parser.add_argument("--repair-desktop", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            verify_installed_shortcuts(
                args.install_root,
                repair_desktop=args.repair_desktop,
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
