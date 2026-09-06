"""Isolated pytest child for the Approval Inbox V15 combined lineage."""

from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import json
import os
import re
import stat
import sys
import sysconfig
import zipfile
from pathlib import Path, PurePosixPath
from types import ModuleType


ROOT = Path(__file__).absolute().parents[1]
PLUGIN_RELATIVE = "scripts/phase5_approval_inbox_v15_historical_projection.py"
RUNTIME_RELATIVE = (
    "docs/onyx/checkpoints/phase5-approval-inbox-v15/private-runtime/pytest-runtime.zip"
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
    "defusedxml",
)
MATERIALIZED_MANIFEST = "_onyx_v15_materialized_manifest.json"
DEPENDENCY_ROOT = "_onyx_v15_dependencies"
FOCUSED = ("tests/test_approval_inbox_v15.py",)
COMBINED = tuple(
    f"tests/test_approval_inbox_v{version}.py" for version in range(1, 16)
)
REGRESSIONS = (
    "tests/test_regressions.py",
    "tests/test_missions.py",
    "tests/test_mission_tools.py",
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
                    or "__pycache__" in pure.parts
                    or pure.suffix in {".pyc", ".pyo"}
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
    name = "_onyx_p52_v15_exact_historical_plugin"
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
    expected_home = str((ROOT.parent / "home").absolute())
    supplied_home = os.environ.get("HOME")
    supplied_profile = os.environ.get("USERPROFILE")
    if supplied_home is not None or supplied_profile is not None:
        if supplied_home != expected_home or supplied_profile != expected_home:
            raise ChildBoundaryError("unsafe-environment:HOME-or-USERPROFILE")
        if os.name == "nt" and (
            os.environ.get("HOMEDRIVE") != Path(expected_home).drive
            or os.environ.get("HOMEPATH")
            != expected_home[len(Path(expected_home).drive) :]
        ):
            raise ChildBoundaryError("unsafe-environment:home-components")


def _require_isolated_runtime() -> None:
    if not (
        sys.flags.isolated
        and sys.flags.no_site
        and sys.flags.safe_path
        and sys.flags.dont_write_bytecode
    ):
        raise ChildBoundaryError("python-not-isolated-use--I--S--B")
    sys.dont_write_bytecode = True


def _validated_pytest_args(raw: list[str]) -> list[str]:
    if type(raw) is not list or any(type(value) is not str for value in raw):
        raise ChildBoundaryError("pytest-arguments-type")
    modes = {
        "focused": FOCUSED,
        "combined": COMBINED,
        "regressions": REGRESSIONS,
    }
    for label, suite in modes.items():
        fixed = [*suite, "-q", "-p", "no:cacheprovider"]
        if raw == fixed:
            return fixed
        junit = str(
            (ROOT.parent / "home" / "junit" / f"{label}.xml").absolute()
        )
        with_junit = [*fixed, f"--junitxml={junit}"]
        if raw == with_junit:
            return with_junit
    raise ChildBoundaryError("pytest-arguments-not-authorized")


def _validated_stdlib_entries(raw: list[list[str]]) -> list[str]:
    if type(raw) is not list or not raw:
        raise ChildBoundaryError("stdlib-entries-type")
    initial = {str(Path(value).absolute()) for value in sys.path if value}
    result: list[str] = []
    normalized_records: list[list[str]] = []
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    stdlib_roots: list[Path] = []
    for name in ("stdlib", "platstdlib"):
        root = Path(sysconfig.get_paths()[name]).resolve(strict=True)
        if root not in stdlib_roots:
            stdlib_roots.append(root)
    base_prefix = Path(sys.base_prefix).resolve(strict=True)
    for record in raw:
        if (
            type(record) is not list
            or len(record) != 2
            or any(type(value) is not str for value in record)
        ):
            raise ChildBoundaryError("stdlib-entry-record")
        value, authority = record
        path = Path(value)
        if not path.is_absolute() or str(path.absolute()) not in initial:
            raise ChildBoundaryError("stdlib-entry-not-in-isolated-path")
        try:
            resolved = path.resolve(strict=True)
            info = path.lstat()
        except OSError as error:
            raise ChildBoundaryError("stdlib-entry-missing") from error
        if str(path.absolute()) != str(resolved) or stat.S_ISLNK(info.st_mode) or getattr(
            info, "st_file_attributes", 0
        ) & reparse:
            raise ChildBoundaryError("stdlib-entry-aliased")
        parts = {part.casefold() for part in resolved.parts}
        if resolved == base_prefix:
            raise ChildBoundaryError("stdlib-entry-base-prefix")
        if "site-packages" in parts or "dist-packages" in parts:
            raise ChildBoundaryError("stdlib-entry-site-packages")
        under_stdlib = any(
            resolved == root or resolved.is_relative_to(root)
            for root in stdlib_roots
        )
        platform_stdlib = (
            resolved.parent == base_prefix
            and resolved.name.casefold() in {"dlls", "lib-dynload"}
        )
        stdlib_zip = (
            resolved.parent == base_prefix
            and resolved.suffix.casefold() == ".zip"
        )
        if not (under_stdlib or platform_stdlib or stdlib_zip):
            raise ChildBoundaryError("stdlib-entry-not-semantic-stdlib")
        if authority == "directory":
            if not stat.S_ISDIR(info.st_mode):
                raise ChildBoundaryError("stdlib-entry-not-directory")
        elif _HEX64.fullmatch(authority):
            if (
                not stat.S_ISREG(info.st_mode)
                or resolved.suffix.casefold() != ".zip"
                or hashlib.sha256(resolved.read_bytes()).hexdigest() != authority
            ):
                raise ChildBoundaryError("stdlib-entry-zip-drift")
        else:
            raise ChildBoundaryError("stdlib-entry-authority")
        if str(resolved) in result:
            raise ChildBoundaryError("stdlib-entry-duplicate")
        result.append(str(resolved))
        normalized_records.append([str(resolved), authority])
    expected: list[list[str]] = []
    for value in sys.path:
        if not value:
            continue
        path = Path(value).absolute()
        try:
            resolved = path.resolve(strict=True)
            info = path.lstat()
        except OSError:
            continue
        parts = {part.casefold() for part in resolved.parts}
        if (
            resolved == base_prefix
            or "site-packages" in parts
            or "dist-packages" in parts
        ):
            continue
        under_stdlib = any(
            resolved == root or resolved.is_relative_to(root)
            for root in stdlib_roots
        )
        platform_stdlib = (
            resolved.parent == base_prefix
            and resolved.name.casefold() in {"dlls", "lib-dynload"}
        )
        stdlib_zip = (
            resolved.parent == base_prefix
            and resolved.suffix.casefold() == ".zip"
        )
        if stat.S_ISDIR(info.st_mode) and (under_stdlib or platform_stdlib):
            candidate = [str(resolved), "directory"]
        elif stat.S_ISREG(info.st_mode) and stdlib_zip:
            candidate = [
                str(resolved),
                hashlib.sha256(resolved.read_bytes()).hexdigest(),
            ]
        else:
            continue
        if candidate not in expected:
            expected.append(candidate)
    if normalized_records != expected:
        raise ChildBoundaryError("stdlib-entry-set-or-order-drift")
    return result


def _authoritative_sys_path(
    runtime: Path, dependency_root: Path, stdlib_paths: list[str]
) -> list[str]:
    return [
        *stdlib_paths,
        str(runtime),
        str(ROOT),
        str(dependency_root),
    ]


def _load_materialized_manifest(expected_digest: str) -> dict[str, str]:
    path = _safe_file(MATERIALIZED_MANIFEST)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_digest:
        raise ChildBoundaryError("materialized-manifest-drift")
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as error:
        raise ChildBoundaryError("materialized-manifest-json") from error
    files = payload.get("files") if type(payload) is dict else None
    if payload.get("contract") != "OnyxMaterializedAuthority.v15" or type(files) is not dict:
        raise ChildBoundaryError("materialized-manifest-contract")
    for relative, digest in files.items():
        if type(relative) is not str or not _HEX64.fullmatch(digest):
            raise ChildBoundaryError("materialized-manifest-entry")
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or pure.as_posix() != relative
            or any(part in {"", ".", ".."} for part in pure.parts)
            or "__pycache__" in pure.parts
            or pure.suffix in {".pyc", ".pyo"}
        ):
            raise ChildBoundaryError(f"materialized-manifest-path:{relative}")
    observed = _scan_materialized_files()
    expected_files = set(files) | {MATERIALIZED_MANIFEST}
    extras = set(observed) - expected_files
    if extras:
        raise ChildBoundaryError(f"materialized-extra-files:{sorted(extras)[:3]}")
    missing = expected_files - set(observed)
    if missing:
        raise ChildBoundaryError(f"materialized-missing-files:{sorted(missing)[:3]}")
    for relative, digest in files.items():
        if observed[relative] != digest:
            raise ChildBoundaryError(f"materialized-file-drift:{relative}")
    return files


def _scan_materialized_files() -> dict[str, str]:
    root, _ = _safe_root()
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    observed: dict[str, str] = {}
    stack: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath())]
    while stack:
        directory, prefix = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as error:
            raise ChildBoundaryError("materialized-tree-unreadable") from error
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & reparse:
                raise ChildBoundaryError(f"materialized-reparse:{prefix / entry.name}")
            relative = prefix / entry.name
            if stat.S_ISDIR(info.st_mode):
                stack.append((Path(entry.path), relative))
            elif stat.S_ISREG(info.st_mode):
                value = relative.as_posix()
                if "__pycache__" in relative.parts or relative.suffix in {".pyc", ".pyo"}:
                    raise ChildBoundaryError(f"bytecode-present:{value}")
                observed[value] = hashlib.sha256(Path(entry.path).read_bytes()).hexdigest()
            else:
                raise ChildBoundaryError(f"materialized-nonregular:{relative}")
    return observed


def _validate_module_origins(
    files: dict[str, str], runtime: Path, stdlib_roots: tuple[Path, ...]
) -> None:
    runtime_prefix = str(runtime) + os.sep
    root_resolved = ROOT.resolve(strict=True)
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if origin is None:
            continue
        if type(origin) is not str:
            raise ChildBoundaryError(f"module-origin-type:{name}")
        if origin.startswith(runtime_prefix):
            continue
        try:
            resolved = Path(origin).resolve(strict=True)
        except OSError as error:
            raise ChildBoundaryError(f"module-origin-missing:{name}") from error
        if any(resolved == root or resolved.is_relative_to(root) for root in stdlib_roots):
            continue
        try:
            relative = resolved.relative_to(root_resolved).as_posix()
        except ValueError as error:
            raise ChildBoundaryError(f"module-origin-outside-authority:{name}:{origin}") from error
        expected = files.get(relative)
        if expected is None or hashlib.sha256(resolved.read_bytes()).hexdigest() != expected:
            raise ChildBoundaryError(f"module-origin-unbound:{name}:{relative}")


def _validate_no_bytecode(files: dict[str, str]) -> None:
    observed = _scan_materialized_files()
    for relative, expected in files.items():
        if observed.get(relative) != expected:
            raise ChildBoundaryError(f"materialized-postrun-drift:{relative}")
    for relative in set(observed) - set(files) - {MATERIALIZED_MANIFEST}:
        if PurePosixPath(relative).suffix.casefold() in {
            ".py",
            ".pyw",
            ".pyd",
            ".dll",
            ".so",
            ".dylib",
        }:
            raise ChildBoundaryError(f"unbound-executable-output:{relative}")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--plugin-sha256", required=True)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--runtime-manifest-sha256", required=True)
    parser.add_argument("--materialized-manifest-sha256", required=True)
    parser.add_argument("--stdlib-entry", action="append", nargs=2, default=[])
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    if not all(
        _HEX64.fullmatch(value)
        for value in (
            arguments.plugin_sha256,
            arguments.runtime_sha256,
            arguments.runtime_manifest_sha256,
            arguments.materialized_manifest_sha256,
        )
    ):
        raise ChildBoundaryError("invalid-authority-digest")
    _require_isolated_runtime()
    _verify_ambient_boundary()
    materialized_files = _load_materialized_manifest(
        arguments.materialized_manifest_sha256
    )
    runtime, runtime_identity = _validate_runtime_archive(
        arguments.runtime_sha256, arguments.runtime_manifest_sha256
    )
    for loaded in tuple(sys.modules):
        if loaded.split(".", 1)[0] in RUNTIME_NAMESPACES:
            raise ChildBoundaryError(f"pytest-runtime-preloaded:{loaded}")
    stdlib_paths = _validated_stdlib_entries(arguments.stdlib_entry)
    dependency_root = (ROOT / DEPENDENCY_ROOT).resolve(strict=True)
    sys.path[:] = _authoritative_sys_path(runtime, dependency_root, stdlib_paths)
    stdlib_paths = sys.path[:-3]
    plugin = _load_exact_plugin(arguments.plugin_sha256)
    import pytest

    _validate_runtime_modules(runtime)
    pytest_args = _validated_pytest_args(arguments.pytest_args)
    args = ["-c", os.devnull, "--noconftest", *pytest_args]
    result = pytest.main(args, plugins=[plugin])
    _validate_runtime_modules(runtime)
    _validate_module_origins(
        materialized_files,
        runtime,
        tuple(Path(value) for value in dict.fromkeys(stdlib_paths)),
    )
    _validate_no_bytecode(materialized_files)
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
