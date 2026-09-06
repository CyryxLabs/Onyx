"""Default-off source bootstrap for the Google Workspace V1 branch."""
from __future__ import annotations

import os
import platform
import hashlib
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from types import CodeType, FunctionType, ModuleType


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
V24_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v24.pyw"
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_google_workspace_v1.pyw"
LIVE_FLAG = "ONYX_GOOGLE_WORKSPACE_LIVE_V1"
CONNECTOR_FLAG = "ONYX_GOOGLE_WORKSPACE_CONNECTOR_V1"
V24_BOOTSTRAP_SHA256 = "9bf8bbb7b1417d733d5218845c35ebe8daa39b22b8ac2d5102c3e44ccc343228"
LAUNCHER_SHA256 = (
    "040e361b288e7246e10f415fead0498816ff029ec183bb706cdd5f3d9337eddc"
)


def _verified_source(path: Path, digest: str) -> bytes:
    expected = path.resolve(strict=True)
    before = path.lstat()
    if (
        expected != path
        or not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or getattr(before, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise RuntimeError("Onyx authenticated script is invalid")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.lstat()
    def identity(value: os.stat_result) -> tuple[object, object, int, int]:
        return (
            getattr(value, "st_dev", None),
            getattr(value, "st_ino", None),
            value.st_size,
            value.st_mtime_ns,
        )
    source = b"".join(chunks)
    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(closed)
        or identity(closed) != identity(after)
        or path.resolve(strict=True) != path
        or hashlib.sha256(source).hexdigest() != digest
    ):
        raise RuntimeError("Onyx authenticated script drifted")
    return source


def _execute_verified(path: Path, digest: str, name: str) -> dict[str, object]:
    source = _verified_source(path, digest)
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
    previous = sys.modules.get(name)
    if previous is not None:
        raise RuntimeError("Onyx authenticated script target was preloaded")
    sys.modules[name] = module
    try:
        exec(compile(source, str(path), "exec", dont_inherit=True), module.__dict__)
        seal = module.__dict__.get("_AUTHENTICATED_SOURCE_SEAL")
        if seal is not None:
            module.__dict__["__onyx_authenticated_source_seal__"] = seal
        _verify_local_module(module, source, path, seal)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module.__dict__


def _verify_local_module(
    module: ModuleType, source: bytes, path: Path, seal: object | None
) -> None:
    if type(module) is not ModuleType or Path(module.__file__).resolve() != path:
        raise RuntimeError("Onyx authenticated module identity drifted")
    if seal is not None and (
        module.__dict__.get("__onyx_authenticated_source_seal__") is not seal
    ):
        raise RuntimeError("Onyx authenticated module seal drifted")
    compiled = compile(source, str(path), "exec", dont_inherit=True)
    expected = {
        item.co_name: item
        for item in compiled.co_consts
        if isinstance(item, CodeType) and not item.co_name.startswith("<")
    }
    for name, code in expected.items():
        runtime = module.__dict__.get(name)
        if isinstance(runtime, FunctionType):
            if (
                runtime.__globals__ is not module.__dict__
                or runtime.__code__.co_code != code.co_code
                or runtime.__code__.co_names != code.co_names
                or runtime.__code__.co_varnames != code.co_varnames
            ):
                raise RuntimeError("Onyx authenticated module code drifted")
            continue
        if not isinstance(runtime, type) or runtime.__module__ != module.__name__:
            raise RuntimeError("Onyx authenticated module definition drifted")
        methods = {
            item.co_name: item
            for item in code.co_consts
            if isinstance(item, CodeType) and not item.co_name.startswith("<")
        }
        for method_name, method_code in methods.items():
            candidate = runtime.__dict__.get(method_name)
            if isinstance(candidate, (classmethod, staticmethod)):
                candidate = candidate.__func__
            elif isinstance(candidate, property):
                candidate = candidate.fget
            if (
                not isinstance(candidate, FunctionType)
                or candidate.__globals__ is not module.__dict__
                or candidate.__code__.co_code != method_code.co_code
                or candidate.__code__.co_names != method_code.co_names
                or candidate.__code__.co_varnames != method_code.co_varnames
            ):
                raise RuntimeError("Onyx authenticated module class drifted")
    required = (
        ("_bootstrap_environment", "run")
        if path == V24_BOOTSTRAP
        else ("run",)
    )
    if any(type(module.__dict__.get(name)) is not FunctionType for name in required):
        raise RuntimeError("Onyx authenticated script contract drifted")


def _v24_contract() -> dict[str, object]:
    namespace = _execute_verified(
        V24_BOOTSTRAP,
        V24_BOOTSTRAP_SHA256,
        "onyx_v24_bootstrap_for_google_workspace_v1",
    )
    if not callable(namespace.get("_bootstrap_environment")):
        raise RuntimeError("Onyx V24 bootstrap contract is unavailable")
    return namespace


def _selection(environ: Mapping[str, str]) -> bool:
    matches = {
        canonical: tuple(
            key
            for key in environ
            if type(key) is str and key.casefold() == canonical.casefold()
        )
        for canonical in (LIVE_FLAG, CONNECTOR_FLAG)
    }
    if not matches[LIVE_FLAG] and not matches[CONNECTOR_FLAG]:
        return False
    if (
        matches[LIVE_FLAG] != (LIVE_FLAG,)
        or matches[CONNECTOR_FLAG] != (CONNECTOR_FLAG,)
        or environ[LIVE_FLAG] != "true"
        or environ[CONNECTOR_FLAG] != "true"
    ):
        raise RuntimeError("ONYX_GOOGLE_WORKSPACE_PARTIAL_CONFIGURATION_REFUSED")
    return True


def _bootstrap_environment(
    environ: Mapping[str, str],
) -> tuple[str, dict[str, str]]:
    enabled = _selection(environ)
    if not enabled:
        mode, prepared = _v24_contract()["_bootstrap_environment"](environ)
        return str(mode), dict(prepared)
    if platform.system() != "Windows":
        raise RuntimeError("ONYX_GOOGLE_WORKSPACE_WINDOWS_SOURCE_ONLY")
    return "google_workspace_v1", dict(environ)


def _run_v24(environment: Mapping[str, str]) -> None:
    os.environ.clear()
    os.environ.update(environment)
    namespace = _execute_verified(
        V24_BOOTSTRAP, V24_BOOTSTRAP_SHA256, "onyx_v24_bootstrap_execution"
    )
    namespace["run"]()


def run() -> None:
    accepted = (
        [],
        ["--preflight-only"],
        ["--governance-smoke-test"],
        ["--founder-smoke-test"],
        ["--document-intake-smoke-test"],
        ["--dayops-smoke-test"],
        ["--advanced-operations-smoke-test"],
        ["--advanced-commands-smoke-test"],
        ["--owner-context-smoke-test"],
        ["--operational-events-smoke-test"],
        ["--native-startup-smoke-test"],
    )
    if sys.argv[1:] not in accepted:
        raise RuntimeError("Onyx Google Workspace bootstrap arguments are invalid")
    mode, prepared = _bootstrap_environment(os.environ)
    if mode != "google_workspace_v1" or sys.argv[1:] not in (
        [],
        ["--native-startup-smoke-test"],
    ):
        _run_v24(prepared)
        return
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    namespace = _execute_verified(
        LAUNCHER, LAUNCHER_SHA256, "onyx_google_workspace_launcher_execution"
    )
    namespace["run"]()


if __name__ == "__main__":
    run()
