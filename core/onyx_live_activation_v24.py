"""Final shutdown-dispatch guard over the exact authenticated V23 runtime."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import CodeType, FunctionType, ModuleType
from typing import Final

LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V24"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V24"
FEATURE_FLAG: Final = "ONYX_FINAL_SHUTDOWN_DISPATCH_GUARD_V1"
HOST_MARKER: Final = "_onyx_live_activation_v24"
V23_RELATIVE_PATH: Final = Path("core") / "onyx_live_activation_v23.py"
V23_SHA256: Final = "207aec29d0e87a874b3641162f53250382fe18f2dfc2998b68d3702b82d85607"
_PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
_PRIVATE_V23_NAME: Final = (
    f"core._onyx_authenticated_v23_{V23_SHA256[:16]}"
)
_DIRECT_DEPENDENCIES: Final = {
    "core.onyx_live_activation_v22": (
        Path("core") / "onyx_live_activation_v22.py",
        "88f9c3373a3ef998598841b30b1bef471e0c77bdf819e0ec05496a55b0591d4c",
    ),
    "core.operational_event_controller_v1": (
        Path("core") / "operational_event_controller_v1.py",
        "b73a81d0d69b1c3f6d286d0df0e9c2c67f7375e4f6cbf5ce2c99fbdb968e41e6",
    ),
    "core.phase6_live_wiring_v1": (
        Path("core") / "phase6_live_wiring_v1.py",
        "a658f430c10bb992724ad7bbd2ddae94b3c83f8893608fe724b241302b55d55f",
    ),
    "core.portable_host_capability_v1": (
        Path("core") / "portable_host_capability_v1.py",
        "e7eef960e944736e85a9016f6b0ce637b5fc4566cb994c7a8370370c4882c620",
    ),
}
_CRITICAL_VALUES: Final = {
    "core.operational_event_controller_v1": {
        "HOST_CONTROLLER": "_operational_event_controller_v1",
    },
    "core.phase6_live_wiring_v1": {
        "FEATURE_FLAG": "ONYX_PHASE6_LIVE_WIRING_V1",
        "SESSION_ATTRIBUTE": "_phase6_live_wiring_v1_session",
        "SCHEMA_VERSION": 1,
    },
    "core.portable_host_capability_v1": {
        "SUPPORTED_SYSTEMS": frozenset({"Darwin", "Linux"}),
        "ALLOWED_STAGES": frozenset(
            {
                "governance_v16",
                "founder_preflight",
                "founder_controller",
                "document_intake_preflight",
                "dayops_preflight",
            }
        ),
    },
}
_CRITICAL_LAYOUTS: Final = {
    ("core.onyx_live_activation_v22", "ActivationFlagsV22"): (
        "master",
        "owner_context",
        "base",
    ),
    ("core.onyx_live_activation_v22", "HostContractV22"): (
        "module",
        "onyx_live",
        "project",
        "base",
    ),
    ("core.portable_host_capability_v1", "PortableHostCapabilityV1"): (
        "_seal",
        "system",
        "euid",
        "process_id",
    ),
    ("core.portable_host_capability_v1", "PortableHostBindingsV1"): (
        "_seal",
        "capability",
        "runtime_address",
        "runtime_endpoint_factory",
        "trusted_directory_factory",
        "kill_signal_factory",
        "artifact_root_authorizer",
        "governance_descriptor_io",
    ),
}


class ActivationV24Error(RuntimeError):
    pass


def _constant_payload(value: object) -> object:
    if isinstance(value, CodeType):
        return _code_payload(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return [type(value).__name__, value]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, tuple):
        return ["tuple", [_constant_payload(item) for item in value]]
    if isinstance(value, frozenset):
        items = [_constant_payload(item) for item in value]
        return ["frozenset", sorted(items, key=lambda item: json.dumps(item))]
    return [type(value).__name__, repr(value)]


def _code_payload(code: CodeType) -> object:
    """Canonical code data independent of marshal reference-table state."""

    return {
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "stacksize": code.co_stacksize,
        "flags": code.co_flags,
        "code": code.co_code.hex(),
        "consts": [_constant_payload(value) for value in code.co_consts],
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


def _code_fingerprint(code: CodeType) -> str:
    encoded = json.dumps(
        _code_payload(code),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _source_definitions(source: bytes, path: Path) -> dict[str, CodeType]:
    module_code = compile(source, str(path), "exec", dont_inherit=True)
    return {
        value.co_name: value
        for value in module_code.co_consts
        if isinstance(value, CodeType) and not value.co_name.startswith("<")
    }


def _runtime_function(value: object) -> FunctionType | None:
    if isinstance(value, (classmethod, staticmethod)):
        value = value.__func__
    elif isinstance(value, property):
        value = value.fget
    return value if isinstance(value, FunctionType) else None


def _authenticate_dependency(
    name: str,
    relative: Path,
    expected_sha256: str,
) -> ModuleType:
    expected_path = _PROJECT_ROOT / relative
    path = expected_path.resolve()
    try:
        metadata = expected_path.lstat()
        source = expected_path.read_bytes()
        module = importlib.import_module(name)
    except (ImportError, OSError) as exc:
        raise ActivationV24Error(f"authenticated dependency unavailable: {name}") from exc
    if (
        path != expected_path
        or not stat.S_ISREG(metadata.st_mode)
        or hashlib.sha256(source).hexdigest() != expected_sha256
        or type(module) is not ModuleType
        or module.__name__ != name
        or Path(getattr(module, "__file__", "")).resolve() != path
        or sys.modules.get(name) is not module
    ):
        raise ActivationV24Error(f"authenticated dependency drifted: {name}")

    expected = _source_definitions(source, path)
    for symbol, expected_code in expected.items():
        runtime = getattr(module, symbol, None)
        function = _runtime_function(runtime)
        if function is not None:
            if (
                function.__globals__ is not module.__dict__
                or _code_fingerprint(function.__code__)
                != _code_fingerprint(expected_code)
            ):
                raise ActivationV24Error(
                    f"dependency code provenance drifted: {name}.{symbol}"
                )
            continue
        if not isinstance(runtime, type):
            raise ActivationV24Error(
                f"dependency definition unavailable: {name}.{symbol}"
            )
        if runtime.__module__ != name or runtime.__qualname__ != symbol:
            raise ActivationV24Error(
                f"dependency class provenance drifted: {name}.{symbol}"
            )
        expected_methods = {
            value.co_name: value
            for value in expected_code.co_consts
            if isinstance(value, CodeType) and not value.co_name.startswith("<")
        }
        for method_name, expected_method in expected_methods.items():
            method = _runtime_function(runtime.__dict__.get(method_name))
            if (
                method is None
                or method.__globals__ is not module.__dict__
                or _code_fingerprint(method.__code__)
                != _code_fingerprint(expected_method)
            ):
                raise ActivationV24Error(
                    "dependency method provenance drifted: "
                    f"{name}.{symbol}.{method_name}"
                )

    for constant, exact_value in _CRITICAL_VALUES.get(name, {}).items():
        if type(getattr(module, constant, None)) is not type(exact_value) or getattr(
            module, constant, None
        ) != exact_value:
            raise ActivationV24Error(
                f"dependency critical value drifted: {name}.{constant}"
            )
    for (module_name, class_name), fields in _CRITICAL_LAYOUTS.items():
        if module_name != name:
            continue
        runtime = getattr(module, class_name, None)
        runtime_fields = getattr(runtime, "__dataclass_fields__", {})
        if type(runtime) is not type or tuple(runtime_fields) != fields:
            raise ActivationV24Error(
                f"dependency critical layout drifted: {name}.{class_name}"
            )
    return module


def _capture_authenticated_dependencies() -> dict[str, ModuleType]:
    return {
        name: _authenticate_dependency(name, relative, sha256)
        for name, (relative, sha256) in _DIRECT_DEPENDENCIES.items()
    }


def _read_authenticated_v23() -> tuple[Path, bytes]:
    path = (_PROJECT_ROOT / V23_RELATIVE_PATH).resolve()
    expected = _PROJECT_ROOT / V23_RELATIVE_PATH
    try:
        metadata = expected.lstat()
        source = expected.read_bytes()
    except OSError as exc:
        raise ActivationV24Error(
            "exact authenticated V23 predecessor is unavailable"
        ) from exc
    if (
        path != expected
        or not stat.S_ISREG(metadata.st_mode)
        or hashlib.sha256(source).hexdigest() != V23_SHA256
    ):
        raise ActivationV24Error(
            "exact authenticated V23 predecessor is unavailable"
        )
    return path, source


_AUTHENTICATED_DEPENDENCIES: Final = _capture_authenticated_dependencies()


def _load_authenticated_v23() -> ModuleType:
    """Execute only the pinned V23 bytes in an unpublished private namespace."""

    path, source = _read_authenticated_v23()
    for name, authenticated in _AUTHENTICATED_DEPENDENCIES.items():
        relative, sha256 = _DIRECT_DEPENDENCIES[name]
        if _authenticate_dependency(name, relative, sha256) is not authenticated:
            raise ActivationV24Error(
                f"authenticated dependency identity drifted: {name}"
            )
    loader = importlib.machinery.SourceFileLoader(_PRIVATE_V23_NAME, str(path))
    spec = importlib.util.spec_from_loader(
        _PRIVATE_V23_NAME,
        loader,
        origin=str(path),
    )
    if spec is None:
        raise ActivationV24Error("authenticated V23 module spec is unavailable")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "core"
    module.__file__ = str(path)
    module.__dict__["__onyx_authenticated_source_sha256__"] = V23_SHA256
    previous = sys.modules.get(_PRIVATE_V23_NAME)
    had_previous = _PRIVATE_V23_NAME in sys.modules
    sys.modules[_PRIVATE_V23_NAME] = module
    try:
        code = compile(source, str(path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except BaseException:
        raise
    finally:
        if had_previous:
            sys.modules[_PRIVATE_V23_NAME] = previous  # type: ignore[assignment]
        else:
            sys.modules.pop(_PRIVATE_V23_NAME, None)
    if (
        module.__dict__.get("__onyx_authenticated_source_sha256__") != V23_SHA256
        or Path(module.__file__).resolve() != path
    ):
        raise ActivationV24Error("authenticated V23 private module drifted")
    v22_module = _AUTHENTICATED_DEPENDENCIES["core.onyx_live_activation_v22"]
    events_module = _AUTHENTICATED_DEPENDENCIES[
        "core.operational_event_controller_v1"
    ]
    wiring_module = _AUTHENTICATED_DEPENDENCIES["core.phase6_live_wiring_v1"]
    portable_module = _AUTHENTICATED_DEPENDENCIES[
        "core.portable_host_capability_v1"
    ]
    if (
        module.__dict__.get("v22") is not v22_module
        or module.__dict__.get("OperationalEventControllerV1")
        is not events_module.OperationalEventControllerV1
        or module.__dict__.get("OPERATIONAL_EVENT_CONTROLLER")
        != events_module.HOST_CONTROLLER
        or module.__dict__.get("Phase6LiveWiringV1")
        is not wiring_module.Phase6LiveWiringV1
        or module.__dict__.get("PortableHostBindingsV1")
        is not portable_module.PortableHostBindingsV1
    ):
        raise ActivationV24Error("authenticated V23 dependency bindings drifted")
    return module


v23: Final = _load_authenticated_v23()
CONTROL_FLAGS: Final = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    FEATURE_FLAG,
    *v23.CONTROL_FLAGS,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _authenticate_v23(module: ModuleType) -> Path:
    expected, _source = _read_authenticated_v23()
    loaded = Path(v23.__file__).resolve()
    host_file = Path(module.__file__).resolve()
    if (
        host_file.parent != _PROJECT_ROOT
        or loaded != expected
        or v23.__dict__.get("__onyx_authenticated_source_sha256__") != V23_SHA256
    ):
        raise ActivationV24Error("exact authenticated V23 predecessor is unavailable")
    return _PROJECT_ROOT


@dataclass(frozen=True, slots=True)
class ActivationFlagsV24:
    base: v23.ActivationFlagsV23

    def __post_init__(self) -> None:
        if type(self.base) is not v23.ActivationFlagsV23:
            raise ActivationV24Error("exact V23 activation flags are required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV24":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV24Error("rollback is not an active V24 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(FEATURE_FLAG) != "true":
            raise ActivationV24Error("activation environment is not canonical V24")
        try:
            base = v23.ActivationFlagsV23.from_canonical_environ(
                restore_v23_environment(source)
            )
        except v23.ActivationV23Error as exc:
            raise ActivationV24Error("V23 environment is incomplete") from exc
        return cls(base)


def exact_activation_environment(
    workspace_roots: Sequence[str | os.PathLike[str]],
) -> dict[str, str]:
    result = v23.exact_activation_environment(workspace_roots)
    result[LIVE_MASTER_FLAG] = "1"
    result[FEATURE_FLAG] = "true"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v23_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(FEATURE_FLAG, None)
    return result


@dataclass(frozen=True, slots=True)
class HostContractV24:
    module: ModuleType
    project: Path
    base: v23.HostContractV23


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
) -> HostContractV24:
    source = os.environ if environ is None else environ
    flags = ActivationFlagsV24.from_canonical_environ(source)
    project = _authenticate_v23(module)
    try:
        base = v23.preflight_host(module, restore_v23_environment(source))
    except v23.ActivationV23Error as exc:
        raise ActivationV24Error("exact V23 host preflight failed") from exc
    if type(flags.base) is not v23.ActivationFlagsV23 or base.project.resolve() != project:
        raise ActivationV24Error("V23 host project drifted")
    return HostContractV24(module, project, base)


@dataclass(slots=True)
class _BindingV24:
    instance: object
    previous_class: type
    guarded_class: type
    had_instance_dispatch: bool
    previous_instance_dispatch: object | None
    owned_dispatch: object
    owned_setattr: object
    class_restored: bool = False


@dataclass(frozen=True, slots=True)
class _TerminalRollbackV24:
    """Authenticated authority needed to retire the V16-preserving V17 seam."""

    v17_controller: object
    v16_controller: object
    ui_module: ModuleType
    hud_modules: tuple[tuple[str, ModuleType], ...]

    def finish(self) -> None:
        # V17-V19 intentionally preserve their accepted predecessor for a
        # version-local rollback.  V24 ``rollback_all`` is a terminal rollback,
        # so explicitly cross that historical boundary and then retire V16.
        self.v17_controller.rollback_to_v16()
        self.v16_controller.rollback_all()
        key = id(self.ui_module)
        if getattr(self.ui_module, "_ONYX_HUD_V6_INSTALLATION", None) is not None:
            raise ActivationV24Error("V24 terminal HUD V6 rollback drifted")
        for version, module in self.hud_modules:
            if (
                getattr(self.ui_module, f"_ONYX_HUD_V{version}_INSTALLATION", None)
                is not None
                or module._ACTIVE_INSTALLATIONS.get(key) is not None
            ):
                raise ActivationV24Error(
                    f"V24 terminal HUD V{version} rollback drifted"
                )


def _capture_terminal_rollback(base: object) -> _TerminalRollbackV24:
    """Bind the exact authenticated V23-to-V10 controller spine fail closed."""

    modules = [v23]
    for predecessor in ("v22", "v21", "v20", "v19", "v18", "v17", "v16"):
        module = getattr(modules[-1], predecessor, None)
        if type(module) is not ModuleType:
            raise ActivationV24Error("V24 terminal rollback module spine drifted")
        modules.append(module)
    controllers: list[object] = []
    current = base
    for version, module in zip(range(23, 15, -1), modules, strict=True):
        expected = getattr(module, f"OnyxLiveActivationV{version}", None)
        if type(current) is not expected:
            raise ActivationV24Error("V24 terminal rollback controller spine drifted")
        controllers.append(current)
        current = getattr(current, "_base", None)

    v16_controller = controllers[-1]
    lower_modules = [modules[-1]]
    for predecessor in ("v15", "v14", "v13", "v12", "v11", "v10"):
        module = getattr(lower_modules[-1], predecessor, None)
        if type(module) is not ModuleType:
            raise ActivationV24Error("V24 terminal HUD module spine drifted")
        lower_modules.append(module)
    lower_controllers: list[object] = []
    current = getattr(v16_controller, "_base", None)
    for version, module in zip(range(15, 9, -1), lower_modules[1:], strict=True):
        expected = getattr(module, f"OnyxLiveActivationV{version}", None)
        if type(current) is not expected:
            raise ActivationV24Error("V24 terminal HUD controller spine drifted")
        lower_controllers.append(current)
        current = getattr(current, "_base", None)

    v12_controller = lower_controllers[3]
    v11_controller = lower_controllers[4]
    v10_controller = lower_controllers[5]
    ui_module = getattr(getattr(v10_controller, "contract", None), "ui_module", None)
    hud_v8 = getattr(v11_controller, "_hud_v8_module", None)
    hud_v7 = getattr(v10_controller, "_hud_v7_module", None)
    hud_v9 = getattr(lower_modules[4], "hud_v9", None)
    v9_module = getattr(lower_modules[-1], "v9", None)
    hud_v6 = getattr(v9_module, "hud_v6", None)
    if type(ui_module) is not ModuleType or any(
        type(module) is not ModuleType for module in (hud_v6, hud_v7, hud_v8, hud_v9)
    ):
        raise ActivationV24Error("V24 terminal HUD authority is unavailable")
    if getattr(v12_controller, "contract", None).ui_module is not ui_module:
        raise ActivationV24Error("V24 terminal HUD owner drifted")

    hud_modules = (("7", hud_v7), ("8", hud_v8), ("9", hud_v9))
    key = id(ui_module)
    v6_record = getattr(ui_module, "_ONYX_HUD_V6_INSTALLATION", None)
    if type(v6_record) is not dict or v6_record.get("ui_module") not in (None, ui_module):
        raise ActivationV24Error("V24 terminal HUD V6 authority drifted")
    for version, module in hud_modules:
        record = module._ACTIVE_INSTALLATIONS.get(key)
        if (
            record is None
            or record.ui_module is not ui_module
            or getattr(ui_module, f"_ONYX_HUD_V{version}_INSTALLATION", None)
            is not module._INSTALLATION_TOKEN
        ):
            raise ActivationV24Error(
                f"V24 terminal HUD V{version} authority drifted"
            )
    return _TerminalRollbackV24(
        controllers[-2], v16_controller, ui_module, hud_modules
    )


class _ProtectedDispatchV24:
    __slots__ = ("_dispatch",)

    def __init__(self, dispatch: object) -> None:
        if not callable(dispatch):
            raise ActivationV24Error("V24 protected dispatcher is invalid")
        self._dispatch = dispatch

    def __get__(self, instance: object | None, owner: type | None = None) -> object:
        if instance is None:
            return self._dispatch
        return self._dispatch.__get__(instance, owner)  # type: ignore[union-attr]

    def __set__(self, instance: object, value: object) -> None:
        raise ActivationV24Error("V24 protected dispatcher cannot be shadowed")

    def __delete__(self, instance: object) -> None:
        raise ActivationV24Error("V24 protected dispatcher cannot be deleted")


class OnyxLiveActivationV24:
    """Own only a per-instance guard outside every accepted V23 interceptor."""

    def __init__(self, flags: ActivationFlagsV24, contract: HostContractV24) -> None:
        if type(flags) is not ActivationFlagsV24 or type(contract) is not HostContractV24:
            raise ActivationV24Error("exact V24 activation bindings are required")
        self.flags = flags
        self.contract = contract
        self._base = v23.OnyxLiveActivationV23(flags.base, contract.base)
        self._installed = False
        self._rollback_pending = False
        self._bindings: list[_BindingV24] = []
        self._terminal_rollback: _TerminalRollbackV24 | None = None

    def install(self) -> None:
        if self._installed or self._rollback_pending:
            raise ActivationV24Error("V24 is already installed")
        environment = dict(os.environ)
        os.environ.clear()
        os.environ.update(restore_v23_environment(environment))
        try:
            self._base.install()
        finally:
            os.environ.clear()
            os.environ.update(environment)
        self._installed = True

    def _bind_instance(self, instance: object) -> None:
        if any(binding.instance is instance for binding in self._bindings):
            raise ActivationV24Error("V24 instance is already guarded")
        original = getattr(instance, "_execute_tool", None)
        if not callable(original):
            raise ActivationV24Error("V23 tool dispatcher is unavailable")
        had_instance = "_execute_tool" in getattr(instance, "__dict__", {})
        previous = getattr(instance, "__dict__", {}).get("_execute_tool")
        previous_class = type(instance)
        previous_setattr = previous_class.__setattr__

        async def guarded(owner: object, function_call: object) -> object:
            name = str(getattr(function_call, "name", ""))
            quiesced = getattr(owner, "_runtime_input_is_quiesced", None)
            if callable(quiesced) and quiesced():
                denied = getattr(owner, "_final_tool_dispatch_denials_v24", None)
                if type(denied) is not list:
                    denied = []
                    setattr(owner, "_final_tool_dispatch_denials_v24", denied)
                denied.append((name, str(getattr(function_call, "id", ""))))
                if len(denied) > 128:
                    del denied[:-128]
                response_type = getattr(
                    getattr(self.contract.module, "types", None),
                    "FunctionResponse",
                    None,
                )
                if response_type is None:
                    raise ActivationV24Error("FunctionResponse authority is unavailable")
                return response_type(
                    id=getattr(function_call, "id", None),
                    name=name,
                    response={
                        "result": "Action refused: shutdown is already in progress."
                    },
                )

            task = asyncio.current_task()
            depths = getattr(owner, "_final_tool_dispatch_depth_v24", None)
            if type(depths) is not dict:
                depths = {}
                setattr(owner, "_final_tool_dispatch_depth_v24", depths)
            tracked = getattr(owner, "_external_action_tasks", None)
            if tracked is None:
                tracked = set()
                setattr(owner, "_external_action_tasks", tracked)
            if task is not None:
                depth = int(depths.get(task, 0))
                depths[task] = depth + 1
                if depth == 0:
                    tracked.add(task)
            try:
                return await original(function_call)
            finally:
                if task is not None:
                    depth = int(depths.get(task, 1)) - 1
                    if depth <= 0:
                        depths.pop(task, None)
                        tracked.discard(task)
                    else:
                        depths[task] = depth

        protected_dispatch = _ProtectedDispatchV24(guarded)

        def protected_setattr(owner: object, name: str, value: object) -> None:
            if name == "_execute_tool":
                raise ActivationV24Error(
                    "V24 protected dispatcher cannot be shadowed"
                )
            previous_setattr(owner, name, value)

        guarded_class = type(
            f"{previous_class.__name__}V24Guard_{id(instance):x}",
            (previous_class,),
            {
                "__slots__": (),
                "__module__": previous_class.__module__,
                "_execute_tool": protected_dispatch,
                "__setattr__": protected_setattr,
            },
        )
        try:
            if had_instance:
                delattr(instance, "_execute_tool")
            instance.__class__ = guarded_class
            if (
                type(instance) is not guarded_class
                or guarded_class.__dict__.get("_execute_tool")
                is not protected_dispatch
                or guarded_class.__dict__.get("__setattr__") is not protected_setattr
                or "_execute_tool" in getattr(instance, "__dict__", {})
            ):
                raise ActivationV24Error("V24 outer dispatch binding drifted")
        except BaseException as exc:
            try:
                instance.__class__ = previous_class
                if had_instance:
                    setattr(instance, "_execute_tool", previous)
            except BaseException as rollback_exc:
                raise ActivationV24Error(
                    "V24 partial dispatch binding could not be restored"
                ) from rollback_exc
            if isinstance(exc, ActivationV24Error):
                raise
            raise ActivationV24Error("V24 outer dispatch binding failed") from exc
        self._bindings.append(
            _BindingV24(
                instance,
                previous_class,
                guarded_class,
                had_instance,
                previous,
                protected_dispatch,
                protected_setattr,
            )
        )

    def instantiate_live(self, ui: object) -> object:
        if not self._installed or self._rollback_pending:
            raise ActivationV24Error("V24 activation is not installed")
        instance = self._base.instantiate_live(ui)
        self._bind_instance(instance)
        return instance

    def rollback_all(self) -> None:
        if not self._installed:
            raise ActivationV24Error("V24 activation is not installed")
        if getattr(self.contract.module, HOST_MARKER, None) is not self:
            self._rollback_pending = True
            raise ActivationV24Error("V24 rollback marker drifted")

        self._rollback_pending = True
        errors: list[BaseException] = []
        for binding in reversed(self._bindings):
            try:
                if not binding.class_restored:
                    if (
                        type(binding.instance) is not binding.guarded_class
                        or binding.guarded_class.__dict__.get("_execute_tool")
                        is not binding.owned_dispatch
                        or binding.guarded_class.__dict__.get("__setattr__")
                        is not binding.owned_setattr
                        or "_execute_tool"
                        in getattr(binding.instance, "__dict__", {})
                    ):
                        raise ActivationV24Error("V24 dispatch rollback drifted")
                    binding.instance.__class__ = binding.previous_class
                    if type(binding.instance) is not binding.previous_class:
                        raise ActivationV24Error("V24 class restoration drifted")
                    binding.class_restored = True
                elif type(binding.instance) is not binding.previous_class:
                    raise ActivationV24Error("V24 retry restoration drifted")
                if binding.had_instance_dispatch:
                    setattr(
                        binding.instance,
                        "_execute_tool",
                        binding.previous_instance_dispatch,
                    )
                    if (
                        getattr(binding.instance, "__dict__", {}).get(
                            "_execute_tool"
                        )
                        is not binding.previous_instance_dispatch
                    ):
                        raise ActivationV24Error(
                            "V24 instance dispatcher restoration drifted"
                        )
                elif "_execute_tool" in getattr(binding.instance, "__dict__", {}):
                    raise ActivationV24Error(
                        "V24 absent instance dispatcher restoration drifted"
                    )
            except BaseException as exc:
                errors.append(exc)
            else:
                self._bindings.remove(binding)
        if errors:
            raise ActivationV24Error("V24 rollback restoration failed") from errors[0]
        terminal = getattr(self, "_terminal_rollback", None)
        if terminal is None and type(self._base) is v23.OnyxLiveActivationV23:
            terminal = _capture_terminal_rollback(self._base)
            self._terminal_rollback = terminal
        try:
            self._base.rollback_all()
        except BaseException as exc:
            raise ActivationV24Error("V23 rollback failed") from exc
        if terminal is not None:
            try:
                terminal.finish()
            except BaseException as exc:
                raise ActivationV24Error("V24 terminal rollback failed") from exc
        self._installed = False
        self.contract.module.__dict__.pop(HOST_MARKER, None)
        if getattr(self.contract.module, HOST_MARKER, None) is not None:
            raise ActivationV24Error("V24 rollback marker removal drifted")
        self._rollback_pending = False
        self._terminal_rollback = None


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
) -> OnyxLiveActivationV24:
    source = os.environ if environ is None else environ
    controller = OnyxLiveActivationV24(
        ActivationFlagsV24.from_canonical_environ(source),
        preflight_host(module, source),
    )
    controller.install()
    setattr(module, HOST_MARKER, controller)
    return controller


__all__ = [
    "ActivationFlagsV24",
    "ActivationV24Error",
    "CONTROL_FLAGS",
    "FEATURE_FLAG",
    "HOST_MARKER",
    "HostContractV24",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV24",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v23_environment",
]
