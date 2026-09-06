"""Source-only, default-off Google Workspace composition over exact V24.

The module deliberately has no Google Workspace import at module scope.  The
enabled branch authenticates the current Cyryx successor manifest and all seven
pinned dependencies before importing the connector, host, or live adapter.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import importlib.abc
import importlib.util
import json
import os
import re
import secrets
import stat
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import CodeType, FunctionType, ModuleType
from typing import Final


LIVE_FLAG: Final = "ONYX_GOOGLE_WORKSPACE_LIVE_V1"
CONNECTOR_FLAG: Final = "ONYX_GOOGLE_WORKSPACE_CONNECTOR_V1"
ENABLED_VALUE: Final = "true"
TOOL_NAME: Final = "google_workspace"
HOST_MARKER: Final = "_google_workspace_live_v1"
MODULE_MARKER: Final = "_onyx_live_activation_google_workspace_v1"
V24_MARKER: Final = "_onyx_live_activation_v24"
V24_RELATIVE_PATH: Final = Path("core") / "onyx_live_activation_v24.py"
V24_SHA256: Final = "a058c74fc9f80455b5f298d473775ece1f0ff805b774a9524a84d3de0493c82f"
MANIFEST_RELATIVE_PATH: Final = (
    Path("docs")
    / "onyx"
    / "evidence"
    / "ONYX_GWS_1_0_1_1_SOURCE_PROVENANCE_20260905.json"
)
MANIFEST_SCHEMA: Final = "onyx.gws.source-provenance-evidence.v1"
EXPECTED_AGGREGATE: Final = (
    "d3962996733c76e99046cb46949a9f8fed630d0a0ad1b00ac368cc355c7426bc"
)
_PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
_CONFIG_FIELDS: Final = {
    "owner_id": "ONYX_GOOGLE_WORKSPACE_OWNER_ID",
    "workspace_id": "ONYX_GOOGLE_WORKSPACE_WORKSPACE_ID",
    "account_id": "ONYX_GOOGLE_WORKSPACE_ACCOUNT_ID",
    "client_id": "ONYX_GOOGLE_WORKSPACE_CLIENT_ID",
    "callback_port": "ONYX_GOOGLE_WORKSPACE_CALLBACK_PORT",
}
_EXPECTED_DEPENDENCIES: Final = {
    "core/google_workspace_connector_v1.py": (
        120549,
        "084c8dba0f1af73babfac977b4dabe7e8bc7be2126e48b91a9d2696a7a91fc5d",
    ),
    "core/google_workspace_host_v1.py": (
        123742,
        "5c9d9d332de3c3c7dac1e5f612c6fdf7ffbfeaedd2a5ad9fcdd81376c5c2c7fc",
    ),
    "docs/stories/ONYX-GWS-1.0.0.md": (
        20333,
        "ba9f853e56da927db97965c3c1e79e24b8a5b65374eb522b16c6bfeae33dd279",
    ),
    "docs/stories/ONYX-GWS-1.1.0.md": (
        36832,
        "032c05eb2cb7a7c89201ad5ae8ce0be041ebdc6ab0adddd8f2781a57ceefb604",
    ),
    "scripts/onyx_google_workspace.py": (
        11127,
        "a2ab58b19950fe7a3d189eb404eba3e52cefd1fa2501a559f4d55590adb605ad",
    ),
    "tests/test_google_workspace_connector_v1.py": (
        60347,
        "7e947babf5775850cdc7202802520c65389a3c95d73ae37edddb172dbe7f71fc",
    ),
    "tests/test_google_workspace_host_v1.py": (
        85242,
        "c61698ff1b08d67806b36eebb0458e8b396bedaff8b7fbe819819721a1a560ae",
    ),
}
_ENABLED_RUNTIME_DEPENDENCIES: Final = {
    "core.paths": (
        Path("core/paths.py"),
        "59a881f574b8725bb22dc70ead88866671ed8a67f2fc3dc84bf90b78a243cfa0",
    ),
    "core.tool_audit": (
        Path("core/tool_audit.py"),
        "cee6de35023ccb6955478e9d648c17e6a7b58070eeeedb1885ea02374ed55437",
    ),
    "core.permission_broker": (
        Path("core/permission_broker.py"),
        "5b19f5d7ceab445af616c5c7c66bd8d9f8dd1f9a9b7e9f02e3a35372d06c4e07",
    ),
    "core.native_vault": (
        Path("core/native_vault.py"),
        "526be0df7c9e4ef5a2d63391a0f3f8293f2f257a8e39f6e468cd8801a60cd5d5",
    ),
    "core.google_workspace_connector_v1": (
        Path("core/google_workspace_connector_v1.py"),
        _EXPECTED_DEPENDENCIES["core/google_workspace_connector_v1.py"][1],
    ),
    "core.google_workspace_host_v1": (
        Path("core/google_workspace_host_v1.py"),
        _EXPECTED_DEPENDENCIES["core/google_workspace_host_v1.py"][1],
    ),
    "core.google_workspace_live_v1": (
        Path("core/google_workspace_live_v1.py"),
        "641ac4b8cc938aff87335219cae6bcfc8cefd49011f323066dd56400399bc98a",
    ),
    "core.google_workspace_audit_v1": (
        Path("core/google_workspace_audit_v1.py"),
        "df02644a0a40b359305c469b0f4346f22fbc21c8f2c686f688d87b924997250e",
    ),
}
_IDENTIFIER: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+-]{0,254}")
_EMAIL: Final = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_CLIENT_ID: Final = re.compile(r"[A-Za-z0-9._:-]{10,512}")
_AUTHENTICATED_SOURCE_SEAL: Final = object()
_DECLARATION_LOCK: Final = threading.RLock()
_PENDING_CLEANUP_LOCK: Final = threading.RLock()
_PENDING_SOURCE_SESSION: object | None = None
_PENDING_ACTIVATION_CONTROLLER: object | None = None
_ROLLBACK_DRAIN_SECONDS: Final = 10.0
_DISPATCH_TIMEOUT_SECONDS: Final = 30.0
_RUNTIME_LOCAL_ROOTS: Final = ("actions", "core", "dashboard", "memory")
_PREDECESSOR_SCRIPT_PATHS: Final = {
    f"scripts.launch_onyx_live_v{version}": Path(
        f"scripts/launch_onyx_live_v{version}.pyw"
    )
    for version in range(19, 24)
}
_BUILD_ONLY_SCRIPT_MODULES: Final = frozenset(
    {
        "scripts.generate_phase5_current_successor_transition_v47",
        "scripts.generate_phase5_current_successor_transition_v48",
        "scripts.generate_release_workflow_v46",
        "scripts.generate_release_workflow_v47",
        "scripts.generate_release_workflow_v48",
        "scripts.verify_release_workflow_v46",
        "scripts.verify_release_workflow_v47",
        "scripts.verify_release_workflow_v48",
        "scripts.generate_release_workflow_v95",
        "scripts.generate_release_workflow_v96",
        "scripts.verify_release_workflow_v95",
        "scripts.verify_release_workflow_v96",
        "scripts.verify_current_successor_retirement_v1",
        "scripts.verify_phase5_exit_retirement_v1",
    }
)
_LOCAL_CLOSURE_COUNT: Final = 1030
_LOCAL_CLOSURE_AGGREGATE: Final = (
    "9f9376302bdb2a640aab798eda3a117e14c244b1f27c704aa64d0cc862d6132e"
)
_V23_SHA256: Final = "207aec29d0e87a874b3641162f53250382fe18f2dfc2998b68d3702b82d85607"


def _assert_activation_critical_globals() -> None:
    expected = {
        "core.paths": (
            Path("core/paths.py"),
            "59a881f574b8725bb22dc70ead88866671ed8a67f2fc3dc84bf90b78a243cfa0",
        ),
        "core.tool_audit": (
            Path("core/tool_audit.py"),
            "cee6de35023ccb6955478e9d648c17e6a7b58070eeeedb1885ea02374ed55437",
        ),
        "core.permission_broker": (
            Path("core/permission_broker.py"),
            "5b19f5d7ceab445af616c5c7c66bd8d9f8dd1f9a9b7e9f02e3a35372d06c4e07",
        ),
        "core.native_vault": (
            Path("core/native_vault.py"),
            "526be0df7c9e4ef5a2d63391a0f3f8293f2f257a8e39f6e468cd8801a60cd5d5",
        ),
        "core.google_workspace_connector_v1": (
            Path("core/google_workspace_connector_v1.py"),
            "084c8dba0f1af73babfac977b4dabe7e8bc7be2126e48b91a9d2696a7a91fc5d",
        ),
        "core.google_workspace_host_v1": (
            Path("core/google_workspace_host_v1.py"),
            "5c9d9d332de3c3c7dac1e5f612c6fdf7ffbfeaedd2a5ad9fcdd81376c5c2c7fc",
        ),
        "core.google_workspace_live_v1": (
            Path("core/google_workspace_live_v1.py"),
            "641ac4b8cc938aff87335219cae6bcfc8cefd49011f323066dd56400399bc98a",
        ),
        "core.google_workspace_audit_v1": (
            Path("core/google_workspace_audit_v1.py"),
            "df02644a0a40b359305c469b0f4346f22fbc21c8f2c686f688d87b924997250e",
        ),
    }
    if (
        _ENABLED_RUNTIME_DEPENDENCIES != expected
        or V24_SHA256
        != "a058c74fc9f80455b5f298d473775ece1f0ff805b774a9524a84d3de0493c82f"
        or EXPECTED_AGGREGATE
        != "d3962996733c76e99046cb46949a9f8fed630d0a0ad1b00ac368cc355c7426bc"
        or _LOCAL_CLOSURE_COUNT != 1030
        or _LOCAL_CLOSURE_AGGREGATE
        != "9f9376302bdb2a640aab798eda3a117e14c244b1f27c704aa64d0cc862d6132e"
        or _BUILD_ONLY_SCRIPT_MODULES
        != frozenset(
            {
                "scripts.generate_phase5_current_successor_transition_v47",
                "scripts.generate_phase5_current_successor_transition_v48",
                "scripts.generate_release_workflow_v46",
                "scripts.generate_release_workflow_v47",
                "scripts.generate_release_workflow_v48",
                "scripts.verify_release_workflow_v46",
                "scripts.verify_release_workflow_v47",
                "scripts.verify_release_workflow_v48",
        "scripts.generate_release_workflow_v95",
        "scripts.generate_release_workflow_v96",
        "scripts.verify_release_workflow_v95",
        "scripts.verify_release_workflow_v96",
                "scripts.verify_current_successor_retirement_v1",
                "scripts.verify_phase5_exit_retirement_v1",
            }
        )
        or _V23_SHA256
        != "207aec29d0e87a874b3641162f53250382fe18f2dfc2998b68d3702b82d85607"
    ):
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace activation critical globals drifted"
        )


class GoogleWorkspaceActivationV1Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class GoogleWorkspaceRawConfigurationV1:
    owner_id: str
    workspace_id: str
    account_id: str
    client_id: str
    callback_port: int


@dataclass(frozen=True, slots=True)
class GoogleWorkspaceHostContractV1:
    module: ModuleType
    onyx_live: type
    project: Path
    base: object


@dataclass(slots=True)
class _BindingV1:
    instance: object
    previous_class: type
    guarded_class: type
    owned_dispatch: object
    owned_setattr: object


def _relevant_keys(source: Mapping[str, str], canonical: str) -> tuple[str, ...]:
    return tuple(
        key
        for key in source
        if type(key) is str and key.casefold() == canonical.casefold()
    )


def google_workspace_selection_v1(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Parse only the exact case-sensitive dual opt-in pair."""

    source = os.environ if environ is None else environ
    live = _relevant_keys(source, LIVE_FLAG)
    connector = _relevant_keys(source, CONNECTOR_FLAG)
    if not live and not connector:
        return False
    if live != (LIVE_FLAG,) or connector != (CONNECTOR_FLAG,):
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace activation flags are noncanonical"
        )
    if source[LIVE_FLAG] != ENABLED_VALUE or source[CONNECTOR_FLAG] != ENABLED_VALUE:
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace activation flags are noncanonical"
        )
    return True


def _raw_configuration(source: Mapping[str, str]) -> GoogleWorkspaceRawConfigurationV1:
    values: dict[str, str] = {}
    for field, canonical in _CONFIG_FIELDS.items():
        matches = _relevant_keys(source, canonical)
        if matches != (canonical,):
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace host configuration is noncanonical"
            )
        value = source[canonical]
        if type(value) is not str or value != value.strip() or not value:
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace host configuration is noncanonical"
            )
        values[field] = value
    if (
        _IDENTIFIER.fullmatch(values["owner_id"]) is None
        or _IDENTIFIER.fullmatch(values["workspace_id"]) is None
        or _EMAIL.fullmatch(values["account_id"]) is None
        or values["account_id"] != values["account_id"].casefold()
        or _CLIENT_ID.fullmatch(values["client_id"]) is None
        or not values["callback_port"].isascii()
        or not values["callback_port"].isdigit()
    ):
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace host configuration is noncanonical"
        )
    port = int(values["callback_port"])
    if not 1024 <= port <= 65535 or str(port) != values["callback_port"]:
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace host configuration is noncanonical"
        )
    return GoogleWorkspaceRawConfigurationV1(
        values["owner_id"],
        values["workspace_id"],
        values["account_id"],
        values["client_id"],
        port,
    )


def restore_v24_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    for name in (LIVE_FLAG, CONNECTOR_FLAG, *_CONFIG_FIELDS.values()):
        for key in tuple(result):
            if type(key) is str and key.casefold() == name.casefold():
                result.pop(key, None)
    return result


def _stable_regular_bytes(path: Path, *, root: Path) -> bytes:
    expected = root / path
    try:
        resolved = expected.resolve(strict=True)
        info = expected.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if (
            resolved != expected
            or not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise OSError("source entry is not stable")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(expected, flags)
        try:
            before = os.fstat(descriptor)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        final_info = expected.lstat()
        final_resolved = expected.resolve(strict=True)
    except OSError:
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace source provenance is unavailable"
        ) from None
    def identity(item: os.stat_result) -> tuple[object, object, int, int]:
        return (
            getattr(item, "st_dev", None),
            getattr(item, "st_ino", None),
            item.st_size,
            item.st_mtime_ns,
        )
    if (
        identity(info) != identity(before)
        or identity(before) != identity(after)
        or identity(after) != identity(final_info)
        or final_resolved != expected
    ):
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace source provenance changed during verification"
        )
    return b"".join(chunks)


def _code_payload(code: CodeType) -> object:
    def constant(value: object) -> object:
        if isinstance(value, CodeType):
            return _code_payload(value)
        if value is None or isinstance(value, (bool, int, float, str)):
            return [type(value).__name__, value]
        if isinstance(value, bytes):
            return ["bytes", value.hex()]
        if isinstance(value, tuple):
            return ["tuple", [constant(item) for item in value]]
        if isinstance(value, frozenset):
            items = [constant(item) for item in value]
            return ["frozenset", sorted(items, key=lambda item: json.dumps(item))]
        return [type(value).__name__, repr(value)]

    return {
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "stacksize": code.co_stacksize,
        "flags": code.co_flags,
        "code": code.co_code.hex(),
        "consts": [constant(value) for value in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
        "name": code.co_name,
        "qualname": code.co_qualname,
        "firstlineno": code.co_firstlineno,
        "linetable": code.co_linetable.hex(),
        "exceptiontable": code.co_exceptiontable.hex(),
    }


def _fingerprint(code: CodeType) -> str:
    return hashlib.sha256(
        json.dumps(
            _code_payload(code), sort_keys=True, separators=(",", ":")
        ).encode("ascii")
    ).hexdigest()


def _matches_verified_source_function(
    candidate: object, expected: CodeType, module: ModuleType
) -> bool:
    if not isinstance(candidate, FunctionType):
        return False
    if (
        candidate.__globals__ is module.__dict__
        and _fingerprint(candidate.__code__) == _fingerprint(expected)
    ):
        return True
    wrapped = getattr(candidate, "__wrapped__", None)
    return bool(
        isinstance(wrapped, FunctionType)
        and wrapped.__globals__ is module.__dict__
        and _fingerprint(wrapped.__code__) == _fingerprint(expected)
        and candidate.__code__.co_name == "helper"
        and Path(candidate.__code__.co_filename).name == "contextlib.py"
        and candidate.__globals__.get("__name__") == "contextlib"
    )


def _verify_executed_module(module: ModuleType, source: bytes, path: Path) -> None:
    if (
        type(module) is not ModuleType
        or Path(getattr(module, "__file__", "")).resolve() != path
        or module.__dict__.get("__onyx_authenticated_source_seal__")
        is not _AUTHENTICATED_SOURCE_SEAL
    ):
        raise GoogleWorkspaceActivationV1Error(
            "authenticated source module identity drifted"
        )
    compiled = compile(source, str(path), "exec", dont_inherit=True)
    expected = {
        value.co_name: value
        for value in compiled.co_consts
        if isinstance(value, CodeType) and not value.co_name.startswith("<")
    }
    for name, expected_code in expected.items():
        runtime = module.__dict__.get(name)
        if isinstance(runtime, FunctionType):
            if not _matches_verified_source_function(
                runtime, expected_code, module
            ):
                raise GoogleWorkspaceActivationV1Error(
                    "authenticated source function drifted"
                )
        elif isinstance(runtime, type) and runtime.__module__ == module.__name__:
            methods: dict[str, list[CodeType]] = {}
            for value in expected_code.co_consts:
                if isinstance(value, CodeType) and not value.co_name.startswith("<"):
                    methods.setdefault(value.co_name, []).append(value)
            for method_name, expected_methods in methods.items():
                candidate = runtime.__dict__.get(method_name)
                if isinstance(candidate, (classmethod, staticmethod)):
                    candidates = (candidate.__func__,)
                elif isinstance(candidate, property) or isinstance(
                    getattr(candidate, "fget", None), FunctionType
                ):
                    candidates = tuple(
                        item
                        for item in (
                            getattr(candidate, "fget", None),
                            getattr(candidate, "fset", None),
                            getattr(candidate, "fdel", None),
                        )
                        if isinstance(item, FunctionType)
                    )
                else:
                    candidates = (candidate,)
                if any(
                    not any(
                        _matches_verified_source_function(
                            candidate_function, expected_method, module
                        )
                        for candidate_function in candidates
                    )
                    for expected_method in expected_methods
                ) or any(
                    not any(
                        _matches_verified_source_function(
                            candidate_function, expected_method, module
                        )
                        for expected_method in expected_methods
                    )
                    for candidate_function in candidates
                ):
                    raise GoogleWorkspaceActivationV1Error(
                        "authenticated source method drifted"
                    )
        else:
            raise GoogleWorkspaceActivationV1Error(
                "authenticated source definition drifted"
            )


def _runtime_module_code_seal(module: ModuleType) -> str:
    records: list[tuple[str, str]] = []

    def add_function(label: str, candidate: object) -> None:
        function = candidate
        if isinstance(function, (classmethod, staticmethod)):
            function = function.__func__
        if isinstance(function, FunctionType):
            if function.__globals__ is module.__dict__:
                records.append((label, _fingerprint(function.__code__)))
                return
            wrapped = getattr(function, "__wrapped__", None)
            if (
                isinstance(wrapped, FunctionType)
                and wrapped.__globals__ is module.__dict__
            ):
                records.append((label, _fingerprint(wrapped.__code__)))

    for name, value in sorted(module.__dict__.items()):
        add_function(name, value)
        if isinstance(value, type) and value.__module__ == module.__name__:
            for method_name, candidate in sorted(value.__dict__.items()):
                if isinstance(candidate, property) or isinstance(
                    getattr(candidate, "fget", None), FunctionType
                ):
                    for accessor_name in ("fget", "fset", "fdel"):
                        accessor = getattr(candidate, accessor_name, None)
                        if accessor is not None:
                            add_function(
                                f"{name}.{method_name}.{accessor_name}", accessor
                            )
                else:
                    add_function(f"{name}.{method_name}", candidate)
    return hashlib.sha256(
        json.dumps(records, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def _local_module_relative(name: str) -> Path | None:
    if name in _PREDECESSOR_SCRIPT_PATHS:
        return _PREDECESSOR_SCRIPT_PATHS[name]
    if name in {"main", "ui"}:
        return Path(f"{name}.py")
    parts = name.split(".")
    if not parts or parts[0] not in {*_RUNTIME_LOCAL_ROOTS, "scripts"}:
        return None
    base = Path(*parts)
    candidates = [base.with_suffix(".py"), base / "__init__.py"]
    if parts[0] == "scripts":
        candidates.insert(1, base.with_suffix(".pyw"))
    for relative in candidates:
        if (_PROJECT_ROOT / relative).is_file():
            return relative
    return None


def _captured_local_closure() -> tuple[dict[str, tuple[Path, bytes]], str]:
    captured: dict[str, tuple[Path, bytes]] = {}
    for root_name in _RUNTIME_LOCAL_ROOTS:
        root = _PROJECT_ROOT / root_name
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(_PROJECT_ROOT)
            suffix = relative.with_suffix("").parts
            name = ".".join(
                suffix[:-1] if suffix[-1] == "__init__" else suffix
            )
            if name == "core.onyx_live_activation_google_workspace_v1":
                continue
            captured[name] = (
                relative,
                _stable_regular_bytes(relative, root=_PROJECT_ROOT),
            )
    scripts_root = _PROJECT_ROOT / "scripts"
    for pattern in ("*.py", "*.pyw"):
        for path in sorted(scripts_root.rglob(pattern)):
            relative = path.relative_to(_PROJECT_ROOT)
            suffix = relative.with_suffix("").parts
            name = ".".join(
                suffix[:-1] if suffix[-1] == "__init__" else suffix
            )
            if name in {
                "scripts.bootstrap_onyx_live_google_workspace_v1",
                "scripts.launch_onyx_live_google_workspace_v1",
            } | _BUILD_ONLY_SCRIPT_MODULES:
                continue
            captured[name] = (
                relative,
                _stable_regular_bytes(relative, root=_PROJECT_ROOT),
            )
    for name in ("main", "ui", "scripts"):
        relative = _local_module_relative(name)
        if relative is None:
            raise GoogleWorkspaceActivationV1Error(
                "authenticated local closure is incomplete"
            )
        captured[name] = (
            relative,
            _stable_regular_bytes(relative, root=_PROJECT_ROOT),
        )
    canonical = "".join(
        f"{name}|{relative.as_posix()}|{len(source)}|"
        f"{hashlib.sha256(source).hexdigest()}\n"
        for name, (relative, source) in sorted(captured.items())
    )
    aggregate = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if (
        len(captured) != _LOCAL_CLOSURE_COUNT
        or aggregate != _LOCAL_CLOSURE_AGGREGATE
    ):
        raise GoogleWorkspaceActivationV1Error(
            "authenticated local closure drifted"
        )
    return captured, aggregate


class _CapturedClosureFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, captured: dict[str, tuple[Path, bytes]]) -> None:
        self._captured = captured
        self.loaded: list[ModuleType] = []
        self.seals: dict[str, str] = {}

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> object:
        del path, target
        if fullname in self._captured:
            relative = self._captured[fullname][0]
            return importlib.util.spec_from_loader(
                fullname,
                self,
                is_package=relative.name == "__init__.py",
            )
        if _local_module_relative(fullname) is not None:
            raise GoogleWorkspaceActivationV1Error(
                "unpinned local closure import was denied"
            )
        return None

    @staticmethod
    def create_module(spec: object) -> None:
        del spec
        return None

    def exec_module(self, module: ModuleType) -> None:
        name = module.__name__
        relative, source = self._captured[name]
        path = _PROJECT_ROOT / relative
        module.__file__ = str(path)
        is_package = relative.name == "__init__.py"
        module.__package__ = name if is_package else name.rpartition(".")[0]
        if is_package:
            module.__path__ = [str(path.parent)]  # type: ignore[attr-defined]
        module.__dict__["__onyx_authenticated_source_seal__"] = (
            _AUTHENTICATED_SOURCE_SEAL
        )
        exec(
            compile(source, str(path), "exec", dont_inherit=True),
            module.__dict__,
        )
        _verify_executed_module(module, source, path)
        self.seals[name] = _runtime_module_code_seal(module)
        self.loaded.append(module)


class GoogleWorkspaceSourcePreflightV1:
    """Controller-owned authenticated source session and lazy import authority."""

    __slots__ = (
        "aggregate_sha256",
        "base_environment",
        "closure_modules",
        "configuration",
        "runtime_modules",
        "v24",
        "_active",
        "_captured",
        "_finder",
        "_lock",
    )

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._lock = threading.RLock()
        self._active = False
        self._captured: dict[str, tuple[Path, bytes]] = {}
        self._finder: _CapturedClosureFinder | None = None
        self.aggregate_sha256 = ""
        self.base_environment: dict[str, str] = {}
        self.configuration: GoogleWorkspaceRawConfigurationV1 | None = None
        self.runtime_modules: tuple[ModuleType, ...] = ()
        self.closure_modules: tuple[ModuleType, ...] = ()
        self.v24: ModuleType | None = None
        self._start(os.environ if environ is None else environ)

    def _start(self, source: Mapping[str, str]) -> None:
        _assert_activation_critical_globals()
        if not google_workspace_selection_v1(source):
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace source activation is disabled"
            )
        configuration = _raw_configuration(source)
        aggregate = verify_source_provenance_v1()
        captured, _closure_aggregate = _captured_local_closure()
        allowed_preloaded = {
            "core",
            "core.onyx_live_activation_google_workspace_v1",
        }
        if any(
            name in sys.modules and name not in allowed_preloaded
            for name in captured
        ):
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace dependencies were imported before provenance"
            )
        finder = _CapturedClosureFinder(captured)
        sys.meta_path.insert(0, finder)
        self._captured = captured
        self._finder = finder
        self._active = True
        failure = ""
        try:
            modules = tuple(
                self.load(name) for name in _ENABLED_RUNTIME_DEPENDENCIES
            )
            self.load("core.onyx_live_activation_v23")
            v24 = self.load("core.onyx_live_activation_v24")
            self._attest_v24(v24)
        except BaseException as error:
            failure = (
                str(error)
                if type(error) is GoogleWorkspaceActivationV1Error
                else "authenticated source closure failed"
            )
        if failure:
            try:
                self._close_owned_modules()
            except BaseException:
                _retain_pending_source_session(self)
                raise GoogleWorkspaceActivationV1Error(
                    "authenticated source session rollback is pending"
                ) from None
            raise GoogleWorkspaceActivationV1Error(failure) from None
        self.aggregate_sha256 = aggregate
        restored = restore_v24_environment(source)
        if (
            "ONYX_LIVE_ACTIVATION_V24" not in restored
            and "ONYX_LIVE_ROLLBACK_V24" not in restored
        ):
            canonical = dict(restored)
            canonical.update(v24.exact_activation_environment((_PROJECT_ROOT,)))
            restored = canonical
        try:
            v24.ActivationFlagsV24.from_canonical_environ(restored)
        except BaseException:
            self._close_owned_modules()
            raise GoogleWorkspaceActivationV1Error(
                "authenticated V24 environment is unavailable"
            ) from None
        self.base_environment = restored
        self.configuration = configuration
        self.runtime_modules = modules
        self.v24 = v24
        self._refresh_closure_modules()

    def _refresh_closure_modules(self) -> None:
        finder = self._finder
        self.closure_modules = () if finder is None else tuple(finder.loaded)

    def _attest_v24(self, module: ModuleType) -> None:
        finder = self._finder
        public_predecessor = sys.modules.get("core.onyx_live_activation_v23")
        private_predecessor = getattr(module, "v23", None)
        if (
            finder is None
            or type(module) is not ModuleType
            or type(public_predecessor) is not ModuleType
            or type(private_predecessor) is not ModuleType
            or module.__dict__.get("V23_SHA256") != _V23_SHA256
            or private_predecessor.__dict__.get(
                "__onyx_authenticated_source_sha256__"
            )
            != _V23_SHA256
            or Path(getattr(private_predecessor, "__file__", "")).resolve()
            != _PROJECT_ROOT / "core" / "onyx_live_activation_v23.py"
            or finder.seals.get(public_predecessor.__name__)
            != _runtime_module_code_seal(public_predecessor)
            or _runtime_module_code_seal(private_predecessor)
            != _runtime_module_code_seal(public_predecessor)
        ):
            raise GoogleWorkspaceActivationV1Error(
                "authenticated V24 predecessor chain drifted"
            )

    def assert_healthy(self) -> None:
        with self._lock:
            finder = self._finder
            if (
                not self._active
                or finder is None
                or not sys.meta_path
                or sys.meta_path[0] is not finder
            ):
                raise GoogleWorkspaceActivationV1Error(
                    "authenticated source session is unhealthy"
                )
            for module in finder.loaded:
                name = module.__name__
                captured = self._captured.get(name)
                if (
                    captured is None
                    or sys.modules.get(name) is not module
                    or module.__dict__.get("__onyx_authenticated_source_seal__")
                    is not _AUTHENTICATED_SOURCE_SEAL
                    or Path(getattr(module, "__file__", "")).resolve()
                    != _PROJECT_ROOT / captured[0]
                    or finder.seals.get(name) != _runtime_module_code_seal(module)
                ):
                    raise GoogleWorkspaceActivationV1Error(
                        "authenticated source session is unhealthy"
                    )

    def accept_v24_runtime_mutations(self) -> None:
        """Seal the exact, authenticated Windows mutations made by V24 install."""

        expected = {"core.phase11_live_mission_v1", "main", "ui"}
        with self._lock:
            finder = self._finder
            if (
                not self._active
                or finder is None
                or not sys.meta_path
                or sys.meta_path[0] is not finder
            ):
                raise GoogleWorkspaceActivationV1Error(
                    "authenticated source session is unhealthy"
                )
            changed: set[str] = set()
            for module in finder.loaded:
                name = module.__name__
                captured = self._captured.get(name)
                if (
                    captured is None
                    or sys.modules.get(name) is not module
                    or module.__dict__.get("__onyx_authenticated_source_seal__")
                    is not _AUTHENTICATED_SOURCE_SEAL
                    or Path(getattr(module, "__file__", "")).resolve()
                    != _PROJECT_ROOT / captured[0]
                ):
                    raise GoogleWorkspaceActivationV1Error(
                        "authenticated source session is unhealthy"
                    )
                if finder.seals.get(name) != _runtime_module_code_seal(module):
                    changed.add(name)
            if changed != expected:
                raise GoogleWorkspaceActivationV1Error(
                    "authenticated V24 runtime mutation set drifted"
                )
            for module in finder.loaded:
                if module.__name__ in expected:
                    finder.seals[module.__name__] = _runtime_module_code_seal(module)
            self.assert_healthy()

    def load(self, name: str) -> ModuleType:
        with self._lock:
            self.assert_healthy()
            finder = self._finder
            if (
                not self._active
                or finder is None
                or not sys.meta_path
                or sys.meta_path[0] is not finder
                or name not in self._captured
            ):
                raise GoogleWorkspaceActivationV1Error(
                    "authenticated source session is unavailable"
                )
            existing = sys.modules.get(name)
            if existing is not None and all(
                existing is not loaded for loaded in finder.loaded
            ):
                raise GoogleWorkspaceActivationV1Error(
                    "authenticated source target was preloaded"
                )
            try:
                module = importlib.import_module(name)
            except BaseException:
                raise GoogleWorkspaceActivationV1Error(
                    f"authenticated lazy import failed: {name}"
                ) from None
            if (
                type(module) is not ModuleType
                or module not in finder.loaded
                or sys.modules.get(name) is not module
            ):
                raise GoogleWorkspaceActivationV1Error(
                    "authenticated lazy import drifted"
                )
            self._refresh_closure_modules()
            return module

    def _close_owned_modules(self) -> None:
        finder = self._finder
        if finder is None or finder not in sys.meta_path:
            raise GoogleWorkspaceActivationV1Error(
                "authenticated source session rollback is pending"
            ) from None
        if any(
            sys.modules.get(module.__name__) not in {None, module}
            for module in finder.loaded
        ):
            raise GoogleWorkspaceActivationV1Error(
                "authenticated source session rollback is pending"
            ) from None
        failed = False
        for module in reversed(tuple(finder.loaded)):
            name = module.__name__
            if sys.modules.get(name) is module:
                removed = sys.modules.pop(name, None)
                if removed is not module:
                    failed = True
                    break
        if failed:
            raise GoogleWorkspaceActivationV1Error(
                "authenticated source session rollback is pending"
            ) from None
        try:
            sys.meta_path.remove(finder)
        except ValueError:
            raise GoogleWorkspaceActivationV1Error(
                "authenticated source session rollback is pending"
            ) from None
        self._active = False
        self._finder = None
        self.closure_modules = ()

    def close(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._close_owned_modules()


def _retain_pending_source_session(
    session: GoogleWorkspaceSourcePreflightV1,
) -> None:
    global _PENDING_SOURCE_SESSION
    with _PENDING_CLEANUP_LOCK:
        if _PENDING_SOURCE_SESSION not in {None, session}:
            raise GoogleWorkspaceActivationV1Error(
                "authenticated source cleanup authority is already retained"
            ) from None
        _PENDING_SOURCE_SESSION = session


def retry_pending_source_cleanup_v1() -> bool:
    global _PENDING_SOURCE_SESSION
    with _PENDING_CLEANUP_LOCK:
        session = _PENDING_SOURCE_SESSION
    if session is None:
        return True
    if type(session) is not GoogleWorkspaceSourcePreflightV1:
        raise GoogleWorkspaceActivationV1Error(
            "authenticated source cleanup authority drifted"
        ) from None
    session.close()
    with _PENDING_CLEANUP_LOCK:
        if _PENDING_SOURCE_SESSION is not session:
            raise GoogleWorkspaceActivationV1Error(
                "authenticated source cleanup authority drifted"
            ) from None
        _PENDING_SOURCE_SESSION = None
    return True


def verify_source_provenance_v1(*, root: Path = _PROJECT_ROOT) -> str:
    """Verify manifest plus exact dependency bytes without importing Google."""

    raw_manifest = _stable_regular_bytes(MANIFEST_RELATIVE_PATH, root=root)
    try:
        manifest = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace source manifest is invalid"
        ) from None
    if type(manifest) is not dict or manifest.get("schema") != MANIFEST_SCHEMA:
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace source manifest is invalid"
        )
    aggregate = manifest.get("aggregate")
    dependencies = manifest.get("dependencies")
    if (
        type(aggregate) is not dict
        or aggregate.get("algorithm") != "sha256"
        or aggregate.get("digest") != EXPECTED_AGGREGATE
        or type(dependencies) is not list
        or len(dependencies) != len(_EXPECTED_DEPENDENCIES)
    ):
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace source manifest is invalid"
        )
    records: dict[str, tuple[int, str]] = {}
    folded: set[str] = set()
    for record in dependencies:
        if type(record) is not dict:
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace source manifest is invalid"
            )
        path = record.get("path")
        size = record.get("size_bytes")
        digest = record.get("sha256")
        if (
            type(path) is not str
            or path != Path(path).as_posix()
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or path.casefold() in folded
            or type(size) is not int
            or isinstance(size, bool)
            or type(digest) is not str
        ):
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace source manifest is invalid"
            )
        folded.add(path.casefold())
        records[path] = (size, digest)
    if records != _EXPECTED_DEPENDENCIES:
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace source manifest drifted"
        )
    canonical: list[str] = []
    for relative, (expected_size, expected_digest) in sorted(records.items()):
        data = _stable_regular_bytes(Path(relative), root=root)
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != expected_size or digest != expected_digest:
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace source dependency drifted"
            )
        canonical.append(f"{relative}|{expected_size}|{expected_digest}\n")
    actual = hashlib.sha256("".join(canonical).encode("utf-8")).hexdigest()
    if actual != EXPECTED_AGGREGATE:
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace source aggregate drifted"
        )
    return actual


def preflight_source_environment_v1(
    environ: Mapping[str, str] | None = None,
) -> GoogleWorkspaceSourcePreflightV1:
    with _PENDING_CLEANUP_LOCK:
        if (
            _PENDING_SOURCE_SESSION is not None
            or _PENDING_ACTIVATION_CONTROLLER is not None
        ):
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace cleanup authority is pending"
            ) from None
    return GoogleWorkspaceSourcePreflightV1(environ)


def _configuration_from_raw(preflight: GoogleWorkspaceSourcePreflightV1) -> object:
    if type(preflight.configuration) is not GoogleWorkspaceRawConfigurationV1:
        raise GoogleWorkspaceActivationV1Error(
            "authenticated Google Workspace configuration is unavailable"
        )
    connector = sys.modules["core.google_workspace_connector_v1"]
    host = sys.modules["core.google_workspace_host_v1"]
    binding = connector.GoogleWorkspaceBindingV1(
        preflight.configuration.owner_id,
        preflight.configuration.workspace_id,
        preflight.configuration.account_id,
    )
    return host.GoogleWorkspaceHostConfigurationV1(
        binding,
        preflight.configuration.client_id,
        preflight.configuration.callback_port,
    )


def preflight_host_v1(
    module: ModuleType,
    preflight: GoogleWorkspaceSourcePreflightV1,
) -> GoogleWorkspaceHostContractV1:
    preflight.assert_healthy()
    if (
        type(preflight) is not GoogleWorkspaceSourcePreflightV1
        or type(preflight.v24) is not ModuleType
    ):
        raise GoogleWorkspaceActivationV1Error(
            "exact Google Workspace source preflight is required"
        )
    try:
        base = preflight.v24.preflight_host(module, preflight.base_environment)
    except Exception:
        raise GoogleWorkspaceActivationV1Error(
            "exact V24 host preflight failed"
        ) from None
    host = getattr(getattr(base, "base", None), "onyx_live", None)
    declarations = getattr(module, "TOOL_DECLARATIONS", None)
    response_type = getattr(getattr(module, "types", None), "FunctionResponse", None)
    if (
        not isinstance(host, type)
        or not isinstance(declarations, list)
        or not callable(getattr(host, "_execute_tool", None))
        or not callable(getattr(module, "authorize_model_tool", None))
        or not callable(response_type)
        or any(
            isinstance(item, dict) and item.get("name") == TOOL_NAME
            for item in declarations
        )
        or hasattr(host, HOST_MARKER)
        or hasattr(module, MODULE_MARKER)
    ):
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace live host contract is unavailable"
        )
    return GoogleWorkspaceHostContractV1(module, host, base.project, base)


class _ProtectedDispatchV1:
    __slots__ = ("_dispatch",)

    def __init__(self, dispatch: object) -> None:
        self._dispatch = dispatch

    def __get__(self, instance: object | None, owner: type | None = None) -> object:
        if instance is None:
            return self._dispatch
        return self._dispatch.__get__(instance, owner)  # type: ignore[union-attr]

    def __set__(self, instance: object, value: object) -> None:
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace dispatcher cannot be shadowed"
        )

    def __delete__(self, instance: object) -> None:
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace dispatcher cannot be deleted"
        )


class OnyxLiveActivationGoogleWorkspaceV1:
    SEAM_COUNT: Final = 6

    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        preflight: GoogleWorkspaceSourcePreflightV1 | None = None
        initialization_failed = False
        try:
            preflight = preflight_source_environment_v1(environ)
            runtime_module = preflight.load("main")
            contract = preflight_host_v1(runtime_module, preflight)
            if (
                type(preflight.runtime_modules) is not tuple
                or len(preflight.runtime_modules) != 8
                or type(preflight.v24) is not ModuleType
            ):
                raise GoogleWorkspaceActivationV1Error(
                    "authenticated Google runtime closure is required"
                )
            base = preflight.v24.OnyxLiveActivationV24(
                preflight.v24.ActivationFlagsV24.from_canonical_environ(
                    preflight.base_environment
                ),
                contract.base,
            )
            configuration = _configuration_from_raw(preflight)
            host_module = preflight.runtime_modules[5]
            factory = host_module.create_google_workspace_host_service_v1
            if not callable(factory):
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace production factory is unavailable"
                )
        except BaseException:
            initialization_failed = True
        if initialization_failed or preflight is None:
            if preflight is not None:
                try:
                    preflight.close()
                except BaseException:
                    _retain_pending_source_session(preflight)
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace activation construction failed"
            ) from None
        (
            self._paths_module,
            _tool_audit,
            self._permission,
            self._native_vault,
            self._connector_module,
            host_module,
            self._live_module,
            self._audit_module,
        ) = preflight.runtime_modules
        self._host_module = host_module
        self.preflight = preflight
        self.contract = contract
        self._runtime_module = runtime_module
        self._base = base
        self._configuration = configuration
        self._factory = factory
        self._host_service_type = host_module.GoogleWorkspaceHostServiceV1
        self._service: object | None = None
        self._adapter: object | None = None
        self._declaration: dict[str, object] | None = None
        self._policy_lease: object | None = None
        self._audit_store: object | None = None
        self._installed = False
        self._bindings: list[_BindingV1] = []
        self._lock = threading.RLock()
        self._state = "new"
        self._accepting_dispatch = False
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._futures: set[concurrent.futures.Future[object]] = set()
        self._tasks: set[asyncio.Task[object]] = set()
        self._pending_instances: list[object] = []
        self._base_started = False
        self._source_session_closed = False
        self._generation = 0

    def run_runtime(self) -> None:
        self._attest_source_session()
        with self._lock:
            if self._state != "installed" or not self._installed:
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace activation is not installed"
                )
        entry = getattr(self._runtime_module, "main", None)
        if (
            not isinstance(entry, FunctionType)
            or entry.__globals__ is not self._runtime_module.__dict__
        ):
            raise GoogleWorkspaceActivationV1Error(
                "authenticated Onyx runtime entry is unavailable"
            )
        entry()

    def _attest_source_session(self) -> None:
        try:
            self.preflight.assert_healthy()
        except BaseException:
            raise GoogleWorkspaceActivationV1Error(
                "authenticated source session is unhealthy"
            ) from None

    def _install_policy(self) -> None:
        self._policy_lease = self._permission.register_model_tool_policy_lease(
            tool=TOOL_NAME,
            policy="action_policy",
            actions=frozenset(
                {"status", "connect", "disconnect", "list_gmail_messages", "list_calendar_events"}
            ),
            autonomous_actions=frozenset(
                {"status", "list_gmail_messages", "list_calendar_events"}
            ),
        )

    def _remove_policy(self) -> None:
        if self._policy_lease is None:
            return
        self._permission.release_model_tool_policy_lease(self._policy_lease)
        self._policy_lease = None

    def _attest_instance(self, instance: object) -> None:
        phase6 = sys.modules.get("core.phase6_live_wiring_v1")
        session = getattr(instance, "_phase6_live_wiring_v1_session", None)
        session_type = getattr(phase6, "LiveWiringSessionV1", None)
        identity_type = getattr(phase6, "LiveWiringIdentityV1", None)
        host_identity = getattr(session, "identity", None)
        binding = self._configuration.binding
        if (
            type(session) is not session_type
            or type(host_identity) is not identity_type
            or host_identity.workspace_id != binding.workspace_id
            or host_identity.profile_id != binding.owner_id
            or not host_identity.account_id
            or not host_identity.principal_id
        ):
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace owner binding attestation failed"
            )

    def _stable_audit_key(self, binding_digest: str) -> bytes:
        reference = self._native_vault.SecretReference(
            "Onyx.GoogleWorkspace.LiveAudit.v1",
            "audit-" + binding_digest[:48],
            "Onyx Google Workspace durable audit authentication",
        )
        vault = self._native_vault.NativeSecretVault(reference)
        key = vault.get_bytes()
        if key is None:
            candidate = secrets.token_bytes(32)
            vault.set_bytes(candidate)
            key = vault.get_bytes()
            if key != candidate:
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace audit key provisioning failed"
                )
        if type(key) is not bytes or len(key) != 32:
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace audit key is unavailable"
            )
        return key

    def install(self, *, fail_after: int | None = None) -> None:
        self._attest_source_session()
        with self._lock:
            if self._state != "new":
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace activation state is invalid"
                )
            self._state = "installing"
        if fail_after is not None and not 1 <= fail_after <= self.SEAM_COUNT:
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace activation failpoint is invalid"
            )
        module = self.contract.module
        failed = False
        try:
            environment = dict(os.environ)
            os.environ.clear()
            os.environ.update(self.preflight.base_environment)
            try:
                self._base_started = True
                self._base.install()
                setattr(module, V24_MARKER, self._base)
                self.preflight.accept_v24_runtime_mutations()
            finally:
                os.environ.clear()
                os.environ.update(environment)
            if fail_after == 1:
                raise GoogleWorkspaceActivationV1Error(
                    "injected Google Workspace predecessor failure"
                )
            self._attest_source_session()
            self._construct_service_boundary()
            if fail_after == 2:
                raise GoogleWorkspaceActivationV1Error(
                    "injected Google Workspace service-boundary failure"
                )
            self._attest_source_session()
            declarations = module.TOOL_DECLARATIONS
            declaration = self._live_module.tool_declaration_google_workspace_v1()
            with _DECLARATION_LOCK:
                if any(
                    isinstance(item, dict) and item.get("name") == TOOL_NAME
                    for item in declarations
                ):
                    raise GoogleWorkspaceActivationV1Error(
                        "Google Workspace declaration already exists"
                    )
                declarations.append(declaration)
            self._declaration = declaration
            if fail_after == 3:
                raise GoogleWorkspaceActivationV1Error(
                    "injected Google Workspace declaration failure"
                )
            self._attest_source_session()
            self._install_policy()
            if fail_after == 4:
                raise GoogleWorkspaceActivationV1Error(
                    "injected Google Workspace policy failure"
                )
            self._attest_source_session()
            current_module_marker = getattr(module, MODULE_MARKER, None)
            if current_module_marker not in {None, self}:
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace recovery marker is already owned"
                )
            setattr(self.contract.onyx_live, HOST_MARKER, self)
            setattr(module, MODULE_MARKER, self)
            if fail_after == 5:
                raise GoogleWorkspaceActivationV1Error(
                    "injected Google Workspace publication failure"
                )
            self._attest_source_session()
            with self._lock:
                self._installed = True
                self._accepting_dispatch = True
                self._state = "installed"
                self._generation += 1
            if fail_after == 6:
                raise GoogleWorkspaceActivationV1Error(
                    "injected Google Workspace completion failure"
                )
        except BaseException:
            failed = True
        if failed:
            try:
                self._rollback_owned_and_base(install_failure=True)
            except BaseException:
                pass
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace activation installation failed"
            ) from None

    def _construct_service_boundary(self) -> None:
        self._attest_source_session()
        with self._lock:
            owned_resources = (
                self._service,
                self._adapter,
                self._audit_store,
                self._executor,
            )
            if any(resource is not None for resource in owned_resources):
                if all(resource is not None for resource in owned_resources):
                    return
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace service cleanup is pending"
                )
            binding = self._configuration.binding
            gate = self._connector_module.GoogleWorkspaceFeatureGateV1(True)
            service: object | None = None
            executor: concurrent.futures.ThreadPoolExecutor | None = None
            audit_store: object | None = None
            adapter: object | None = None
            construction_failed = False
            try:
                service = self._factory(
                    gate=gate, configuration=self._configuration
                )
                if type(service) is not self._host_service_type:
                    raise GoogleWorkspaceActivationV1Error(
                        "Google Workspace host construction failed"
                    )
                connector = getattr(service, "_connector", None)
                if (
                    type(connector)
                    is not self._connector_module.GoogleWorkspaceConnectorV1
                    or getattr(connector, "_binding", None) != binding
                    or type(getattr(connector, "_binding_digest", None)) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", connector._binding_digest)
                    is None
                ):
                    raise GoogleWorkspaceActivationV1Error(
                        "Google Workspace host binding attestation failed"
                    )
                status = service.status()
                if (
                    type(status)
                    is not self._host_module.GoogleWorkspaceHostStatusV1
                    or status.binding_digest != connector._binding_digest
                ):
                    raise GoogleWorkspaceActivationV1Error(
                        "Google Workspace host status attestation failed"
                    )
                audit_key = self._stable_audit_key(connector._binding_digest)
                audit_identity = self._live_module.pseudonymize_live_identity_v1(
                    owner_id=binding.owner_id,
                    workspace_id=binding.workspace_id,
                    account_id=binding.account_id,
                    key=audit_key,
                )
                audit_store = self._audit_module.GoogleWorkspaceAuditStoreV1(
                    path=(
                        self._paths_module.runtime_dir()
                        / "google-workspace"
                        / "live-audit-v1.sqlite3"
                    ),
                    authentication_key=audit_key,
                )
                adapter = self._live_module.GoogleWorkspaceLiveAdapterV1(
                    service=service,
                    audit_identity=audit_identity,
                    expected_binding_digest=connector._binding_digest,
                    central_authorizer=(
                        self._permission.authorize_model_tool_decision_only
                    ),
                    reservation_port=audit_store.reserve,
                    denied_audit_port=audit_store.record_denied,
                    audit_port=audit_store.finalize,
                    audit_verify_port=audit_store.verify,
                )
                executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="onyx-google-workspace-v1",
                )
            except BaseException:
                construction_failed = True
            if construction_failed:
                if executor is not None:
                    executor_cleanup_failed = False
                    try:
                        executor.shutdown(wait=True, cancel_futures=False)
                    except BaseException:
                        executor_cleanup_failed = True
                    if executor_cleanup_failed:
                        self._executor = executor
                if service is not None:
                    service_cleanup_failed = False
                    close = getattr(service, "close", None)
                    if callable(close):
                        try:
                            close()
                        except BaseException:
                            service_cleanup_failed = True
                    if service_cleanup_failed:
                        self._service = service
                        self._adapter = adapter
                if audit_store is not None:
                    audit_cleanup_failed = False
                    try:
                        audit_store.close()
                    except BaseException:
                        audit_cleanup_failed = True
                    if audit_cleanup_failed:
                        self._audit_store = audit_store
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace service construction failed safely"
                ) from None
            self._adapter = adapter
            self._executor = executor
            self._service = service
            self._audit_store = audit_store

    def _ensure_service(self, instance: object) -> None:
        self._attest_source_session()
        with self._lock:
            self._attest_instance(instance)
            if not all(
                resource is not None
                for resource in (
                    self._service,
                    self._adapter,
                    self._audit_store,
                    self._executor,
                )
            ):
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace ready service boundary is unavailable"
                )

    async def _dispatch(
        self, instance: object, original: object, function_call: object
    ) -> object:
        name = getattr(function_call, "name", "")
        try:
            self._attest_source_session()
        except GoogleWorkspaceActivationV1Error:
            if name != TOOL_NAME:
                return await original(function_call)  # type: ignore[operator]
            response_type = self.contract.module.types.FunctionResponse
            return response_type(
                id=getattr(function_call, "id", None),
                name=TOOL_NAME,
                response={
                    "schema": "OnyxGoogleWorkspaceCommand.v1",
                    "status": "denied",
                    "result": "Google Workspace source authority is unavailable.",
                    "external_dispatch": False,
                },
            )
        if name != TOOL_NAME:
            return await original(function_call)  # type: ignore[operator]
        response_type = self.contract.module.types.FunctionResponse
        arguments = getattr(function_call, "args", None)
        trace_id = os.urandom(16).hex()
        invocation_id = str(getattr(function_call, "id", "") or trace_id)
        task = asyncio.current_task()
        tracked = getattr(instance, "_external_action_tasks", None)
        if tracked is None:
            tracked = set()
            setattr(instance, "_external_action_tasks", tracked)
        if task is not None:
            tracked.add(task)
            with self._lock:
                self._tasks.add(task)
        try:
            if callable(getattr(instance, "_runtime_input_is_quiesced", None)) and (
                instance._runtime_input_is_quiesced()
            ):
                return response_type(
                    id=getattr(function_call, "id", None),
                    name=TOOL_NAME,
                    response={
                        "schema": "OnyxGoogleWorkspaceCommand.v1",
                        "status": "denied",
                        "result": "Google Workspace is unavailable during shutdown.",
                        "external_dispatch": False,
                    },
                )
            with self._lock:
                if (
                    self._state != "installed"
                    or not self._accepting_dispatch
                    or self._adapter is None
                    or self._executor is None
                ):
                    return response_type(
                        id=getattr(function_call, "id", None),
                        name=TOOL_NAME,
                        response={
                            "schema": "OnyxGoogleWorkspaceCommand.v1",
                            "status": "denied",
                            "result": "Google Workspace is not accepting work.",
                            "external_dispatch": False,
                        },
                    )
                future = self._executor.submit(
                    self._adapter.execute,
                    arguments,
                    trace_id=trace_id,
                    idempotency_key=invocation_id,
                )
                self._futures.add(future)

                def completed(done: concurrent.futures.Future[object]) -> None:
                    with self._lock:
                        self._futures.discard(done)

                future.add_done_callback(completed)
            try:
                result = await asyncio.wait_for(
                    asyncio.wrap_future(future),
                    timeout=_DISPATCH_TIMEOUT_SECONDS,
                )
            except self._live_module.GoogleWorkspaceLiveV1UnknownOutcome:
                result = {
                    "schema": "OnyxGoogleWorkspaceCommand.v1",
                    "status": "attempted_unknown",
                    "result": "Google Workspace outcome requires reconciliation; no retry was issued.",
                    "external_dispatch": True,
                    "idempotency_digest": self._live_module.idempotency_digest_v1(
                        invocation_id
                    ),
                }
            except (
                self._live_module.GoogleWorkspaceLiveV1ContractError,
                self._live_module.GoogleWorkspaceLiveV1Denied,
            ):
                result = {
                    "schema": "OnyxGoogleWorkspaceCommand.v1",
                    "status": "denied",
                    "result": "Google Workspace request was denied.",
                    "external_dispatch": False,
                }
            except Exception:
                result = {
                    "schema": "OnyxGoogleWorkspaceCommand.v1",
                    "status": "attempted_unknown",
                    "result": "Google Workspace worker outcome requires reconciliation; no retry was issued.",
                    "external_dispatch": True,
                    "idempotency_digest": self._live_module.idempotency_digest_v1(
                        invocation_id
                    ),
                }
            ui = getattr(instance, "ui", None)
            if ui is not None and not getattr(ui, "muted", False):
                ui.set_state("LISTENING")
            return response_type(
                id=getattr(function_call, "id", None),
                name=TOOL_NAME,
                response=result,
            )
        finally:
            if task is not None:
                tracked.discard(task)
                with self._lock:
                    self._tasks.discard(task)

    def _bind_instance(self, instance: object) -> None:
        self._attest_source_session()
        if any(binding.instance is instance for binding in self._bindings):
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace instance is already bound"
            )
        original = getattr(instance, "_execute_tool", None)
        if not callable(original):
            raise GoogleWorkspaceActivationV1Error(
                "V24 dispatcher is unavailable"
            )
        previous_class = type(instance)
        previous_setattr = previous_class.__setattr__
        activation = self

        async def dispatch(owner: object, function_call: object) -> object:
            return await activation._dispatch(owner, original, function_call)

        protected = _ProtectedDispatchV1(dispatch)

        def protected_setattr(owner: object, name: str, value: object) -> None:
            if name == "_execute_tool":
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace dispatcher cannot be shadowed"
                )
            previous_setattr(owner, name, value)

        guarded = type(
            f"{previous_class.__name__}GoogleWorkspaceV1_{id(instance):x}",
            (previous_class,),
            {
                "__slots__": (),
                "__module__": previous_class.__module__,
                "_execute_tool": protected,
                "__setattr__": protected_setattr,
            },
        )
        binding = _BindingV1(
            instance, previous_class, guarded, protected, protected_setattr
        )
        try:
            instance.__class__ = guarded
            if type(instance) is not guarded:
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace dispatcher binding drifted"
                )
            self._bindings.append(binding)
        except BaseException:
            if binding in self._bindings:
                self._bindings.remove(binding)
            if type(instance) is guarded:
                instance.__class__ = previous_class
            raise

    def instantiate_live(self, ui: object) -> object:
        self._attest_source_session()
        with self._lock:
            if (
                self._state != "installed"
                or not self._installed
                or self._pending_instances
            ):
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace activation is not installed"
                )
            generation = self._generation
        instance = self._base.instantiate_live(ui)
        failed = False
        try:
            self._attest_source_session()
            with self._lock:
                if (
                    self._state != "installed"
                    or self._generation != generation
                    or not self._accepting_dispatch
                ):
                    raise GoogleWorkspaceActivationV1Error(
                        "Google Workspace activation changed during construction"
                    )
                self._ensure_service(instance)
                self._bind_instance(instance)
                self._attest_source_session()
        except BaseException:
            failed = True
        if failed:
            close = getattr(instance, "close", None)
            close_failed = False
            if callable(close):
                try:
                    close()
                except BaseException:
                    close_failed = True
            if close_failed:
                with self._lock:
                    self._pending_instances.append(instance)
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace instance binding failed"
            ) from None
        return instance

    def _rollback_owned_and_base(self, *, install_failure: bool = False) -> None:
        try:
            self._attest_source_session()
        except GoogleWorkspaceActivationV1Error:
            pass
        with self._lock:
            if self._state == "rolled_back":
                return
            self._state = "rollback_pending"
            self._accepting_dispatch = False
            self._generation += 1
            pending = tuple(self._futures)
        if pending:
            _done, not_done = concurrent.futures.wait(
                pending, timeout=_ROLLBACK_DRAIN_SECONDS
            )
            if not_done:
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace rollback is waiting for active work"
                ) from None
        with self._lock:
            active_tasks = tuple(task for task in self._tasks if not task.done())
        if active_tasks:
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace rollback is waiting for active dispatch"
            ) from None
        instance_cleanup_failed = False
        for instance in tuple(self._pending_instances):
            close = getattr(instance, "close", None)
            try:
                if callable(close):
                    close()
            except BaseException:
                instance_cleanup_failed = True
            else:
                self._pending_instances.remove(instance)
        if instance_cleanup_failed:
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace instance rollback is pending"
            ) from None
        failed = False
        for binding in reversed(self._bindings):
            try:
                if (
                    type(binding.instance) is not binding.guarded_class
                    or binding.guarded_class.__dict__.get("_execute_tool")
                    is not binding.owned_dispatch
                    or binding.guarded_class.__dict__.get("__setattr__")
                    is not binding.owned_setattr
                ):
                    raise GoogleWorkspaceActivationV1Error(
                        "Google Workspace binding rollback drifted"
                    )
                binding.instance.__class__ = binding.previous_class
            except BaseException:
                failed = True
            else:
                self._bindings.remove(binding)
        if failed:
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace binding rollback is pending"
            ) from None
        if self._policy_lease is not None:
            policy_cleanup_failed = False
            try:
                self._remove_policy()
            except BaseException:
                policy_cleanup_failed = True
            if policy_cleanup_failed:
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace policy rollback is pending"
                ) from None
        declarations = self.contract.module.TOOL_DECLARATIONS
        if self._declaration is not None:
            with _DECLARATION_LOCK:
                owned = next(
                    (index for index, item in enumerate(declarations) if item is self._declaration),
                    None,
                )
                if owned is None:
                    raise GoogleWorkspaceActivationV1Error(
                        "Google Workspace declaration rollback is pending"
                    ) from None
                declarations.pop(owned)
                self._declaration = None
        if self._service is not None:
            service_cleanup_failed = False
            try:
                self._service.close()
            except BaseException:
                service_cleanup_failed = True
            if service_cleanup_failed:
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace service rollback is pending"
                ) from None
            else:
                self._service = None
                self._adapter = None
        if self._audit_store is not None:
            audit_cleanup_failed = False
            try:
                self._audit_store.close()
            except BaseException:
                audit_cleanup_failed = True
            if audit_cleanup_failed:
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace audit rollback is pending"
                ) from None
            else:
                self._audit_store = None
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None
        for owner, marker_name in (
            (self.contract.onyx_live, HOST_MARKER),
            (self.contract.module, MODULE_MARKER),
        ):
            current = getattr(owner, marker_name, None)
            if current is self:
                delattr(owner, marker_name)
            elif current is not None:
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace marker rollback is pending"
                ) from None
        marker = getattr(self.contract.module, V24_MARKER, None)
        if self._base_started and marker is self._base:
            base_cleanup_failed = False
            try:
                self._base.rollback_all()
            except BaseException:
                base_cleanup_failed = True
            if base_cleanup_failed:
                raise GoogleWorkspaceActivationV1Error(
                    "V24 rollback is pending"
                ) from None
            self._base_started = False
        elif self._base_started:
            base_cleanup_failed = False
            try:
                self._base.rollback_all()
            except BaseException:
                base_cleanup_failed = True
            if base_cleanup_failed:
                if install_failure:
                    raise GoogleWorkspaceActivationV1Error(
                        "V24 partial installation rollback is pending"
                    ) from None
                raise GoogleWorkspaceActivationV1Error(
                    "V24 rollback marker drifted"
                ) from None
            self._base_started = False
        elif marker is self._base:
            raise GoogleWorkspaceActivationV1Error(
                "V24 rollback marker remains after completed rollback"
            ) from None
        close_source_session = getattr(self.preflight, "close", None)
        if not self._source_session_closed and callable(close_source_session):
            source_cleanup_failed = False
            try:
                close_source_session()
            except BaseException:
                source_cleanup_failed = True
            if source_cleanup_failed:
                raise GoogleWorkspaceActivationV1Error(
                    "authenticated source session rollback is pending"
                ) from None
            self._source_session_closed = True
        with self._lock:
            self._installed = False
            self._state = "rolled_back"

    def rollback_all(self) -> None:
        with self._lock:
            if self._state not in {"installed", "rollback_pending"}:
                raise GoogleWorkspaceActivationV1Error(
                    "Google Workspace activation cannot roll back"
                )
        rollback_error = ""
        try:
            self._rollback_owned_and_base()
        except GoogleWorkspaceActivationV1Error as error:
            rollback_error = str(error)
        except BaseException:
            rollback_error = "Google Workspace rollback failed safely"
        if rollback_error:
            raise GoogleWorkspaceActivationV1Error(rollback_error) from None
        global _PENDING_ACTIVATION_CONTROLLER
        with _PENDING_CLEANUP_LOCK:
            if _PENDING_ACTIVATION_CONTROLLER is self:
                _PENDING_ACTIVATION_CONTROLLER = None


def retry_pending_activation_cleanup_v1() -> bool:
    global _PENDING_ACTIVATION_CONTROLLER
    with _PENDING_CLEANUP_LOCK:
        controller = _PENDING_ACTIVATION_CONTROLLER
    if controller is None:
        return retry_pending_source_cleanup_v1()
    if type(controller) is not OnyxLiveActivationGoogleWorkspaceV1:
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace cleanup controller drifted"
        ) from None
    controller.rollback_all()
    with _PENDING_CLEANUP_LOCK:
        if _PENDING_ACTIVATION_CONTROLLER is controller:
            _PENDING_ACTIVATION_CONTROLLER = None
        elif _PENDING_ACTIVATION_CONTROLLER is not None:
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace cleanup controller drifted"
            ) from None
    return retry_pending_source_cleanup_v1()


def activate_main(
    environ: Mapping[str, str] | None = None,
) -> OnyxLiveActivationGoogleWorkspaceV1:
    global _PENDING_ACTIVATION_CONTROLLER
    with _PENDING_CLEANUP_LOCK:
        if (
            _PENDING_ACTIVATION_CONTROLLER is not None
            or _PENDING_SOURCE_SESSION is not None
        ):
            raise GoogleWorkspaceActivationV1Error(
                "Google Workspace cleanup authority is pending"
            ) from None
    try:
        controller = OnyxLiveActivationGoogleWorkspaceV1(environ)
    except BaseException:
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace activation construction failed"
        ) from None
    try:
        controller.install()
    except BaseException:
        rolled_back = controller._state == "rolled_back"
        if controller._state == "rollback_pending":
            for _attempt in range(3):
                try:
                    controller.rollback_all()
                except GoogleWorkspaceActivationV1Error:
                    continue
                rolled_back = True
                break
        if not rolled_back:
            with _PENDING_CLEANUP_LOCK:
                if _PENDING_ACTIVATION_CONTROLLER not in {None, controller}:
                    raise GoogleWorkspaceActivationV1Error(
                        "Google Workspace cleanup controller is already retained"
                    ) from None
                _PENDING_ACTIVATION_CONTROLLER = controller
        raise GoogleWorkspaceActivationV1Error(
            "Google Workspace activation failed safely"
        ) from None
    return controller


__all__ = [
    "CONNECTOR_FLAG",
    "ENABLED_VALUE",
    "EXPECTED_AGGREGATE",
    "GoogleWorkspaceActivationV1Error",
    "GoogleWorkspaceHostContractV1",
    "GoogleWorkspaceRawConfigurationV1",
    "GoogleWorkspaceSourcePreflightV1",
    "HOST_MARKER",
    "LIVE_FLAG",
    "MANIFEST_RELATIVE_PATH",
    "MODULE_MARKER",
    "OnyxLiveActivationGoogleWorkspaceV1",
    "TOOL_NAME",
    "activate_main",
    "google_workspace_selection_v1",
    "preflight_host_v1",
    "preflight_source_environment_v1",
    "retry_pending_activation_cleanup_v1",
    "retry_pending_source_cleanup_v1",
    "restore_v24_environment",
    "verify_source_provenance_v1",
]
