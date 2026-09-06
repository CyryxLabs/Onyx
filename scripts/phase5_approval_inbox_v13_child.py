"""Isolated pytest child for the Approval Inbox V13 combined lineage."""

from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import os
import re
import site
import stat
import sys
import sysconfig
from pathlib import Path, PurePosixPath
from types import ModuleType


ROOT = Path(__file__).absolute().parents[1]
PLUGIN_RELATIVE = "scripts/phase5_approval_inbox_v13_historical_projection.py"
PROHIBITED_AMBIENT_INPUTS = (
    "scripts/__init__.py",
    "conftest.py",
    "tests/conftest.py",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "pyproject.toml",
)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class ChildBoundaryError(RuntimeError):
    pass


def _safe_file(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
        or pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ChildBoundaryError(f"noncanonical-path:{relative!r}")
    root = ROOT.absolute()
    resolved_root = root.resolve(strict=True)
    current = root
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for part in pure.parts:
        entries = {entry.name: entry for entry in current.iterdir()}
        if part not in entries:
            raise ChildBoundaryError(f"missing-or-case-mismatch:{relative}")
        current = entries[part]
        info = current.lstat()
        resolved = current.resolve(strict=True)
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & reparse
        ):
            raise ChildBoundaryError(f"reparse-component:{relative}")
        resolved.relative_to(resolved_root)
        if resolved.name != part:
            raise ChildBoundaryError(f"case-or-name-alias:{relative}")
    if not current.is_file():
        raise ChildBoundaryError(f"not-file:{relative}")
    return current


class _ExactPluginLoader:
    def __init__(self, path: Path, digest: str) -> None:
        self.path = str(path)
        self.digest = digest


def _load_exact_plugin(expected_digest: str) -> ModuleType:
    path = _safe_file(PLUGIN_RELATIVE)
    before = path.lstat()
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != expected_digest:
        raise ChildBoundaryError("plugin-digest-drift")
    path = _safe_file(PLUGIN_RELATIVE)
    after = path.lstat()
    identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
        raise ChildBoundaryError("plugin-identity-drift")
    name = "_onyx_p52_v13_exact_historical_plugin"
    if name in sys.modules:
        sys.modules.pop(name, None)
        raise ChildBoundaryError("plugin-private-cache-preexisting")
    loader = _ExactPluginLoader(path, expected_digest)
    spec = importlib.machinery.ModuleSpec(name, loader, origin=str(path))
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__loader__ = loader
    module.__package__ = ""
    module.__spec__ = spec
    try:
        exec(compile(source, str(path), "exec", dont_inherit=True), module.__dict__)
        regated = _safe_file(PLUGIN_RELATIVE)
        current = regated.lstat()
        if (
            (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            != identity
            or hashlib.sha256(regated.read_bytes()).hexdigest() != expected_digest
            or module.__file__ != str(regated)
            or module.__loader__ is not loader
            or module.__spec__ is not spec
            or module.__spec__.origin != str(regated)
            or name in sys.modules
        ):
            raise ChildBoundaryError("plugin-loaded-identity-drift")
        return module
    finally:
        sys.modules.pop(name, None)


def _verify_ambient_boundary() -> None:
    for relative in PROHIBITED_AMBIENT_INPUTS:
        candidate = ROOT / relative
        if candidate.exists() or candidate.is_symlink():
            raise ChildBoundaryError(f"prohibited-ambient-input:{relative}")
    if os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1":
        raise ChildBoundaryError("pytest-autoload-not-disabled")
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH", "PYTHONSTARTUP"):
        if name in os.environ:
            raise ChildBoundaryError(f"unsafe-environment:{name}")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--plugin-sha256", required=True)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    if not _HEX64.fullmatch(arguments.plugin_sha256):
        raise ChildBoundaryError("invalid-plugin-digest")
    _verify_ambient_boundary()
    # ``python -E -S`` prevents environment-derived paths, .pth execution and
    # sitecustomize/usercustomize. Add only the two conventional package roots
    # needed to import the explicitly selected pytest runtime.
    for package_root in (
        sysconfig.get_paths()["purelib"],
        site.getusersitepackages(),
    ):
        if package_root not in sys.path:
            sys.path.append(package_root)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    plugin = _load_exact_plugin(arguments.plugin_sha256)
    import pytest

    args = ["-c", os.devnull, "--noconftest", *arguments.pytest_args]
    return pytest.main(args, plugins=[plugin])


if __name__ == "__main__":
    raise SystemExit(main())
