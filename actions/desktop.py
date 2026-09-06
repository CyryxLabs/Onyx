#desktop.py
import os
import re
import json
import subprocess
import tempfile
import platform
from pathlib import Path
from datetime import datetime


def _applescript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

def _get_desktop() -> Path:
    # Honour Windows Known Folder redirection (OneDrive) as well as XDG.
    from core.paths import user_desktop_dir

    return user_desktop_dir()

def set_wallpaper(image_path: str) -> str:
    raw_path = str(image_path).strip()
    normalized = raw_path.replace("/", "\\")
    if (
        normalized.startswith("\\\\")
        or normalized.lower().startswith(("file:", "smb:", "nfs:"))
        or re.match(r"^[a-zA-Z]+://", raw_path)
    ):
        return "Network, UNC, device, and URL wallpaper paths are not allowed."
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        return f"Image not found: {image_path}"
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        return f"Unsupported format: {path.suffix}. Use jpg, png, bmp or webp."

    try:
        if _OS == "Windows":
            import ctypes
            if path.suffix.lower() in {".webp", ".png"}:
                try:
                    from PIL import Image
                    fd, bmp_name = tempfile.mkstemp(suffix=".bmp")
                    os.close(fd)
                    bmp_path = Path(bmp_name)
                    Image.open(path).convert("RGB").save(bmp_path, "BMP")
                    path = bmp_path
                except ImportError:
                    pass
            ctypes.windll.user32.SystemParametersInfoW(20, 0, str(path), 3)
            return f"Wallpaper set: {path.name}"

        elif _OS == "Darwin":
            escaped_path = _applescript_string(str(path))
            script = (
                f'tell application "System Events" to tell every desktop to '
                f'set picture to POSIX file "{escaped_path}"'
            )
            subprocess.run(["osascript", "-e", script], capture_output=True)
            return f"Wallpaper set: {path.name}"

        else:
            desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
            uri = f"file://{path}"

            if "gnome" in desktop_env or "unity" in desktop_env:
                subprocess.run([
                    "gsettings", "set", "org.gnome.desktop.background",
                    "picture-uri", uri
                ], capture_output=True)
                subprocess.run([
                    "gsettings", "set", "org.gnome.desktop.background",
                    "picture-uri-dark", uri
                ], capture_output=True)

            elif "kde" in desktop_env:
                # KDE Plasma
                js_uri = json.dumps(uri)
                script = f"""
var allDesktops = desktops();
for (var i = 0; i < allDesktops.length; i++) {{
    d = allDesktops[i];
    d.wallpaperPlugin = "org.kde.image";
    d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    d.writeConfig("Image", {js_uri});
}}
"""
                subprocess.run(
                    ["qdbus", "org.kde.plasmashell", "/PlasmaShell",
                     "org.kde.PlasmaShell.evaluateScript", script],
                    capture_output=True
                )

            elif "xfce" in desktop_env:
                subprocess.run([
                    "xfconf-query", "-c", "xfce4-desktop",
                    "-p", "/backdrop/screen0/monitor0/workspace0/last-image",
                    "-s", str(path)
                ], capture_output=True)

            else:
                result = subprocess.run(
                    ["feh", "--bg-scale", str(path)],
                    capture_output=True
                )
                if result.returncode != 0:
                    return (
                        f"Could not set wallpaper automatically on {desktop_env}. "
                        f"Try manually or install 'feh'."
                    )

            return f"Wallpaper set: {path.name}"

    except Exception as e:
        return f"Could not set wallpaper: {e}"


def set_wallpaper_from_url(url: str) -> str:
    del url
    return (
        "Remote wallpaper URLs are disabled to prevent network request forgery. "
        "Download the image yourself, then use the wallpaper action with a local file path."
    )


def get_current_wallpaper() -> str:
    try:
        if _OS == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop"
            )
            val, _ = winreg.QueryValueEx(key, "Wallpaper")
            winreg.CloseKey(key)
            return f"Current wallpaper: {val}"

        elif _OS == "Darwin":
            script = (
                'tell application "System Events" to get picture of desktop 1'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True
            )
            return f"Current wallpaper: {result.stdout.strip()}"

        else:
            desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
            if "gnome" in desktop_env or "unity" in desktop_env:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.background", "picture-uri"],
                    capture_output=True, text=True
                )
                return f"Current wallpaper: {result.stdout.strip()}"
            return "Wallpaper path retrieval not supported for this desktop environment."

    except Exception as e:
        return f"Could not get wallpaper: {e}"

FILE_TYPE_MAP = {
    "Images":      {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
    "Documents":   {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                    ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
    "Videos":      {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
    "Music":       {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
    "Archives":    {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Code":        {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                    ".cpp", ".java", ".cs", ".go", ".rs", ".sh", ".php"},
    "Executables": {".exe", ".msi", ".bat", ".cmd", ".sh", ".appimage", ".deb", ".rpm"},
}

_SKIP_EXTENSIONS = {
    "Windows": {".lnk", ".url"},
    "Darwin":  {".webloc"},
    "Linux":   {".desktop"},
}


def _is_link_or_reparse(path: Path) -> bool:
    """Inspect a path without accepting symlinks, junctions, or reparse points."""
    try:
        info = path.lstat()
    except OSError:
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(
        path.is_symlink()
        or (is_junction is not None and is_junction(path))
        or getattr(info, "st_file_attributes", 0) & 0x400
    )


def _desktop_boundary() -> tuple[Path, object]:
    """Bind the real Desktop to the shared no-follow mutation guard."""
    from actions.file_controller import SafeOperationGuard

    desktop = _get_desktop()
    if _is_link_or_reparse(desktop) or not desktop.is_dir():
        raise PermissionError("Desktop is a link, junction, reparse point, or unavailable")
    return desktop, SafeOperationGuard(desktop)


def _bound_rename(desktop: Path, source: Path, target: Path) -> None:
    """Rename while both the Desktop root and destination directory are bound."""
    from actions.file_controller import SafeOperationGuard

    with SafeOperationGuard(desktop, target.parent) as guard:
        if _is_link_or_reparse(source) or _is_link_or_reparse(target.parent):
            raise PermissionError("Desktop mutation crossed a link or reparse point")
        guard.rename(source, target)


def organize_desktop(mode: str = "by_type") -> str:
    desktop, guard = _desktop_boundary()
    skip_exts     = _SKIP_EXTENSIONS.get(_OS, set())
    moved, skipped = [], []

    with guard:
        for item in desktop.iterdir():
            if _is_link_or_reparse(item) or item.is_dir() or item.name.startswith("."):
                continue
            if item.suffix.lower() in skip_exts:
                continue

            if mode == "by_date":
                mtime       = datetime.fromtimestamp(item.stat(follow_symlinks=False).st_mtime)
                folder_name = mtime.strftime("%Y-%m")
            else:
                ext         = item.suffix.lower()
                folder_name = "Others"
                for folder, exts in FILE_TYPE_MAP.items():
                    if ext in exts:
                        folder_name = folder
                        break

            target_dir = desktop / folder_name
            if target_dir.exists() and _is_link_or_reparse(target_dir):
                skipped.append(item.name)
                continue
            target_dir.mkdir(exist_ok=True)
            new_path = target_dir / item.name

            if new_path.exists() or _is_link_or_reparse(item):
                skipped.append(item.name)
                continue

            _bound_rename(desktop, item, new_path)
            moved.append(f"{item.name} → {folder_name}/")

    result = f"Desktop organized ({mode}): {len(moved)} files moved."
    if moved:
        result += "\n" + "\n".join(moved[:8])
        if len(moved) > 8:
            result += f"\n... and {len(moved) - 8} more."
    if skipped:
        result += f"\n{len(skipped)} file(s) skipped (name conflict)."
    return result


def list_desktop() -> str:
    desktop = _get_desktop()
    items   = []
    for item in sorted(desktop.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            try:
                count = len(list(item.iterdir()))
            except PermissionError:
                count = "?"
            items.append(f"📁 {item.name}/ ({count} items)")
        else:
            size     = item.stat().st_size
            size_str = (
                f"{size / 1024:.1f} KB" if size < 1024 * 1024
                else f"{size / 1024 / 1024:.1f} MB"
            )
            items.append(f"📄 {item.name} ({size_str})")

    if not items:
        return "Desktop is empty."
    return f"Desktop ({len(items)} items):\n" + "\n".join(items)


def clean_desktop() -> str:
    desktop, guard = _desktop_boundary()
    skip_exts   = _SKIP_EXTENSIONS.get(_OS, set())
    today       = datetime.now().strftime("%Y-%m-%d")
    archive_dir = desktop / f"Desktop Archive {today}"
    moved = 0
    with guard:
        if archive_dir.exists() and _is_link_or_reparse(archive_dir):
            raise PermissionError("Desktop archive target is a link or reparse point")
        archive_dir.mkdir(exist_ok=True)
        for item in desktop.iterdir():
            if _is_link_or_reparse(item) or item.is_dir() or item.name.startswith("."):
                continue
            if item.suffix.lower() in skip_exts:
                continue
            new_path = archive_dir / item.name
            if not new_path.exists() and not _is_link_or_reparse(item):
                _bound_rename(desktop, item, new_path)
                moved += 1

    return f"Desktop cleaned: {moved} files archived to '{archive_dir.name}'."


def get_desktop_stats() -> str:
    desktop    = _get_desktop()
    files      = [i for i in desktop.iterdir() if i.is_file()]
    folders    = [i for i in desktop.iterdir() if i.is_dir()]
    total_size = sum(f.stat().st_size for f in files if f.exists())
    size_str   = (
        f"{total_size / 1024:.1f} KB" if total_size < 1024 * 1024
        else f"{total_size / 1024 / 1024:.1f} MB"
    )
    return (
        f"Desktop stats ({_OS}):\n"
        f"  Files   : {len(files)}\n"
        f"  Folders : {len(folders)}\n"
        f"  Size    : {size_str}\n"
        f"  Path    : {desktop}"
    )

def desktop_control(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        action : wallpaper | wallpaper_url | current_wallpaper |
                 organize  | clean | list | stats
        path   : image path for 'wallpaper'
        url    : image URL for 'wallpaper_url'
        mode   : 'by_type' or 'by_date' for 'organize'
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    task   = params.get("task", "").strip()

    if player:
        player.write_log(f"[desktop] {action or task[:40]}")

    try:
        if action == "wallpaper":
            path = params.get("path", "")
            return set_wallpaper(path) if path else "No image path provided."

        elif action == "wallpaper_url":
            url = params.get("url", "")
            return set_wallpaper_from_url(url) if url else "No URL provided."

        elif action == "current_wallpaper":
            return get_current_wallpaper()

        elif action == "organize":
            return organize_desktop(params.get("mode", "by_type"))

        elif action == "clean":
            return clean_desktop()

        elif action == "list":
            return list_desktop()

        elif action == "stats":
            return get_desktop_stats()

        elif action == "task" or task:
            return (
                "AI-generated desktop tasks are disabled: a task description cannot "
                "authorize code that is generated after approval. Use one of the explicit "
                "desktop actions instead."
            )

        else:
            return f"Unknown desktop action: '{action}'." if action else "No action specified."

    except Exception as e:
        print(f"[Desktop] Error: {e}")
        return f"Desktop control error: {e}"
