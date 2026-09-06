"""Resolve an owner-supplied FFmpeg with a bounded audio/video encoder baseline."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
import threading
from pathlib import Path


PROBE_TIMEOUT_SECONDS = 3
PROBE_CACHE_SECONDS = 60
_PROBE_CACHE: dict[tuple, bool] = {}
_PROBE_CACHE_LOCK = threading.Lock()


def _unlinked_directories(path: Path) -> bool:
    """Reject symlinks and Windows junction/reparse ancestors before resolving."""
    absolute = path.absolute()
    try:
        for directory in (absolute, *absolute.parents):
            info = directory.lstat()
            if (not stat.S_ISDIR(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                return False
        return True
    except OSError:
        return False


def _probe_av_encoders(path: str, identity: tuple, epoch: int) -> bool:
    """Cached baseline capability check, not certification of every media codec."""
    try:
        result = subprocess.run(
            [path, "-hide_banner", "-encoders"], stdin=subprocess.DEVNULL,
            capture_output=True, timeout=PROBE_TIMEOUT_SECONDS, check=False,
            shell=False, **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
        if result.returncode != 0:
            return False
        kinds = set()
        for line in result.stdout.decode("utf-8", errors="replace").splitlines():
            fields = line.split()
            if len(fields) >= 2 and len(fields[0]) == 6 and fields[1] != "=":
                if fields[0][0] in "AV" and all(c == "." or c.isupper() for c in fields[0]):
                    kinds.add(fields[0][0])
        return kinds == {"A", "V"}
    except (OSError, subprocess.SubprocessError):
        return False


def _cached_av_encoders(path: str, identity: tuple, epoch: int) -> bool:
    # Keep source functions directly attestable by the authenticated loader.
    # A C-level decorator wrapper would hide their verified code identity.
    key = (path, identity, epoch)
    with _PROBE_CACHE_LOCK:
        if key in _PROBE_CACHE:
            return _PROBE_CACHE[key]
    result = _probe_av_encoders(path, identity, epoch)
    with _PROBE_CACHE_LOCK:
        if len(_PROBE_CACHE) >= 32:
            _PROBE_CACHE.clear()
        _PROBE_CACHE[key] = result
    return result


def _has_av_encoders(path: Path) -> bool:
    try:
        before = path.stat()
        identity = (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns)
        result = _cached_av_encoders(str(path), identity, int(time.monotonic() // PROBE_CACHE_SECONDS))
        after = path.stat()
        return result and identity == (after.st_dev, after.st_ino, after.st_size,
                                       after.st_mtime_ns, after.st_ctime_ns)
    except OSError:
        return False


def _winget_ffmpeg_link(candidate: Path) -> Path | None:
    """Accept only the standard per-user WinGet FFmpeg package link.

    Other symlink escapes remain rejected. Return the resolved target so
    subsequent execution does not follow a retargeted Links entry.
    """
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data or not Path(local_app_data).is_absolute():
        return None
    winget = Path(local_app_data) / "Microsoft" / "WinGet"
    expected = winget / "Links" / "ffmpeg.exe"
    if os.path.normcase(os.path.abspath(candidate)) != os.path.normcase(
        os.path.abspath(expected)
    ):
        return None
    package = winget / "Packages" / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    resolved = _regular_contained_file(candidate, package)
    if resolved is None or resolved.name.lower() != "ffmpeg.exe":
        return None
    if resolved.parent.name.lower() != "bin":
        return None
    return resolved


def _regular_contained_file(candidate: Path, root: Path) -> Path | None:
    try:
        if not _unlinked_directories(root) or not _unlinked_directories(candidate.parent):
            return None
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(resolved_root):
            return None
        if not resolved.is_file() or resolved.stat().st_size <= 0:
            return None
        return resolved
    except (OSError, RuntimeError):
        return None


def resolve_ffmpeg_executable() -> Path | None:
    """Resolve configured/PATH FFmpeg only after an audio/video encoder probe.

    Playwright ships a restricted FFmpeg build that lacks the codecs required
    by Onyx audio and social-video operations. Treating it as a general runtime
    would produce false readiness, so it is intentionally excluded here, even
    when renamed. This baseline does not certify every codec or media operation.
    """

    configured = os.environ.get("ONYX_FFMPEG_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        resolved = _regular_contained_file(path, path.parent)
        if resolved is not None and _has_av_encoders(resolved):
            return resolved

    system_binary = shutil.which("ffmpeg")
    if system_binary:
        path = Path(system_binary)
        resolved = _regular_contained_file(path, path.parent)
        if resolved is None:
            resolved = _winget_ffmpeg_link(path)
        if resolved is not None and _has_av_encoders(resolved):
            return resolved
    return None


def ffmpeg_command() -> str | None:
    executable = resolve_ffmpeg_executable()
    return str(executable) if executable is not None else None
