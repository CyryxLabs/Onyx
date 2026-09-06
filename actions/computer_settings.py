#computer_settings.py
import importlib
import difflib
import os
import re
import time
import subprocess
import platform
from pathlib import Path

from core.undo_journal_v1 import register_undo


def _load_pyautogui():
    """Load desktop automation only when the current session supports it."""
    if (
        platform.system() == "Linux"
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    ):
        return None, "headless_session"
    try:
        module = importlib.import_module("pyautogui")
        module.FAILSAFE = True
        module.PAUSE = 0.05
        return module, None
    except (ImportError, KeyError, OSError) as exc:
        return None, type(exc).__name__


pyautogui = None
_PYAUTOGUI_ERROR = ""
_PYAUTOGUI: bool | None = None

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

if _OS == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}


def _require_pyautogui():
    global pyautogui, _PYAUTOGUI, _PYAUTOGUI_ERROR
    if _PYAUTOGUI is None:
        pyautogui, _PYAUTOGUI_ERROR = _load_pyautogui()
        _PYAUTOGUI = pyautogui is not None
    if not _PYAUTOGUI or pyautogui is None:
        detail = f" ({_PYAUTOGUI_ERROR})" if _PYAUTOGUI_ERROR else ""
        raise RuntimeError(
            "Desktop automation is unavailable in the current desktop session"
            f"{detail}."
        )
    return pyautogui


def _get_macos_wifi_interface() -> str:
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i, min(i + 4, len(lines))):
                    if lines[j].startswith("Device:"):
                        return lines[j].split(":", 1)[1].strip()
    except Exception:
        pass
    return "en0" 

def volume_up():
    if _OS == "Windows":
        for _ in range(5): pyautogui.press("volumeup")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            "set volume output volume (output volume of (get volume settings) + 10)"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"],
            capture_output=True)

def volume_down():
    if _OS == "Windows":
        for _ in range(5): pyautogui.press("volumedown")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            "set volume output volume (output volume of (get volume settings) - 10)"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"],
            capture_output=True)

def volume_mute():
    if _OS == "Windows":
        pyautogui.press("volumemute")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", "set volume with output muted"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
            capture_output=True)

def volume_set(value: int):
    value = max(0, min(100, int(value)))
    if _OS == "Windows":
        try:
            import math
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices   = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol       = cast(interface, POINTER(IAudioEndpointVolume))
            vol_db    = -65.25 if value == 0 else max(-65.25, 20 * math.log10(value / 100))
            vol.SetMasterVolumeLevel(vol_db, None)
            return
        except Exception as e:
            print(f"[Settings] pycaw failed, using keypress fallback: {e}")
            pyautogui.press("volumemute")
            pyautogui.press("volumemute")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", f"set volume output volume {value}"],
            capture_output=True)
        return
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"],
            capture_output=True)
        return


def volume_get() -> int | None:
    """Read the current master volume when the platform exposes it."""

    try:
        if _OS == "Windows":
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            endpoint = AudioUtilities.GetSpeakers().Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None
            )
            volume = cast(endpoint, POINTER(IAudioEndpointVolume))
            return max(0, min(100, round(volume.GetMasterVolumeLevelScalar() * 100)))
        if _OS == "Darwin":
            result = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return max(0, min(100, int(result.stdout.strip())))
        result = subprocess.run(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        match = re.search(r"(\d+)%", result.stdout)
        return max(0, min(100, int(match.group(1)))) if match else None
    except Exception:
        return None


def brightness_get() -> int | None:
    """Read brightness without inventing a value when the OS cannot report it."""

    try:
        if _OS == "Windows":
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance -Namespace root/wmi -ClassName "
                    "WmiMonitorBrightness).CurrentBrightness",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                **_WIN_HIDE,
            )
            values = re.findall(r"\d+", result.stdout)
            return max(0, min(100, int(values[0]))) if values else None
        if _OS == "Linux":
            current = subprocess.run(
                ["brightnessctl", "get"], capture_output=True, text=True, timeout=5
            )
            maximum = subprocess.run(
                ["brightnessctl", "max"], capture_output=True, text=True, timeout=5
            )
            top = int(maximum.stdout.strip())
            return round(int(current.stdout.strip()) * 100 / top) if top else None
    except Exception:
        return None
    return None


def brightness_set(value: int) -> None:
    target = max(0, min(100, int(value)))
    if _OS == "Windows":
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance -Namespace root/wmi -ClassName "
                f"WmiMonitorBrightnessMethods).WmiSetBrightness(1, {target})",
            ],
            capture_output=True,
            timeout=5,
            **_WIN_HIDE,
        )
    elif _OS == "Linux":
        subprocess.run(
            ["brightnessctl", "set", f"{target}%"], capture_output=True, timeout=5
        )


def _adjust_xrandr_brightness(delta: float) -> bool:
    """Adjust the first connected X11 output without invoking a shell."""
    try:
        state = subprocess.run(
            ["xrandr", "--verbose"], capture_output=True, text=True, timeout=5
        )
        output_match = re.search(r"^(\S+)\s+connected\b", state.stdout, re.MULTILINE)
        brightness_match = re.search(r"^\s*Brightness:\s*([0-9.]+)", state.stdout, re.MULTILINE)
        if state.returncode != 0 or not output_match or not brightness_match:
            return False
        current = float(brightness_match.group(1))
        target = max(0.1, min(1.0, current + delta))
        result = subprocess.run(
            ["xrandr", "--output", output_match.group(1), "--brightness", str(target)],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, OSError, ValueError, subprocess.SubprocessError):
        return False

def brightness_up():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to key code 144'],
            capture_output=True)
    elif _OS == "Linux":
        if subprocess.run(["which", "brightnessctl"],
                capture_output=True).returncode == 0:
            subprocess.run(["brightnessctl", "set", "+10%"], capture_output=True)
        else:
            _adjust_xrandr_brightness(0.1)
    else:
        try:
            subprocess.run(  # noqa: S602 - fixed command, no user input
                ["powershell", "-Command",
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
                 ".WmiSetBrightness(1, [math]::Min(100, "
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness + 10))"],
                capture_output=True, timeout=5, **_WIN_HIDE
            )
        except Exception as e:
            print(f"[Settings] Brightness up failed on Windows: {e}")

def brightness_down():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to key code 145'],
            capture_output=True)
    elif _OS == "Linux":
        if subprocess.run(["which", "brightnessctl"],
                capture_output=True).returncode == 0:
            subprocess.run(["brightnessctl", "set", "10%-"], capture_output=True)
        else:
            _adjust_xrandr_brightness(-0.1)
    else:
        try:
            subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
                 ".WmiSetBrightness(1, [math]::Max(0, "
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness - 10))"],
                capture_output=True, timeout=5, **_WIN_HIDE
            )
        except Exception as e:
            print(f"[Settings] Brightness down failed on Windows: {e}")

def close_app():
    if _OS == "Darwin": pyautogui.hotkey("command", "q")
    else:               pyautogui.hotkey("alt", "f4")

def close_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")

def full_screen():
    if _OS == "Darwin": pyautogui.hotkey("ctrl", "command", "f")
    else:               pyautogui.press("f11")

def minimize_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "m")
    else:               pyautogui.hotkey("win", "down")

def maximize_window():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to keystroke "f" '
            'using {control down, command down}'],
            capture_output=True)
    elif _OS == "Windows":
        pyautogui.hotkey("win", "up")
    else:
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b", "add,maximized_vert,maximized_horz"],
                capture_output=True)
        except Exception:
            pyautogui.hotkey("super", "up")

def snap_left():
    if _OS == "Windows":
        pyautogui.hotkey("win", "left")
    elif _OS == "Linux":
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", "0,0,0,960,1080"],
                capture_output=True)
        except Exception:
            pass

def snap_right():
    if _OS == "Windows":
        pyautogui.hotkey("win", "right")
    elif _OS == "Linux":
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", "0,960,0,960,1080"],
                capture_output=True)
        except Exception:
            pass

def switch_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "tab")
    else:               pyautogui.hotkey("alt", "tab")

def show_desktop():
    if _OS == "Darwin":   pyautogui.hotkey("fn", "f11")
    elif _OS == "Windows": pyautogui.hotkey("win", "d")
    else:                  pyautogui.hotkey("super", "d")

def open_task_manager():
    if _OS == "Windows":
        pyautogui.hotkey("ctrl", "shift", "esc")
    elif _OS == "Darwin":
        subprocess.Popen(["open", "-a", "Activity Monitor"])
    else:
        for cmd in [["gnome-system-monitor"], ["xfce4-taskmanager"], ["htop"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                break


def focus_search():
    if _OS == "Darwin": pyautogui.hotkey("command", "l")
    else:               pyautogui.hotkey("ctrl", "l")

def pause_video():      pyautogui.press("space")

def refresh_page():
    if _OS == "Darwin": pyautogui.hotkey("command", "r")
    else:               pyautogui.press("f5")

def close_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")

def new_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "t")
    else:               pyautogui.hotkey("ctrl", "t")

def next_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "bracketright")
    else:               pyautogui.hotkey("ctrl", "tab")

def prev_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "bracketleft")
    else:               pyautogui.hotkey("ctrl", "shift", "tab")

def go_back():
    if _OS == "Darwin": pyautogui.hotkey("command", "left")
    else:               pyautogui.hotkey("alt", "left")

def go_forward():
    if _OS == "Darwin": pyautogui.hotkey("command", "right")
    else:               pyautogui.hotkey("alt", "right")

def zoom_in():
    if _OS == "Darwin": pyautogui.hotkey("command", "equal")
    else:               pyautogui.hotkey("ctrl", "equal")

def zoom_out():
    if _OS == "Darwin": pyautogui.hotkey("command", "minus")
    else:               pyautogui.hotkey("ctrl", "minus")

def zoom_reset():
    if _OS == "Darwin": pyautogui.hotkey("command", "0")
    else:               pyautogui.hotkey("ctrl", "0")

def find_on_page():
    if _OS == "Darwin": pyautogui.hotkey("command", "f")
    else:               pyautogui.hotkey("ctrl", "f")

def reload_page_n(n: int):
    for _ in range(max(1, n)):
        refresh_page()
        time.sleep(0.8)


def scroll_up(amount: int = 500):    pyautogui.scroll(amount)
def scroll_down(amount: int = 500):  pyautogui.scroll(-amount)

def scroll_top():
    if _OS == "Darwin": pyautogui.hotkey("command", "up")
    else:               pyautogui.hotkey("ctrl", "home")

def scroll_bottom():
    if _OS == "Darwin": pyautogui.hotkey("command", "down")
    else:               pyautogui.hotkey("ctrl", "end")

def page_up():   pyautogui.press("pageup")
def page_down(): pyautogui.press("pagedown")


def copy():
    if _OS == "Darwin": pyautogui.hotkey("command", "c")
    else:               pyautogui.hotkey("ctrl", "c")

def paste():
    if _OS == "Darwin": pyautogui.hotkey("command", "v")
    else:               pyautogui.hotkey("ctrl", "v")

def cut():
    if _OS == "Darwin": pyautogui.hotkey("command", "x")
    else:               pyautogui.hotkey("ctrl", "x")

def undo():
    if _OS == "Darwin": pyautogui.hotkey("command", "z")
    else:               pyautogui.hotkey("ctrl", "z")

def redo():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "z")
    else:               pyautogui.hotkey("ctrl", "y")

def select_all():
    if _OS == "Darwin": pyautogui.hotkey("command", "a")
    else:               pyautogui.hotkey("ctrl", "a")

def save_file():
    if _OS == "Darwin": pyautogui.hotkey("command", "s")
    else:               pyautogui.hotkey("ctrl", "s")

def press_enter():   pyautogui.press("enter")
def press_escape():  pyautogui.press("escape")
def press_key(key: str): pyautogui.press(key)

def type_text(text: str, press_enter_after: bool = False):
    if not text:
        return
    if _PYPERCLIP:
        pyperclip.copy(str(text))
        time.sleep(0.15)
        paste()
    else:
        pyautogui.write(str(text), interval=0.03)
    if press_enter_after:
        time.sleep(0.1)
        pyautogui.press("enter")

def take_screenshot():
    if _OS == "Windows":
        pyautogui.hotkey("win", "shift", "s")
    elif _OS == "Darwin":
        pyautogui.hotkey("command", "shift", "3")
    else:
        for cmd in [["scrot"], ["gnome-screenshot"], ["import", "-window", "root", "screenshot.png"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return
        pyautogui.hotkey("ctrl", "print_screen")

def lock_screen():
    if _OS == "Windows":
        pyautogui.hotkey("win", "l")
    elif _OS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    else:
        for cmd in [
            ["gnome-screensaver-command", "-l"],
            ["xdg-screensaver", "lock"],
            ["loginctl", "lock-session"],
        ]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.run(cmd, capture_output=True)
                return

def open_system_settings():
    if _OS == "Windows":
        pyautogui.hotkey("win", "i")
    elif _OS == "Darwin":
        subprocess.Popen(["open", "-a", "System Preferences"])
    else:
        for cmd in [["gnome-control-center"], ["xfce4-settings-manager"], ["kcmshell5"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return

def open_file_explorer():
    if _OS == "Windows":
        pyautogui.hotkey("win", "e")
    elif _OS == "Darwin":
        subprocess.Popen(["open", str(Path.home())])
    else:
        for cmd in [["nautilus"], ["thunar"], ["dolphin"], ["nemo"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return
        subprocess.Popen(["xdg-open", str(Path.home())])

def sleep_display():
    if _OS == "Windows":
        try:
            import ctypes
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        except Exception as e:
            print(f"[Settings] sleep_display failed: {e}")
    elif _OS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    else:
        subprocess.run(["xset", "dpms", "force", "off"], capture_output=True)

def open_run():
    if _OS == "Windows":
        pyautogui.hotkey("win", "r")

def dark_mode():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell app "System Events" to tell appearance preferences '
            'to set dark mode to not dark mode'],
            capture_output=True)
    elif _OS == "Windows":
        try:
            import winreg
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            current, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 1 - current)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 1 - current)
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[Settings] dark_mode registry failed: {e}")
    else:
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True
            )
            current = result.stdout.strip()
            new_scheme = "'default'" if "dark" in current else "'prefer-dark'"
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", new_scheme],
                capture_output=True
            )
        except Exception as e:
            print(f"[Settings] dark_mode Linux failed: {e}")


def dark_mode_get() -> bool | None:
    try:
        if _OS == "Windows":
            import winreg

            path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                current, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(current) == 0
        if _OS == "Darwin":
            result = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to tell appearance preferences to get dark mode',
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip().casefold() == "true"
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "dark" in result.stdout.casefold()
    except Exception:
        return None


def dark_mode_set(enabled: bool) -> None:
    if _OS == "Windows":
        import winreg

        path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS
        ) as key:
            value = 0 if enabled else 1
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, value)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, value)
    elif _OS == "Darwin":
        value = "true" if enabled else "false"
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to tell appearance preferences '
                f"to set dark mode to {value}",
            ],
            capture_output=True,
            timeout=5,
        )
    else:
        scheme = "prefer-dark" if enabled else "default"
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", scheme],
            capture_output=True,
            timeout=5,
        )


def _restore_observed_setting(
    label: str,
    read,
    write,
    expected_current,
    previous,
) -> str:
    current = read()
    if current != expected_current:
        raise RuntimeError(f"{label} changed after Onyx acted; leaving it untouched")
    write(previous)
    return f"{label.title()} restored to {previous}."

def toggle_wifi():
    if _OS == "Darwin":
        iface = _get_macos_wifi_interface()
        result = subprocess.run(
            ["networksetup", "-getairportpower", iface],
            capture_output=True, text=True
        )
        state = "off" if "On" in result.stdout else "on"
        subprocess.run(["networksetup", "-setairportpower", iface, state],
            capture_output=True)
    elif _OS == "Windows":
        try:
            subprocess.run(
                ["powershell", "-Command",
                 "$adapter = Get-NetAdapter | Where-Object {$_.PhysicalMediaType -eq 'Native 802.11'};"
                 "if ($adapter.Status -eq 'Up') { Disable-NetAdapter -Name $adapter.Name -Confirm:$false }"
                 "else { Enable-NetAdapter -Name $adapter.Name -Confirm:$false }"],
                capture_output=True, timeout=10, **_WIN_HIDE
            )
        except Exception as e:
            print(f"[Settings] toggle_wifi Windows failed: {e}")
    else:
        try:
            result = subprocess.run(["nmcli", "radio", "wifi"], capture_output=True, text=True)
            state  = "off" if "enabled" in result.stdout else "on"
            subprocess.run(["nmcli", "radio", "wifi", state], capture_output=True)
        except Exception as e:
            print(f"[Settings] toggle_wifi Linux failed: {e}")

def restart_computer():
    if _OS == "Windows":
        subprocess.run(["shutdown", "/r", "/t", "10"], capture_output=True, **_WIN_HIDE)
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to restart'],
            capture_output=True)
    else:
        subprocess.run(["systemctl", "reboot"], capture_output=True)

def shutdown_computer():
    if _OS == "Windows":
        subprocess.run(["shutdown", "/s", "/t", "10"], capture_output=True)
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to shut down'],
            capture_output=True)
    else:
        subprocess.run(["systemctl", "poweroff"], capture_output=True)

ACTION_MAP: dict[str, callable] = {
    "volume_up":           volume_up,
    "volume_down":         volume_down,
    "mute":                volume_mute,
    "unmute":              volume_mute,
    "toggle_mute":         volume_mute,
    "brightness_up":       brightness_up,
    "brightness_down":     brightness_down,
    "sleep_display":       sleep_display,
    "screen_off":          sleep_display,
    "pause_video":         pause_video,
    "play_pause":          pause_video,
    "close_app":           close_app,
    "close_window":        close_window,
    "full_screen":         full_screen,
    "fullscreen":          full_screen,
    "minimize":            minimize_window,
    "maximize":            maximize_window,
    "snap_left":           snap_left,
    "snap_right":          snap_right,
    "switch_window":       switch_window,
    "show_desktop":        show_desktop,
    "task_manager":        open_task_manager,
    "focus_search":        focus_search,
    "refresh_page":        refresh_page,
    "reload":              refresh_page,
    "close_tab":           close_tab,
    "new_tab":             new_tab,
    "next_tab":            next_tab,
    "prev_tab":            prev_tab,
    "go_back":             go_back,
    "go_forward":          go_forward,
    "zoom_in":             zoom_in,
    "zoom_out":            zoom_out,
    "zoom_reset":          zoom_reset,
    "find_on_page":        find_on_page,
    "scroll_up":           scroll_up,
    "scroll_down":         scroll_down,
    "scroll_top":          scroll_top,
    "scroll_bottom":       scroll_bottom,
    "page_up":             page_up,
    "page_down":           page_down,
    "copy":                copy,
    "paste":               paste,
    "cut":                 cut,
    "undo":                undo,
    "redo":                redo,
    "select_all":          select_all,
    "save":                save_file,
    "enter":               press_enter,
    "escape":              press_escape,
    "screenshot":          take_screenshot,
    "lock_screen":         lock_screen,
    "open_settings":       open_system_settings,
    "file_explorer":       open_file_explorer,
    "open_run":            open_run,
    "dark_mode":           dark_mode,
    "toggle_wifi":         toggle_wifi,
    "restart":             restart_computer,
    "shutdown":            shutdown_computer,
}

_DESCRIPTION_ALIASES: dict[str, tuple[str, ...]] = {
    "volume_up": ("louder", "raise volume", "turn it up", "aumentar volume", "mais alto"),
    "volume_down": ("quieter", "lower volume", "turn it down", "baixar volume", "mais baixo"),
    "mute": ("silence", "sound off", "no sound", "silenciar", "sem som"),
    "brightness_up": ("brighter", "increase brightness", "aumentar brilho"),
    "brightness_down": ("dimmer", "lower brightness", "diminuir brilho"),
    "close_window": ("close this", "close it", "fechar janela", "feche isso"),
    "full_screen": ("fullscreen", "tela cheia"),
    "show_desktop": ("go to desktop", "mostrar area de trabalho"),
    "lock_screen": ("lock computer", "lock the pc", "bloquear computador"),
    "sleep_display": ("screen off", "display off", "desligar tela"),
    "dark_mode": ("night mode", "light mode", "toggle theme", "modo escuro"),
    "toggle_wifi": ("wifi", "wi-fi", "internet off", "internet on", "alternar wifi"),
    "task_manager": ("task list", "processes", "gerenciador de tarefas"),
    "screenshot": ("capture screen", "take a screenshot", "capturar tela"),
    "refresh_page": ("refresh", "reload page", "atualizar pagina"),
    "new_tab": ("open new tab", "nova aba"),
    "shutdown": ("power off", "turn off computer", "desligar computador"),
    "restart": ("reboot", "restart computer", "reiniciar computador"),
}


def _normalized_action_text(value: object) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value).casefold())).strip("_")


def resolve_computer_settings_description(description: object) -> tuple[str, object | None]:
    """Resolve bounded local wording without a second model/API round trip."""

    raw = str(description or "").strip()
    normalized = _normalized_action_text(raw)
    if not normalized:
        return "", None
    known = set(ACTION_MAP) | {
        "volume_set", "type_text", "press_key", "reload_n", "scroll_up", "scroll_down"
    }
    if normalized in known:
        return normalized, None
    lowered = raw.casefold()
    amount = re.search(r"(\d{1,3})\s*%?", lowered)
    if amount and any(word in lowered for word in ("volume", "sound", "som", "audio", "áudio")):
        return "volume_set", max(0, min(100, int(amount.group(1))))
    for action, phrases in _DESCRIPTION_ALIASES.items():
        if any(phrase in lowered for phrase in phrases):
            return action, None
    close = difflib.get_close_matches(normalized, sorted(known), n=1, cutoff=0.72)
    return (close[0], None) if close else ("", None)


def materialize_computer_settings_request(parameters: dict | None) -> dict:
    """Bind a description-only request to one exact action before authorization."""

    result = dict(parameters or {})
    raw_action = str(result.get("action", "")).strip()
    if not raw_action:
        action, detected_value = resolve_computer_settings_description(
            result.get("description", "")
        )
        if action:
            result["action"] = action
        if result.get("value") is None and detected_value is not None:
            result["value"] = detected_value
    return result

def computer_settings(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params      = materialize_computer_settings_request(parameters)
    raw_action  = params.get("action", "").strip()
    value       = params.get("value", None)

    action = raw_action.lower().strip().replace(" ", "_").replace("-", "_")

    if not action:
        return "No explicit action provided."

    # Login registration is answered before the desktop-automation gate: it
    # needs no pointer or keyboard, and refusing it in a headless session would
    # be wrong.
    if action in ("enable_autostart", "disable_autostart", "autostart_status"):
        from core.autostart_registration_v1 import (
            autostart_status,
            register_autostart,
            unregister_autostart,
        )

        handler = {
            "enable_autostart": register_autostart,
            "disable_autostart": unregister_autostart,
            "autostart_status": autostart_status,
        }[action]
        try:
            return str(handler())
        except Exception as error:  # noqa: BLE001 - report, never crash the tool
            return f"Could not change the login registration: {error}"

    try:
        _require_pyautogui()
    except RuntimeError:
        detail = f" ({_PYAUTOGUI_ERROR})" if _PYAUTOGUI_ERROR else ""
        return f"Desktop automation is unavailable in the current desktop session{detail}."

    print(f"[Settings] Action: {action}  Value: {value}  OS: {_OS}")
    if player:
        player.write_log(f"[Settings] {action}")

    if action == "volume_set":
        try:
            target = int(value or 50)
            before = volume_get()
            volume_set(target)
            after = volume_get()
            if before is not None and after is not None:
                register_undo(
                    f"set volume from {before}% to {target}%",
                    lambda prior=before, expected=after: _restore_observed_setting(
                        "volume", volume_get, volume_set, expected, prior
                    ),
                )
            return f"Volume set to {target}%."
        except Exception as e:
            return f"Could not set volume: {e}"

    if action in ("type_text", "write_on_screen", "type", "write"):
        text = str(value or params.get("text", "")).strip()
        if not text:
            return "No text provided to type."
        enter_after = str(params.get("press_enter", "false")).lower() in ("true", "1", "yes")
        type_text(text, press_enter_after=enter_after)
        return f"Typed: {text[:80]}"

    if action == "press_key":
        key = str(value or params.get("key", "")).strip()
        if not key:
            return "No key specified."
        press_key(key)
        return f"Pressed: {key}"

    if action in ("reload_n", "refresh_n", "reload_page_n"):
        try:
            reload_page_n(int(value or 1))
            return f"Reloaded {value or 1} time(s)."
        except Exception as e:
            return f"Reload failed: {e}"

    if action == "scroll_up":
        scroll_up(int(value or 500))
        return "Scrolled up."

    if action == "scroll_down":
        scroll_down(int(value or 500))
        return "Scrolled down."

    func = ACTION_MAP.get(action)
    if not func:
        return f"Unknown action: '{raw_action}'."

    before_setting: tuple[str, int] | None = None
    if action in {"volume_up", "volume_down"}:
        prior_volume = volume_get()
        if prior_volume is not None:
            before_setting = ("volume", prior_volume)
    elif action in {"brightness_up", "brightness_down"}:
        prior_brightness = brightness_get()
        if prior_brightness is not None:
            before_setting = ("brightness", prior_brightness)
    elif action == "dark_mode":
        prior_dark_mode = dark_mode_get()
        if prior_dark_mode is not None:
            before_setting = ("dark_mode", prior_dark_mode)

    try:
        func()
    except Exception as e:
        print(f"[Settings] Action failed ({action}): {e}")
        return f"Action failed ({action}): {e}"

    if before_setting is not None:
        setting, prior = before_setting
        if setting == "volume":
            after = volume_get()
            if after is not None:
                register_undo(
                    f"changed volume ({action})",
                    lambda value=prior, expected=after: _restore_observed_setting(
                        "volume", volume_get, volume_set, expected, value
                    ),
                )
        elif setting == "brightness":
            after = brightness_get()
            if after is not None:
                register_undo(
                    f"changed brightness ({action})",
                    lambda value=prior, expected=after: _restore_observed_setting(
                        "brightness", brightness_get, brightness_set, expected, value
                    ),
                )
        else:
            after = dark_mode_get()
            if after is not None:
                register_undo(
                    "toggled operating-system dark mode",
                    lambda value=prior, expected=after: _restore_observed_setting(
                        "dark mode", dark_mode_get, dark_mode_set, expected, value
                    ),
                )
    elif action == "dark_mode":
        # If the OS cannot read the previous state, no reversal is registered.
        # A guessed theme change is more dangerous than no undo entry.
        pass

    return f"Done: {action}."
