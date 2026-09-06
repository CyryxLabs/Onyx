from __future__ import annotations

import os
import tarfile
from pathlib import Path

import pytest

from scripts import build_release


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o7777


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
def test_linux_staging_normalizes_static_directories_and_executables(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stage"
    legal = root / "THIRD_PARTY_LICENSES"
    legal.mkdir(parents=True)
    binary = root / "Onyx"
    launcher = root / "AppRun"
    license_file = root / "LICENSE.txt"
    desktop = root / "onyx.desktop"
    library = root / "libonyx.so"
    binary.write_bytes(b"\x7fELFbinary")
    library.write_bytes(b"\x7fELFlibrary")
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    license_file.write_text("license", encoding="utf-8")
    desktop.write_text("[Desktop Entry]\n", encoding="utf-8")
    (legal / "LGPL-3.0.txt").write_text("lgpl", encoding="utf-8")
    for path in (root, legal):
        path.chmod(0o777)
    for path in (binary, launcher, license_file, desktop, library, legal / "LGPL-3.0.txt"):
        path.chmod(0o777)

    build_release.normalize_linux_tree_permissions(root)

    assert _mode(root) == 0o755
    assert _mode(legal) == 0o755
    assert _mode(binary) == 0o755
    assert _mode(library) == 0o755
    assert _mode(launcher) == 0o755
    assert _mode(license_file) == 0o644
    assert _mode(desktop) == 0o644
    assert _mode(legal / "LGPL-3.0.txt") == 0o644
    assert build_release.validate_linux_tree_permissions(root, label="test") == 8


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
@pytest.mark.parametrize("unsafe_mode", [0o777, 0o666, 0o755])
def test_linux_permission_gate_rejects_static_world_write_or_execute(
    tmp_path: Path,
    unsafe_mode: int,
) -> None:
    root = tmp_path / "stage"
    root.mkdir(mode=0o755)
    static = root / "THIRD_PARTY_NOTICES.md"
    static.write_text("notices", encoding="utf-8")
    static.chmod(unsafe_mode)

    with pytest.raises(RuntimeError, match="world-writable|unexpected executable"):
        build_release.validate_linux_tree_permissions(root, label="test")


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
def test_linux_tar_permission_manifest_rejects_inherited_0777_static_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Onyx"
    source.mkdir(mode=0o755)
    executable = source / "Onyx"
    executable.write_bytes(b"\x7fELFbinary")
    executable.chmod(0o755)
    license_file = source / "LICENSE.txt"
    license_file.write_text("license", encoding="utf-8")
    license_file.chmod(0o777)
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname="Onyx")

    with pytest.raises(RuntimeError, match="world-writable"):
        build_release.validate_linux_tar_permissions(archive)

    build_release.normalize_linux_tree_permissions(source)
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname="Onyx")
    assert build_release.validate_linux_tar_permissions(archive) == 3


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics required")
def test_linux_tar_permission_manifest_accepts_conventional_0777_symlink(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Onyx"
    source.mkdir(mode=0o755)
    executable = source / "Onyx"
    executable.write_bytes(b"\x7fELFbinary")
    executable.chmod(0o755)
    os.symlink("Onyx", source / "onyx")
    archive = tmp_path / "safe-link.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname="Onyx")

    assert build_release.validate_linux_tar_permissions(archive) == 3


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics required")
@pytest.mark.parametrize(
    "target",
    ("/etc/passwd", "../outside", "missing"),
)
def test_linux_tree_permission_manifest_rejects_unsafe_link_targets(
    tmp_path: Path,
    target: str,
) -> None:
    root = tmp_path / "stage"
    root.mkdir(mode=0o755)
    os.symlink(target, root / "onyx")

    with pytest.raises(RuntimeError, match="relative|traverses|dangling|leaves"):
        build_release.validate_linux_tree_permissions(root, label="test")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics required")
def test_linux_tree_permission_manifest_rejects_nested_link_escape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stage"
    root.mkdir(mode=0o755)
    os.symlink("/etc/passwd", root / "escaped")
    os.symlink("escaped", root / "onyx")

    with pytest.raises(RuntimeError, match="relative|dangling or leaves"):
        build_release.validate_linux_tree_permissions(root, label="test")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics required")
@pytest.mark.parametrize(
    "target",
    ("/etc/passwd", "../outside", "missing"),
)
def test_linux_tar_permission_manifest_rejects_unsafe_link_targets(
    tmp_path: Path,
    target: str,
) -> None:
    source = tmp_path / "Onyx"
    source.mkdir(mode=0o755)
    executable = source / "Onyx"
    executable.write_bytes(b"\x7fELFbinary")
    executable.chmod(0o755)
    os.symlink(target, source / "onyx")
    archive = tmp_path / "unsafe-link.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname="Onyx")

    with pytest.raises(RuntimeError, match="relative|traverses|dangling"):
        build_release.validate_linux_tar_permissions(archive)


def test_linux_structure_gate_inspects_all_three_permission_manifests() -> None:
    source = Path(build_release.__file__).read_text(encoding="utf-8")

    assert "validate_linux_tar_permissions(archives[0])" in source
    assert 'validate_linux_tree_permissions(deb_root, label="Linux DEB")' in source
    assert 'label="Linux AppImage"' in source
