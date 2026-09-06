"""Authenticated source launcher for the Google Workspace V1 branch."""
from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import CodeType, FunctionType, ModuleType, SimpleNamespace


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
ACTIVATION = ROOT / "core" / "onyx_live_activation_google_workspace_v1.py"
ACTIVATION_SHA256 = (
    "97908192ac4cf7ac2b909f7d0871e77b5c6be78bdad42d55f0b4d19cffdb7204"
)


def _startup_log_path() -> Path:
    """Keep diagnostics outside the immutable source or packaged bundle."""

    override = os.environ.get("ONYX_DATA_DIR", "").strip()
    if override:
        base = Path(override).expanduser().resolve()
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = (
            Path(local)
            if local
            else Path.home() / "AppData" / "Local"
        ) / "Cyryx Labs" / "Onyx"
    elif sys.platform == "darwin":
        base = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Cyryx Labs"
            / "Onyx"
        )
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
        base = (
            Path(xdg_data).expanduser()
            if xdg_data
            else Path.home() / ".local" / "share"
        ) / "cyryx-labs" / "onyx"
    return base / "runtime" / "logs" / "onyx-google-workspace-v1-startup.log"


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
        raise RuntimeError("Onyx authenticated launcher is invalid")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
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
        raise RuntimeError("Onyx authenticated launcher drifted")
    return source


def _execute_verified(path: Path, digest: str, name: str) -> ModuleType:
    source = _verified_source(path, digest)
    if name in sys.modules:
        raise RuntimeError("Onyx authenticated launcher target was preloaded")
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
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
    return module


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
    runtime_entry = module.__dict__.get("activate_main")
    if (
        not isinstance(runtime_entry, FunctionType)
        or runtime_entry.__globals__ is not module.__dict__
    ):
        raise RuntimeError("Onyx authenticated activation entry drifted")
    if path == ACTIVATION and any(
        type(module.__dict__.get(name)) is not FunctionType
        for name in (
            "_assert_activation_critical_globals",
            "preflight_source_environment_v1",
            "activate_main",
        )
    ):
        raise RuntimeError("Onyx authenticated activation contract drifted")
    if path == ACTIVATION and (
        module.__dict__.get("V24_SHA256")
        != "a058c74fc9f80455b5f298d473775ece1f0ff805b774a9524a84d3de0493c82f"
        or module.__dict__.get("EXPECTED_AGGREGATE")
        != "d3962996733c76e99046cb46949a9f8fed630d0a0ad1b00ac368cc355c7426bc"
        or module.__dict__.get("_V23_SHA256")
        != "207aec29d0e87a874b3641162f53250382fe18f2dfc2998b68d3702b82d85607"
        or module.__dict__.get("_LOCAL_CLOSURE_COUNT") != 1030
        or module.__dict__.get("_LOCAL_CLOSURE_AGGREGATE")
        != "9f9376302bdb2a640aab798eda3a117e14c244b1f27c704aa64d0cc862d6132e"
    ):
        raise RuntimeError("Onyx activation critical globals drifted")


def _activation_contract() -> ModuleType:
    name = "core.onyx_live_activation_google_workspace_v1"
    if name in sys.modules:
        raise RuntimeError("Onyx Google activation target was preloaded")
    return _execute_verified(ACTIVATION, ACTIVATION_SHA256, name)


def _sanitized_startup_failure(log_path: Path) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            print(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                "Onyx Google Workspace V1 startup failed safely",
                file=log,
            )
    except BaseException:
        pass


def _sanitized_cleanup_failure(log_path: Path) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            print(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                "Onyx Google Workspace V1 cleanup remains pending",
                file=log,
            )
    except BaseException:
        pass


class _PreflightUI:
    def __init__(self) -> None:
        self.muted = True
        self.current_file = None
        self.trusted_ui_prompts = 0

    def write_log(self, _value: str) -> None:
        pass

    def set_state(self, _value: str) -> None:
        pass


def run() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if sys.argv[1:] not in ([], ["--native-startup-smoke-test"]):
        raise RuntimeError("Onyx Google Workspace launcher arguments are invalid")

    controller = None
    smoke_instance = None
    primary_error: RuntimeError | None = None
    log_path = _startup_log_path()
    try:
        activation = _activation_contract()
        controller = activation.activate_main(os.environ)
        if sys.argv[1:] == ["--native-startup-smoke-test"]:
            smoke_instance = controller.instantiate_live(_PreflightUI())
            smoke_result = asyncio.run(
                smoke_instance._execute_tool(
                    SimpleNamespace(
                        id="google-workspace-native-smoke",
                        name="google_workspace",
                        args={"action": "status"},
                    )
                )
            )
            response = getattr(smoke_result, "response", None)
            if type(response) is not dict or response.get("status") != "succeeded":
                raise RuntimeError(
                    "Onyx Google Workspace native smoke failed"
                ) from None
        else:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8", buffering=1) as log:
                sys.stdout = log
                sys.stderr = log
                print(
                    f"\n[{datetime.now(timezone.utc).isoformat()}] "
                    "Onyx Google Workspace V1 source branch starting"
                )
                controller.run_runtime()
    except BaseException:
        _sanitized_startup_failure(log_path)
        primary_error = RuntimeError(
            "Onyx Google Workspace startup failed safely"
        )
    cleanup_failed = False
    if smoke_instance is not None:
        try:
            smoke_instance.close()
        except BaseException:
            cleanup_failed = True
    if controller is not None:
        rolled_back = False
        for _attempt in range(3):
            try:
                controller.rollback_all()
            except BaseException:
                continue
            rolled_back = True
            break
        cleanup_failed = cleanup_failed or not rolled_back
    if cleanup_failed:
        _sanitized_cleanup_failure(log_path)
        if primary_error is not None:
            primary_error.add_note(
                "Onyx Google Workspace cleanup also remains pending"
            )
        else:
            raise RuntimeError(
                "Onyx Google Workspace rollback remains pending"
            ) from None
    if primary_error is not None:
        raise primary_error from None


if __name__ == "__main__":
    run()
