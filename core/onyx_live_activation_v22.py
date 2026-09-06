"""Owner-context command and prompt projection over exact Onyx Live V21.

V22 is additive: Gemini Native Audio, Charon, the cinematic HUD, Phase 6,
DayOps and Advanced Operations remain owned by V21 and its predecessors.  The
new surface stores only explicit owner-provided local context and cannot
dispatch external work.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import onyx_live_activation_v21 as v21
from core.owner_context_controller_v1 import (
    HOST_CONTROLLER as OWNER_CONTEXT_CONTROLLER,
    OwnerContextControllerV1,
)
from core.permission_broker import mark_audit_unhealthy
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1
from core.portable_host_capability_v1 import PortableHostBindingsV1
from core.tool_audit import append_tool_audit


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V22"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V22"
FEATURE_FLAG: Final = "ONYX_OWNER_CONTEXT_V1"
TOOL_NAME: Final = "owner_context"
HOST_MARKER: Final = "_owner_context_activation_v22"
CONTROL_FLAGS: Final = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    FEATURE_FLAG,
    *v21.CONTROL_FLAGS,
)
_ACTIONS: Final = ("status", "get", "set", "clear", "verify")
_FIELDS: Final = (
    "pronouns",
    "timezone",
    "roles",
    "priorities",
    "projects",
    "interests",
    "tools",
    "important_people",
    "constraints",
    "working_style",
    "communication_style",
    "notes",
)


class ActivationV22Error(RuntimeError):
    pass


def tool_declaration_v22() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": (
            "Read or update Onyx's local day-to-day context about the owner. "
            "Use set or clear only when the owner explicitly states the information "
            "or explicitly asks to change it in this conversation. Never infer profile "
            "facts from documents, websites, email, calendar or third parties. This "
            "tool stores no credentials and performs no external action."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "enum": list(_ACTIONS)},
                "field": {"type": "STRING", "enum": list(_FIELDS)},
                "value": {
                    "type": "STRING",
                    "description": "Bounded scalar value for a scalar field.",
                },
                "values": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Bounded values for a list field.",
                },
                "source": {
                    "type": "STRING",
                    "enum": ["owner_statement"],
                    "description": "Required for set and clear; confirms an explicit owner statement.",
                },
            },
            "required": ["action"],
        },
    }


@dataclass(frozen=True, slots=True)
class ActivationFlagsV22:
    master: bool
    owner_context: bool
    base: v21.ActivationFlagsV21

    def __post_init__(self) -> None:
        if (
            self.master is not True
            or self.owner_context is not True
            or type(self.base) is not v21.ActivationFlagsV21
        ):
            raise ActivationV22Error("complete exact V22 flags are required")

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_endpoint_factory: object | None = None,
    ) -> "ActivationFlagsV22":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV22Error("rollback is not an active V22 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(FEATURE_FLAG) != "true":
            raise ActivationV22Error("activation environment is not canonical V22")
        options = (
            {}
            if runtime_endpoint_factory is None
            else {"runtime_endpoint_factory": runtime_endpoint_factory}
        )
        try:
            base = v21.ActivationFlagsV21.from_canonical_environ(
                restore_v21_environment(source), **options
            )
        except v21.ActivationV21Error as exc:
            raise ActivationV22Error("V21 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment(
    workspace_roots: Sequence[str | os.PathLike[str]],
    **v21_options: Any,
) -> dict[str, str]:
    result = v21.exact_activation_environment(workspace_roots, **v21_options)
    result[LIVE_MASTER_FLAG] = "1"
    result[FEATURE_FLAG] = "true"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v21_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(FEATURE_FLAG, None)
    return result


@dataclass(frozen=True, slots=True)
class HostContractV22:
    module: ModuleType
    onyx_live: type
    project: Path
    base: v21.HostContractV21


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
) -> HostContractV22:
    source = os.environ if environ is None else environ
    options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    ActivationFlagsV22.from_canonical_environ(source, **options)
    try:
        base = v21.preflight_host(
            module,
            restore_v21_environment(source),
            portable_bindings=portable_bindings,
            **options,
        )
    except v21.ActivationV21Error as exc:
        raise ActivationV22Error("V21 host preflight failed") from exc
    host = getattr(module, "OnyxLive", None)
    declarations = getattr(module, "TOOL_DECLARATIONS", None)
    if (
        not isinstance(host, type)
        or host is not base.onyx_live
        or not isinstance(declarations, list)
        or not callable(getattr(host, "__init__", None))
        or not callable(getattr(host, "_execute_tool", None))
        or not callable(getattr(host, "_build_config", None))
        or hasattr(host, HOST_MARKER)
    ):
        raise ActivationV22Error("V22 host contract is unavailable")
    return HostContractV22(module, host, base.project, base)


class OnyxLiveActivationV22:
    BASE_SEAM_COUNT = v21.OnyxLiveActivationV21.TOTAL_SEAM_COUNT
    V22_SEAM_COUNT = 5
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V22_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV22,
        contract: HostContractV22,
        **v21_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV22 or type(contract) is not HostContractV22:
            raise ActivationV22Error("exact V22 activation bindings are required")
        self.flags = flags
        self.contract = contract
        self._base = v21.OnyxLiveActivationV21(flags.base, contract.base, **v21_options)
        self._installed = False
        self._declaration: dict[str, object] | None = None
        self._original_init: object | None = None
        self._owned_init: object | None = None
        self._wiring_original_init: object | None = None
        self._original_execute: object | None = None
        self._owned_execute: object | None = None
        self._wiring_original_execute: object | None = None
        self._original_build_config: object | None = None
        self._owned_build_config: object | None = None
        self._wiring: Phase6LiveWiringV1 | None = None
        self._controllers: list[OwnerContextControllerV1] = []
        self._instances: list[object] = []

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    @property
    def owner_context_capability(self) -> str:
        return "available_local_explicit_owner_context" if self._installed else "inactive"

    def _phase6_wiring(self) -> Phase6LiveWiringV1:
        cursor: object | None = self._base
        for _ in range(24):
            if cursor is None:
                break
            for name in ("wiring_controller", "_wiring_controller", "_wiring"):
                candidate = getattr(cursor, "__dict__", {}).get(name)
                if type(candidate) is Phase6LiveWiringV1:
                    return candidate
            cursor = getattr(cursor, "__dict__", {}).get("_base")
        raise ActivationV22Error("Phase 6 wiring authority is unavailable")

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not 1 <= fail_after <= self.TOTAL_SEAM_COUNT:
            raise ActivationV22Error("seam failpoint is outside V22 installation")
        base_failpoint = (
            fail_after if fail_after is not None and fail_after <= self.BASE_SEAM_COUNT else None
        )
        environment = dict(os.environ)
        os.environ.clear()
        os.environ.update(restore_v21_environment(environment))
        try:
            self._base.install(fail_after=base_failpoint)
        finally:
            os.environ.clear()
            os.environ.update(environment)
        if base_failpoint is not None:
            return

        module = self.contract.module
        host = self.contract.onyx_live
        declarations = module.TOOL_DECLARATIONS
        declaration = tool_declaration_v22()
        original_init = host.__init__
        original_execute = host._execute_tool
        original_build_config = host._build_config
        activation = self

        def host_init(instance: object, *args: object, **kwargs: object) -> None:
            original_init(instance, *args, **kwargs)
            if hasattr(instance, OWNER_CONTEXT_CONTROLLER):
                raise ActivationV22Error("owner context controller already exists")
            controller = OwnerContextControllerV1(instance)
            setattr(instance, OWNER_CONTEXT_CONTROLLER, controller)
            activation._controllers.append(controller)
            activation._instances.append(instance)

        async def execute_tool(instance: object, fc: object) -> object:
            if getattr(fc, "name", None) != TOOL_NAME:
                return await original_execute(instance, fc)
            arguments = dict(getattr(fc, "args", None) or {})
            action = str(arguments.get("action", ""))[:80]
            trace_id = os.urandom(8).hex()
            outcome = "completed"
            error_type = ""
            try:
                controller = getattr(instance, OWNER_CONTEXT_CONTROLLER, None)
                if type(controller) is not OwnerContextControllerV1:
                    raise ActivationV22Error("owner context controller is unavailable")
                response = controller.execute(arguments)
                outcome = str(response.get("status", "completed"))
            except Exception as exc:
                outcome = "rejected"
                error_type = type(exc).__name__
                response = {
                    "contract": "OnyxOwnerContextCommand.v1",
                    "status": "rejected",
                    "action": action,
                    "result": "Owner context request failed closed.",
                    "error": error_type,
                    "external_dispatch": False,
                }
            try:
                append_tool_audit(
                    profile="runtime",
                    tool=TOOL_NAME,
                    action=action,
                    decision="dispatch",
                    reason="explicit_owner_local_context_only",
                    arguments=arguments,
                    outcome=outcome,
                    trace_id=trace_id,
                    error_type=error_type,
                )
            except Exception:
                mark_audit_unhealthy()
            return module.types.FunctionResponse(
                id=getattr(fc, "id", None),
                name=TOOL_NAME,
                response=response,
            )

        def build_config(instance: object) -> object:
            config = original_build_config(instance)
            controller = getattr(instance, OWNER_CONTEXT_CONTROLLER, None)
            if type(controller) is not OwnerContextControllerV1:
                raise ActivationV22Error("owner context prompt projection is unavailable")
            projection = controller.prompt_projection()
            if not projection:
                return config
            current = getattr(config, "system_instruction", None)
            if type(current) is not str:
                raise ActivationV22Error("live system instruction contract diverged")
            config.system_instruction = current + "\n\n[OWNER-PROVIDED DAY-TO-DAY CONTEXT]\n" + projection
            return config

        try:
            if any(
                isinstance(item, dict) and item.get("name") == TOOL_NAME
                for item in declarations
            ):
                raise ActivationV22Error("owner context declaration already exists")
            declarations.append(declaration)
            self._declaration = declaration
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV22Error("injected V22 declaration failure")

            wiring = self._phase6_wiring()
            with wiring._lock:
                wiring_original_init = wiring._installed_values.get("__init__")
                if wiring_original_init is not original_init:
                    raise ActivationV22Error("Phase 6 constructor authority diverged")
                host.__init__ = host_init
                wiring._installed_values["__init__"] = host_init
            self._wiring = wiring
            self._original_init = original_init
            self._owned_init = host_init
            self._wiring_original_init = wiring_original_init
            if fail_after == self.BASE_SEAM_COUNT + 2:
                raise ActivationV22Error("injected V22 constructor failure")

            with wiring._lock:
                wiring_original_execute = wiring._protected.get("_execute_tool")
                if wiring_original_execute is not original_execute:
                    raise ActivationV22Error("Phase 6 execute authority diverged")
                host._execute_tool = execute_tool
                wiring._protected["_execute_tool"] = execute_tool
            self._original_execute = original_execute
            self._owned_execute = execute_tool
            self._wiring_original_execute = wiring_original_execute
            if fail_after == self.BASE_SEAM_COUNT + 3:
                raise ActivationV22Error("injected V22 routing failure")

            host._build_config = build_config
            self._original_build_config = original_build_config
            self._owned_build_config = build_config
            if fail_after == self.BASE_SEAM_COUNT + 4:
                raise ActivationV22Error("injected V22 prompt projection failure")

            setattr(host, HOST_MARKER, self)
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV22Error("injected V22 marker failure")
            self._installed = True
        except BaseException:
            self.rollback_all()
            raise

    def instantiate_live(self, ui: object) -> object:
        if not self._installed:
            raise ActivationV22Error("V22 activation is not installed")
        instance = self._base.instantiate_live(ui)
        if type(getattr(instance, OWNER_CONTEXT_CONTROLLER, None)) is not OwnerContextControllerV1:
            raise ActivationV22Error("owner context controller did not reach V22")
        return instance

    def rollback_to_v21(self) -> None:
        errors: list[BaseException] = []
        host = self.contract.onyx_live
        wiring = self._wiring
        for controller in reversed(self._controllers):
            try:
                controller.close()
            except BaseException as exc:
                errors.append(exc)
        self._controllers.clear()
        for instance in tuple(self._instances):
            try:
                if type(getattr(instance, OWNER_CONTEXT_CONTROLLER, None)) is OwnerContextControllerV1:
                    delattr(instance, OWNER_CONTEXT_CONTROLLER)
            except BaseException as exc:
                errors.append(exc)
        self._instances.clear()
        if self._owned_build_config is not None:
            try:
                if host._build_config is not self._owned_build_config:
                    raise ActivationV22Error("V22 build-config rollback drift")
                host._build_config = self._original_build_config
            except BaseException as exc:
                errors.append(exc)
        if self._owned_execute is not None:
            try:
                if wiring is None:
                    raise ActivationV22Error("V22 execute rollback authority is missing")
                with wiring._lock:
                    if (
                        host._execute_tool is not self._owned_execute
                        or wiring._protected.get("_execute_tool") is not self._owned_execute
                    ):
                        raise ActivationV22Error("V22 execute rollback drift")
                    host._execute_tool = self._original_execute
                    wiring._protected["_execute_tool"] = self._wiring_original_execute
            except BaseException as exc:
                errors.append(exc)
        if self._owned_init is not None:
            try:
                if wiring is None:
                    raise ActivationV22Error("V22 constructor rollback authority is missing")
                with wiring._lock:
                    if (
                        host.__init__ is not self._owned_init
                        or wiring._installed_values.get("__init__") is not self._owned_init
                    ):
                        raise ActivationV22Error("V22 constructor rollback drift")
                    host.__init__ = self._original_init
                    wiring._installed_values["__init__"] = self._wiring_original_init
            except BaseException as exc:
                errors.append(exc)
        marker = getattr(host, HOST_MARKER, None)
        if marker is self:
            delattr(host, HOST_MARKER)
        elif marker is not None:
            errors.append(ActivationV22Error("V22 marker rollback drift"))
        declarations = getattr(self.contract.module, "TOOL_DECLARATIONS", None)
        if isinstance(declarations, list) and self._declaration is not None:
            declarations[:] = [item for item in declarations if item is not self._declaration]
        if getattr(self.contract.module, "_onyx_live_activation_v22", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v22")
        self._declaration = None
        self._original_init = None
        self._owned_init = None
        self._wiring_original_init = None
        self._original_execute = None
        self._owned_execute = None
        self._wiring_original_execute = None
        self._original_build_config = None
        self._owned_build_config = None
        self._wiring = None
        self._installed = False
        if errors:
            raise ActivationV22Error("V22 rollback completed with errors") from errors[0]

    def rollback_all(self) -> None:
        errors: list[BaseException] = []
        try:
            self.rollback_to_v21()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._base.rollback_all()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise ActivationV22Error("V22 full rollback completed with errors") from errors[0]


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
    **v21_options: Any,
) -> OnyxLiveActivationV22:
    source = os.environ if environ is None else environ
    options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    controller = OnyxLiveActivationV22(
        ActivationFlagsV22.from_canonical_environ(source, **options),
        preflight_host(
            module,
            source,
            portable_bindings=portable_bindings,
            **options,
        ),
        portable_bindings=portable_bindings,
        **v21_options,
    )
    controller.install()
    module._onyx_live_activation_v22 = controller
    return controller


__all__ = [
    "ActivationFlagsV22",
    "ActivationV22Error",
    "CONTROL_FLAGS",
    "FEATURE_FLAG",
    "HOST_MARKER",
    "HostContractV22",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV22",
    "OWNER_CONTEXT_CONTROLLER",
    "TOOL_NAME",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v21_environment",
    "tool_declaration_v22",
]
