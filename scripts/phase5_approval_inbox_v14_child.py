"""Isolated pytest child for the Approval Inbox V14 combined lineage."""

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
import zipfile
from pathlib import Path, PurePosixPath
from types import ModuleType


ROOT = Path(__file__).absolute().parents[1]
PLUGIN_RELATIVE = "scripts/phase5_approval_inbox_v14_historical_projection.py"
RUNTIME_RELATIVE = (
    "docs/onyx/checkpoints/phase5-approval-inbox-v14/private-runtime/pytest-runtime.zip"
)
RUNTIME_MANIFEST_MEMBER = "_onyx_pytest_runtime_manifest.json"
RUNTIME_NAMESPACES = (
    "pytest",
    "_pytest",
    "pluggy",
    "iniconfig",
    "packaging",
    "pygments",
    "colorama",
)
PROHIBITED_AMBIENT_INPUTS = (
    "scripts/__init__.py",
    "conftest.py",
    "tests/conftest.py",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "pyproject.toml",
    "pytest.py",
    "_pytest",
    "pluggy.py",
    "pluggy",
    "iniconfig.py",
    "iniconfig",
    "packaging.py",
    "pygments.py",
    "pygments",
    "colorama.py",
    "colorama",
)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class ChildBoundaryError(RuntimeError):
    pass


def _safe_root() -> tuple[Path, Path]:
    root = ROOT.absolute()
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    try:
        info = root.lstat()
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise ChildBoundaryError("missing-root") from error
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & reparse
        or str(root) != str(resolved)
    ):
        raise ChildBoundaryError("reparse-or-aliased-root")
    parent = root.parent
    try:
        entries = {entry.name: entry for entry in parent.iterdir()}
    except OSError as error:
        raise ChildBoundaryError("unreadable-root-parent") from error
    if root.name not in entries or entries[root.name] != root:
        raise ChildBoundaryError("root-case-or-name-alias")
    return root, resolved


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
    root, resolved_root = _safe_root()
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


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    info = path.lstat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _validate_runtime_archive(
    expected_digest: str, expected_manifest_digest: str
) -> tuple[Path, tuple[int, int, int, int]]:
    path = _safe_file(RUNTIME_RELATIVE)
    identity = _file_identity(path)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_digest:
        raise ChildBoundaryError("pytest-runtime-digest-drift")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or RUNTIME_MANIFEST_MEMBER not in names:
                raise ChildBoundaryError("pytest-runtime-member-set")
            manifest_bytes = archive.read(RUNTIME_MANIFEST_MEMBER)
            if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_digest:
                raise ChildBoundaryError("pytest-runtime-manifest-drift")
            import json

            manifest = json.loads(manifest_bytes)
            files = manifest.get("files") if type(manifest) is dict else None
            if (
                manifest.get("contract") != "OnyxPrivatePytestRuntime.v1"
                or manifest.get("namespaces") != list(RUNTIME_NAMESPACES)
                or type(files) is not dict
                or set(names) != set(files) | {RUNTIME_MANIFEST_MEMBER}
            ):
                raise ChildBoundaryError("pytest-runtime-manifest-contract")
            for name, digest in files.items():
                pure = PurePosixPath(name)
                if (
                    type(name) is not str
                    or not name
                    or pure.is_absolute()
                    or pure.as_posix() != name
                    or any(part in {"", ".", ".."} for part in pure.parts)
                    or not _HEX64.fullmatch(digest)
                    or hashlib.sha256(archive.read(name)).hexdigest() != digest
                ):
                    raise ChildBoundaryError("pytest-runtime-member-drift")
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise ChildBoundaryError("pytest-runtime-invalid") from error
    path = _safe_file(RUNTIME_RELATIVE)
    if _file_identity(path) != identity:
        raise ChildBoundaryError("pytest-runtime-identity-drift")
    return path, identity


def _validate_runtime_modules(archive: Path) -> None:
    archive_prefix = str(archive) + os.sep
    for name, module in tuple(sys.modules.items()):
        if name.split(".", 1)[0] not in RUNTIME_NAMESPACES:
            continue
        origin = getattr(module, "__file__", None)
        if type(origin) is not str or not origin.startswith(archive_prefix):
            raise ChildBoundaryError(f"pytest-runtime-origin:{name}")


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
    name = "_onyx_p52_v14_exact_historical_plugin"
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
    _safe_root()
    for relative in PROHIBITED_AMBIENT_INPUTS:
        candidate = ROOT / relative
        if candidate.exists() or candidate.is_symlink():
            raise ChildBoundaryError(f"prohibited-ambient-input:{relative}")
    if os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1":
        raise ChildBoundaryError("pytest-autoload-not-disabled")
    forbidden_environment = {
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "HOME",
        "USERPROFILE",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    }
    forbidden_environment.update(
        name
        for name in os.environ
        if name == "GIT_DIR"
        or name == "GIT_WORK_TREE"
        or name == "GIT_OBJECT_DIRECTORY"
        or name == "GIT_ALTERNATE_OBJECT_DIRECTORIES"
        or name.startswith("GIT_CONFIG")
        or name.startswith("GIT_")
    )
    for name in sorted(forbidden_environment):
        if name in os.environ:
            raise ChildBoundaryError(f"unsafe-environment:{name}")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--plugin-sha256", required=True)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--runtime-manifest-sha256", required=True)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    if not all(
        _HEX64.fullmatch(value)
        for value in (
            arguments.plugin_sha256,
            arguments.runtime_sha256,
            arguments.runtime_manifest_sha256,
        )
    ):
        raise ChildBoundaryError("invalid-authority-digest")
    _verify_ambient_boundary()
    runtime, runtime_identity = _validate_runtime_archive(
        arguments.runtime_sha256, arguments.runtime_manifest_sha256
    )
    for loaded in tuple(sys.modules):
        if loaded.split(".", 1)[0] in RUNTIME_NAMESPACES:
            raise ChildBoundaryError(f"pytest-runtime-preloaded:{loaded}")
    stdlib_root = Path(sysconfig.get_paths()["stdlib"]).resolve(strict=True)
    base_prefix = Path(sys.base_prefix).resolve(strict=True)
    stdlib_paths = []
    for entry in sys.path:
        if not entry:
            continue
        try:
            resolved = Path(entry).resolve(strict=True)
            if (
                resolved == stdlib_root
                or resolved.is_relative_to(stdlib_root)
                or (
                    resolved.is_relative_to(base_prefix)
                    and "site-packages"
                    not in {part.casefold() for part in resolved.parts}
                )
            ):
                stdlib_paths.append(str(resolved))
        except (OSError, ValueError):
            continue
    dependency_roots = [sysconfig.get_paths()["purelib"], site.getusersitepackages()]
    sys.path[:] = [
        str(runtime),
        str(ROOT),
        *dict.fromkeys([*stdlib_paths, *dependency_roots]),
    ]
    plugin = _load_exact_plugin(arguments.plugin_sha256)
    import pytest

    _validate_runtime_modules(runtime)
    args = ["-c", os.devnull, "--noconftest", *arguments.pytest_args]
    result = pytest.main(args, plugins=[plugin])
    _validate_runtime_modules(runtime)
    regated_runtime, _ = _validate_runtime_archive(
        arguments.runtime_sha256, arguments.runtime_manifest_sha256
    )
    if (
        regated_runtime != runtime
        or _file_identity(regated_runtime) != runtime_identity
    ):
        raise ChildBoundaryError("pytest-runtime-postrun-identity-drift")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
