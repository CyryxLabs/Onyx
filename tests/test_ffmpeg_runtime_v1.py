from __future__ import annotations

from pathlib import Path
import os
import stat
import subprocess
from types import SimpleNamespace

import pytest

from core import ffmpeg_runtime_v1


FULL_ENCODERS = b" V..... libx264 H.264\n A..... aac AAC\n A..... libmp3lame MP3\n"
REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def encoder_probe(monkeypatch):
    ffmpeg_runtime_v1._PROBE_CACHE.clear()
    calls = []

    def probe(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=FULL_ENCODERS)

    monkeypatch.setattr(ffmpeg_runtime_v1.subprocess, "run", probe)
    yield calls
    ffmpeg_runtime_v1._PROBE_CACHE.clear()


@pytest.mark.parametrize("location", ["package", "packages", "links", "explicit"])
def test_directory_link_escape_is_rejected(tmp_path, monkeypatch, encoder_probe, location):
    outside = tmp_path / "outside"
    outside.mkdir()
    winget = tmp_path / "Microsoft" / "WinGet"
    package = winget / "Packages" / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    link = winget / "Links" / "ffmpeg.exe"
    anchor = {"package": package, "packages": package.parent,
              "links": link.parent, "explicit": tmp_path / "explicit"}[location]
    anchor.parent.mkdir(parents=True, exist_ok=True)
    try:
        anchor.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation unavailable")
    binary = (anchor / "ffmpeg.exe" if location == "explicit"
              else package / "ffmpeg-7.1.1-full_build" / "bin" / "ffmpeg.exe")
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"outside-runtime")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ONYX_FFMPEG_PATH", str(binary) if location == "explicit" else "")
    if location != "explicit":
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(binary)
    monkeypatch.setattr(ffmpeg_runtime_v1.shutil, "which",
                        lambda _: None if location == "explicit" else str(link))
    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() is None
    assert encoder_probe == []


@pytest.mark.parametrize("output,code", [
    (b" V..... libvpx VP8\n A..... = Audio\n", 0),
    (b"not ffmpeg", 0), (FULL_ENCODERS, 1),
])
def test_restricted_or_invalid_probe_rejected_even_explicit(tmp_path, monkeypatch, output, code):
    binary = tmp_path / "renamed.exe"
    binary.write_bytes(b"runtime")
    monkeypatch.setenv("ONYX_FFMPEG_PATH", str(binary))
    monkeypatch.setattr(ffmpeg_runtime_v1.shutil, "which", lambda _: None)
    monkeypatch.setattr(ffmpeg_runtime_v1.subprocess, "run",
                        lambda *a, **kw: SimpleNamespace(returncode=code, stdout=output))
    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() is None


@pytest.mark.parametrize("name", ["ffmpeg.exe", "ffmpeg-win64.exe", "playwright-full.exe"])
def test_full_runtime_has_no_filename_false_positive_and_probe_is_cached(
    tmp_path, monkeypatch, encoder_probe, name,
):
    binary = tmp_path / name
    binary.write_bytes(b"full-runtime")
    monkeypatch.setenv("ONYX_FFMPEG_PATH", str(binary))
    monkeypatch.setattr(ffmpeg_runtime_v1.time, "monotonic", lambda: 120)
    for _ in range(4):
        assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() == binary.resolve()
    assert len(encoder_probe) == 1
    args, kwargs = encoder_probe[0]
    assert args == [str(binary.resolve()), "-hide_banner", "-encoders"]
    assert kwargs["timeout"] == 3 and kwargs["shell"] is False
    binary.write_bytes(b"changed-full-runtime")
    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() == binary.resolve()
    assert len(encoder_probe) == 2
    monkeypatch.setattr(ffmpeg_runtime_v1.time, "monotonic", lambda: 180)
    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() == binary.resolve()
    assert len(encoder_probe) == 3


def test_probe_timeout_is_unavailable_not_readiness(tmp_path, monkeypatch):
    binary = tmp_path / "ffmpeg.exe"
    binary.write_bytes(b"runtime")
    monkeypatch.setenv("ONYX_FFMPEG_PATH", str(binary))
    monkeypatch.setattr(ffmpeg_runtime_v1.shutil, "which", lambda _: None)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(ffmpeg_runtime_v1.subprocess, "run", timeout)
    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() is None


def test_directory_reparse_attribute_is_rejected(tmp_path, monkeypatch):
    real_lstat = Path.lstat

    def junction(path):
        if path == tmp_path:
            return SimpleNamespace(st_mode=stat.S_IFDIR,
                                   st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", junction)
    assert not ffmpeg_runtime_v1._unlinked_directories(tmp_path)


def test_changed_binary_during_probe_is_rejected(tmp_path, monkeypatch):
    binary = tmp_path / "ffmpeg.exe"
    binary.write_bytes(b"before")
    monkeypatch.setenv("ONYX_FFMPEG_PATH", str(binary))
    monkeypatch.setattr(ffmpeg_runtime_v1.shutil, "which", lambda _: None)

    def replaced(*args, **kwargs):
        binary.write_bytes(b"changed-while-probing")
        return SimpleNamespace(returncode=0, stdout=FULL_ENCODERS)

    monkeypatch.setattr(ffmpeg_runtime_v1.subprocess, "run", replaced)
    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() is None


@pytest.mark.parametrize("restricted", [True, False])
def test_real_installed_runtimes(tmp_path, monkeypatch, restricted):
    if restricted:
        candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright" / "ffmpeg-1011" / "ffmpeg-win64.exe"
    else:
        found = ffmpeg_runtime_v1.shutil.which("ffmpeg")
        if not found:
            pytest.skip("owner-supplied FFmpeg is not installed")
        candidate = Path(found).resolve()
    if not candidate.is_file():
        pytest.skip("integration runtime not installed")
    monkeypatch.setattr(ffmpeg_runtime_v1.subprocess, "run", REAL_RUN)
    monkeypatch.setattr(ffmpeg_runtime_v1.shutil, "which", lambda _: None)
    monkeypatch.setenv("ONYX_FFMPEG_PATH", str(candidate))
    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() == (None if restricted else candidate)


@pytest.mark.parametrize("approved", [True, False])
def test_winget_link_requires_expected_package(tmp_path, monkeypatch, approved):
    winget = tmp_path / "Microsoft" / "WinGet"
    package = (
        "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        if approved else "Unrelated.Package"
    )
    binary = winget / "Packages" / package / "ffmpeg-7.1.1-full_build" / "bin" / "ffmpeg.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"full-runtime")
    link = winget / "Links" / "ffmpeg.exe"
    link.parent.mkdir()
    try:
        link.symlink_to(binary)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ONYX_FFMPEG_PATH", raising=False)
    monkeypatch.setattr(ffmpeg_runtime_v1.shutil, "which", lambda _: str(link))
    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() == (
        binary.resolve() if approved else None
    )


def test_explicit_full_ffmpeg_is_resolved_when_path_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "ffmpeg-full.exe"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"trusted-binary")
    monkeypatch.setattr(ffmpeg_runtime_v1.shutil, "which", lambda _name: None)
    monkeypatch.setenv("ONYX_FFMPEG_PATH", str(binary))

    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() == binary.resolve()


def test_explicit_ffmpeg_symlink_escape_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside.exe"
    outside.write_bytes(b"outside")
    link = tmp_path / "root" / "ffmpeg.exe"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    monkeypatch.setattr(ffmpeg_runtime_v1.shutil, "which", lambda _name: None)
    monkeypatch.setenv("ONYX_FFMPEG_PATH", str(link))

    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() is None


def test_system_ffmpeg_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "ffmpeg.exe"
    binary.write_bytes(b"system-binary")
    monkeypatch.delenv("ONYX_FFMPEG_PATH", raising=False)
    monkeypatch.setattr(ffmpeg_runtime_v1.shutil, "which", lambda _name: str(binary))

    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() == binary.resolve()


def test_restricted_playwright_ffmpeg_is_not_reported_as_full_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restricted = (
        tmp_path
        / "playwright"
        / "driver"
        / "package"
        / ".local-browsers"
        / "ffmpeg-1011"
        / "ffmpeg-win64.exe"
    )
    restricted.parent.mkdir(parents=True)
    restricted.write_bytes(b"restricted")
    monkeypatch.delenv("ONYX_FFMPEG_PATH", raising=False)
    monkeypatch.setattr(ffmpeg_runtime_v1.shutil, "which", lambda _name: None)

    assert ffmpeg_runtime_v1.resolve_ffmpeg_executable() is None
