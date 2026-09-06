"""Default-off capability-extension composition over exact Onyx Live V24.

V25 adds one reversible model-tool seam and one session controller.  It does
not create another executor, permission boundary, model session, mission store,
provider loop or UI surface.  Unknown tools always delegate to the protected
V24 dispatcher.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

from core import onyx_live_activation_v24 as v24
from core import permission_broker
from core.capability_extensions_controller_v1 import (
    HOST_CONTROLLER,
    CapabilityExtensionsControllerDenied,
    CapabilityExtensionsControllerV1,
)
from core.capability_extensions_live_v1 import (
    FEATURE_FLAGS,
    CapabilityExtensionAdaptersV1,
    CapabilityExtensionGatesV1,
    CapabilityExtensionsDenied,
    CapabilityExternalOutcomeUnknown,
)
from core.permission_broker import mark_audit_unhealthy
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1
from core.tool_audit import append_tool_audit


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V25"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V25"
FEATURE_FLAG: Final = "ONYX_CAPABILITY_EXTENSIONS_LIVE_V1"
TOOL_NAME: Final = "onyx_capability_extensions"
HOST_MARKER: Final = "_capability_extensions_activation_v25"
MODULE_MARKER: Final = "_onyx_live_activation_v25"
V24_SHA256: Final = "a058c74fc9f80455b5f298d473775ece1f0ff805b774a9524a84d3de0493c82f"
CONTROL_FLAGS: Final = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    FEATURE_FLAG,
    *FEATURE_FLAGS,
    *v24.CONTROL_FLAGS,
)

_ACTIONS: Final = (
    "status",
    "initiate_pairing",
    "cancel_pairing",
    "pairing_status",
    "send_official_message",
    "official_message_status",
    "list_site_recipes",
    "plan_site_recipe",
    "perform_accessibility_action",
    "schedule_content",
    "reserve_content",
    "cancel_content",
    "get_content",
    "list_content",
)
_READ_ONLY_ACTIONS: Final = frozenset(
    {
        "status",
        "pairing_status",
        "official_message_status",
        "list_site_recipes",
        "plan_site_recipe",
        "get_content",
        "list_content",
    }
)
_AUTONOMOUS_LOCAL_ACTIONS: Final = frozenset(
    set(_READ_ONLY_ACTIONS)
    | {
        "initiate_pairing",
        "cancel_pairing",
        "schedule_content",
        "reserve_content",
        "cancel_content",
    }
)


class ActivationV25Error(RuntimeError):
    pass


def _authenticate_v24() -> None:
    expected = Path(__file__).resolve().with_name("onyx_live_activation_v24.py")
    try:
        source = expected.read_bytes()
        loaded = Path(v24.__file__).resolve()
    except OSError as exc:
        raise ActivationV25Error("exact V24 predecessor is unavailable") from exc
    if loaded != expected or hashlib.sha256(source).hexdigest() != V24_SHA256:
        raise ActivationV25Error("exact V24 predecessor is unavailable")


_authenticate_v24()


def _audit_arguments(arguments: Mapping[str, object]) -> dict[str, object]:
    """Return schema-only audit metadata; never pass bodies, codes or values."""

    sensitive = frozenset({"content", "display_code", "value"})
    keys = sorted(str(key) for key in arguments)
    return {
        "action": str(arguments.get("action", ""))[:80],
        "argument_keys": tuple(keys),
        "sensitive_fields_redacted": tuple(key for key in keys if key in sensitive),
    }


def tool_declaration_v25() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": (
            "Use Onyx's feature-gated device pairing, official messaging, site "
            "recipe, portable accessibility and content lifecycle extensions. "
            "Disabled or adapterless capabilities fail closed."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "enum": list(_ACTIONS)},
                "device_id": {"type": "STRING"},
                "issuer": {"type": "STRING"},
                "ttl_seconds": {"type": "NUMBER"},
                "pairing_id": {"type": "STRING"},
                "account_id": {"type": "STRING"},
                "channel_id": {"type": "STRING"},
                "content": {"type": "STRING"},
                "operation_id": {"type": "STRING"},
                "recipe_id": {"type": "STRING"},
                "project_slug": {"type": "STRING"},
                "title": {"type": "STRING"},
                "summary": {"type": "STRING"},
                "primary_action": {"type": "STRING"},
                "request_id": {"type": "STRING"},
                "application_id": {"type": "STRING"},
                "role": {"type": "STRING"},
                "accessible_name": {"type": "STRING"},
                "accessibility_action": {
                    "type": "STRING",
                    "enum": ["focus", "invoke", "set_value", "type_text"],
                },
                "value": {"type": "STRING"},
                "provider": {"type": "STRING"},
                "destination_id": {"type": "STRING"},
                "scheduled_for": {"type": "NUMBER"},
                "content_id": {"type": "STRING"},
                "limit": {"type": "INTEGER"},
            },
            "required": ["action"],
        },
    }


@dataclass(frozen=True, slots=True)
class ActivationFlagsV25:
    base: v24.ActivationFlagsV24
    gates: CapabilityExtensionGatesV1

    def __post_init__(self) -> None:
        if (
            type(self.base) is not v24.ActivationFlagsV24
            or type(self.gates) is not CapabilityExtensionGatesV1
        ):
            raise ActivationV25Error("exact V25 activation flags are required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV25":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV25Error("rollback is not an active V25 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(FEATURE_FLAG) != "true":
            raise ActivationV25Error("activation environment is not canonical V25")
        gates = CapabilityExtensionGatesV1.from_environ(source)
        try:
            base = v24.ActivationFlagsV24.from_canonical_environ(
                restore_v24_environment(source)
            )
        except v24.ActivationV24Error as exc:
            raise ActivationV25Error("V24 environment is incomplete") from exc
        return cls(base, gates)


def exact_activation_environment(
    workspace_roots: Sequence[str | os.PathLike[str]],
    *,
    gates: CapabilityExtensionGatesV1 | None = None,
) -> dict[str, str]:
    selected = gates or CapabilityExtensionGatesV1()
    if type(selected) is not CapabilityExtensionGatesV1:
        raise ActivationV25Error("exact capability gates are required")
    result = v24.exact_activation_environment(workspace_roots)
    result[LIVE_MASTER_FLAG] = "1"
    result[FEATURE_FLAG] = "true"
    result.update(selected.environment())
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v24_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    for name in (LIVE_MASTER_FLAG, LIVE_ROLLBACK_FLAG, FEATURE_FLAG, *FEATURE_FLAGS):
        result.pop(name, None)
    return result


@dataclass(frozen=True, slots=True)
class HostContractV25:
    module: ModuleType
    onyx_live: type
    project: Path
    base: v24.HostContractV24


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
) -> HostContractV25:
    source = os.environ if environ is None else environ
    ActivationFlagsV25.from_canonical_environ(source)
    try:
        base = v24.preflight_host(module, restore_v24_environment(source))
    except v24.ActivationV24Error as exc:
        raise ActivationV25Error("exact V24 host preflight failed") from exc
    host = getattr(base.base, "onyx_live", None)
    declarations = getattr(module, "TOOL_DECLARATIONS", None)
    if (
        not isinstance(host, type)
        or not isinstance(declarations, list)
        or not callable(getattr(host, "__init__", None))
        or not callable(getattr(host, "_execute_tool", None))
        or not callable(getattr(module, "authorize_model_tool", None))
        or not callable(getattr(module, "set_audit_trace_id", None))
        or not callable(getattr(module, "reset_audit_trace_id", None))
        or hasattr(host, HOST_MARKER)
        or hasattr(module, MODULE_MARKER)
    ):
        raise ActivationV25Error("V25 host contract is unavailable")
    return HostContractV25(module, host, base.project, base)


class _ProtectedDispatchV25:
    __slots__ = ("_dispatch",)

    def __init__(self, dispatch: object) -> None:
        if not callable(dispatch):
            raise ActivationV25Error("V25 protected dispatcher is invalid")
        self._dispatch = dispatch

    def __get__(self, instance: object | None, owner: type | None = None) -> object:
        if instance is None:
            return self._dispatch
        return self._dispatch.__get__(instance, owner)  # type: ignore[union-attr]

    def __set__(self, instance: object, value: object) -> None:
        raise ActivationV25Error("V25 protected dispatcher cannot be shadowed")

    def __delete__(self, instance: object) -> None:
        raise ActivationV25Error("V25 protected dispatcher cannot be deleted")


@dataclass(slots=True)
class _BindingV25:
    instance: object
    previous_class: type
    guarded_class: type
    owned_dispatch: object
    owned_setattr: object


class OnyxLiveActivationV25:
    """Own only the additive controller/tool seams outside V24."""

    V25_SEAM_COUNT = 5

    def __init__(
        self,
        flags: ActivationFlagsV25,
        contract: HostContractV25,
        *,
        adapters: CapabilityExtensionAdaptersV1 | None = None,
    ) -> None:
        if type(flags) is not ActivationFlagsV25 or type(contract) is not HostContractV25:
            raise ActivationV25Error("exact V25 activation bindings are required")
        selected_adapters = adapters or CapabilityExtensionAdaptersV1()
        if type(selected_adapters) is not CapabilityExtensionAdaptersV1:
            raise ActivationV25Error("exact V25 extension adapters are required")
        self.flags = flags
        self.contract = contract
        self.adapters = selected_adapters
        self._base = v24.OnyxLiveActivationV24(flags.base, contract.base)
        self._installed = False
        self._declaration: dict[str, object] | None = None
        self._original_init: object | None = None
        self._owned_init: object | None = None
        self._wiring_original_init: object | None = None
        self._wiring: Phase6LiveWiringV1 | None = None
        self._controllers: list[CapabilityExtensionsControllerV1] = []
        self._instances: list[object] = []
        self._bindings: list[_BindingV25] = []
        self._policy_installed = False

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    @property
    def capability_extensions(self) -> dict[str, bool]:
        return self.flags.gates.payload() if self._installed else {}

    def _phase6_wiring(self) -> Phase6LiveWiringV1:
        cursor: object | None = self._base
        for _ in range(32):
            if cursor is None:
                break
            for name in ("wiring_controller", "_wiring_controller", "_wiring"):
                candidate = getattr(cursor, "__dict__", {}).get(name)
                if type(candidate) is Phase6LiveWiringV1:
                    return candidate
            cursor = getattr(cursor, "__dict__", {}).get("_base")
        raise ActivationV25Error("Phase 6 wiring authority is unavailable")

    @staticmethod
    def _install_policy() -> None:
        if any(
            TOOL_NAME in registry
            for registry in (
                permission_broker.MODEL_TOOL_POLICIES,
                permission_broker.MODEL_TOOL_ACTIONS,
                permission_broker._AUTONOMOUS_ACTIONS,
            )
        ):
            raise ActivationV25Error("capability extension policy already exists")
        permission_broker.MODEL_TOOL_POLICIES[TOOL_NAME] = "action_policy"
        permission_broker.MODEL_TOOL_ACTIONS[TOOL_NAME] = frozenset(_ACTIONS)
        permission_broker._AUTONOMOUS_ACTIONS[TOOL_NAME] = _AUTONOMOUS_LOCAL_ACTIONS

    @staticmethod
    def _remove_policy() -> None:
        expected = (
            (permission_broker.MODEL_TOOL_POLICIES, "action_policy"),
            (permission_broker.MODEL_TOOL_ACTIONS, frozenset(_ACTIONS)),
            (permission_broker._AUTONOMOUS_ACTIONS, _AUTONOMOUS_LOCAL_ACTIONS),
        )
        for registry, value in expected:
            if registry.get(TOOL_NAME) != value:
                raise ActivationV25Error("capability extension policy rollback drifted")
        for registry, _value in expected:
            registry.pop(TOOL_NAME)

    def install(self, *, fail_after: int | None = None) -> None:
        if self._installed:
            raise ActivationV25Error("V25 is already installed")
        if fail_after is not None and not 1 <= fail_after <= self.V25_SEAM_COUNT:
            raise ActivationV25Error("seam failpoint is outside V25 installation")
        environment = dict(os.environ)
        os.environ.clear()
        os.environ.update(restore_v24_environment(environment))
        try:
            self._base.install()
            if hasattr(self.contract.module, v24.HOST_MARKER):
                raise ActivationV25Error("V24 module marker already exists")
            setattr(self.contract.module, v24.HOST_MARKER, self._base)
        finally:
            os.environ.clear()
            os.environ.update(environment)

        module = self.contract.module
        host = self.contract.onyx_live
        declarations = module.TOOL_DECLARATIONS
        declaration = tool_declaration_v25()
        original_init = host.__init__
        activation = self

        def host_init(instance: object, *args: object, **kwargs: object) -> None:
            original_init(instance, *args, **kwargs)
            if hasattr(instance, HOST_CONTROLLER):
                raise ActivationV25Error("capability controller already exists")
            controller = CapabilityExtensionsControllerV1(
                instance,
                gates=activation.flags.gates,
                adapters=activation.adapters,
                central_authorizer=activation.contract.module.authorize_model_tool,
                audit_trace_setter=activation.contract.module.set_audit_trace_id,
                audit_trace_resetter=activation.contract.module.reset_audit_trace_id,
            )
            setattr(instance, HOST_CONTROLLER, controller)
            activation._controllers.append(controller)
            activation._instances.append(instance)

        try:
            if any(
                isinstance(item, dict) and item.get("name") == TOOL_NAME
                for item in declarations
            ):
                raise ActivationV25Error("capability declaration already exists")
            declarations.append(declaration)
            self._declaration = declaration
            if fail_after == 1:
                raise ActivationV25Error("injected V25 declaration failure")

            self._install_policy()
            self._policy_installed = True
            if fail_after == 2:
                raise ActivationV25Error("injected V25 policy failure")

            wiring = self._phase6_wiring()
            with wiring._lock:
                wiring_original_init = wiring._installed_values.get("__init__")
                if wiring_original_init is not original_init:
                    raise ActivationV25Error("Phase 6 constructor authority diverged")
                host.__init__ = host_init
                wiring._installed_values["__init__"] = host_init
            self._wiring = wiring
            self._original_init = original_init
            self._owned_init = host_init
            self._wiring_original_init = wiring_original_init
            if fail_after == 3:
                raise ActivationV25Error("injected V25 constructor failure")

            setattr(host, HOST_MARKER, self)
            if fail_after == 4:
                raise ActivationV25Error("injected V25 host marker failure")
            self._installed = True
            if fail_after == 5:
                raise ActivationV25Error("injected V25 completion failure")
        except BaseException:
            try:
                self.rollback_to_v24()
            finally:
                self._base.rollback_all()
            raise

    async def _dispatch(
        self, instance: object, original: object, function_call: object
    ) -> object:
        name = str(getattr(function_call, "name", ""))
        if name != TOOL_NAME:
            return await original(function_call)  # type: ignore[operator]
        if callable(getattr(instance, "_runtime_input_is_quiesced", None)) and (
            instance._runtime_input_is_quiesced()
        ):
            return self.contract.module.types.FunctionResponse(
                id=getattr(function_call, "id", None),
                name=name,
                response={"result": "Action refused: shutdown is already in progress."},
            )
        task = asyncio.current_task()
        tracked = getattr(instance, "_external_action_tasks", None)
        if tracked is None:
            tracked = set()
            setattr(instance, "_external_action_tasks", tracked)
        if task is not None:
            tracked.add(task)
        arguments = dict(getattr(function_call, "args", None) or {})
        action = str(arguments.get("action", "")).strip()
        trace_id = os.urandom(8).hex()

        def finish(response: dict[str, object], outcome: str, error: str = "") -> object:
            governance = getattr(instance, "_governance_nucleus_v1", None)
            if governance is not None:
                try:
                    governance.record_outcome(
                        invocation_id=str(getattr(function_call, "id", "") or ""),
                        outcome=outcome,
                        result=response,
                        error_type=error,
                    )
                except Exception:
                    mark_audit_unhealthy()
            try:
                append_tool_audit(
                    profile="runtime",
                    tool=TOOL_NAME,
                    action=action,
                    decision="dispatch",
                    reason=error or outcome,
                    arguments=_audit_arguments(arguments),
                    outcome=outcome,
                    trace_id=trace_id,
                    error_type=error,
                )
            except Exception:
                mark_audit_unhealthy()
            ui = getattr(instance, "ui", None)
            if ui is not None and not getattr(ui, "muted", False):
                ui.set_state("LISTENING")
            return self.contract.module.types.FunctionResponse(
                id=getattr(function_call, "id", None),
                name=TOOL_NAME,
                response=response,
            )

        try:
            controller = getattr(instance, HOST_CONTROLLER, None)
            if type(controller) is not CapabilityExtensionsControllerV1:
                return finish(
                    {"status": "rejected", "result": "Capability extensions are unavailable."},
                    "rejected",
                    "CapabilityControllerUnavailable",
                )
            try:
                await instance._run_external_action(controller.preflight_action, action)
            except Exception as exc:
                return finish(
                    {
                        "contract": "OnyxCapabilityExtensionsCommand.v1",
                        "status": "rejected",
                        "action": action,
                        "result": "Capability extension request is disabled or unavailable.",
                        "external_dispatch": False,
                    },
                    "rejected",
                    type(exc).__name__,
                )
            if callable(getattr(instance, "_runtime_input_is_quiesced", None)) and (
                instance._runtime_input_is_quiesced()
            ):
                return finish(
                    {"result": "Action refused: shutdown began before dispatch."},
                    "denied",
                    "ShutdownBarrierActive",
                )
            try:
                response = await instance._run_external_action(
                    controller.execute,
                    arguments,
                    invocation_id=str(getattr(function_call, "id", "") or ""),
                    trace_id=trace_id,
                )
            except (CapabilityExtensionsControllerDenied, CapabilityExtensionsDenied) as exc:
                return finish(
                    {
                        "contract": "OnyxCapabilityExtensionsCommand.v1",
                        "status": "denied",
                        "action": action,
                        "result": str(exc),
                        "external_dispatch": False,
                    },
                    "denied",
                    type(exc).__name__,
                )
            except CapabilityExternalOutcomeUnknown as exc:
                return finish(
                    {
                        "contract": "OnyxCapabilityExtensionsCommand.v1",
                        "status": "attempted_unknown",
                        "action": action,
                        "result": "External outcome requires reconciliation; no retry was issued.",
                        "external_dispatch": True,
                    },
                    "attempted_unknown",
                    type(exc).__name__,
                )
            except Exception as exc:
                return finish(
                    {
                        "contract": "OnyxCapabilityExtensionsCommand.v1",
                        "status": "rejected",
                        "action": action,
                        "result": "Capability extension request failed closed.",
                        "external_dispatch": False,
                    },
                    "rejected",
                    type(exc).__name__,
                )
            return finish(response, str(response.get("status", "completed")))
        finally:
            if task is not None:
                tracked.discard(task)

    def _bind_instance(self, instance: object) -> None:
        if any(binding.instance is instance for binding in self._bindings):
            raise ActivationV25Error("V25 instance is already guarded")
        original = getattr(instance, "_execute_tool", None)
        if not callable(original):
            raise ActivationV25Error("V24 dispatcher is unavailable")
        previous_class = type(instance)
        previous_setattr = previous_class.__setattr__
        activation = self

        async def dispatch(owner: object, function_call: object) -> object:
            return await activation._dispatch(owner, original, function_call)

        protected_dispatch = _ProtectedDispatchV25(dispatch)

        def protected_setattr(owner: object, name: str, value: object) -> None:
            if name == "_execute_tool":
                raise ActivationV25Error("V25 protected dispatcher cannot be shadowed")
            previous_setattr(owner, name, value)

        guarded_class = type(
            f"{previous_class.__name__}V25Extensions_{id(instance):x}",
            (previous_class,),
            {
                "__slots__": (),
                "__module__": previous_class.__module__,
                "_execute_tool": protected_dispatch,
                "__setattr__": protected_setattr,
            },
        )
        instance.__class__ = guarded_class
        if type(instance) is not guarded_class:
            raise ActivationV25Error("V25 dispatcher binding drifted")
        self._bindings.append(
            _BindingV25(
                instance,
                previous_class,
                guarded_class,
                protected_dispatch,
                protected_setattr,
            )
        )

    def instantiate_live(self, ui: object) -> object:
        if not self._installed:
            raise ActivationV25Error("V25 activation is not installed")
        instance = self._base.instantiate_live(ui)
        if type(getattr(instance, HOST_CONTROLLER, None)) is not CapabilityExtensionsControllerV1:
            raise ActivationV25Error("capability controller did not reach V25")
        self._bind_instance(instance)
        return instance

    def rollback_to_v24(self) -> None:
        errors: list[BaseException] = []
        for binding in reversed(self._bindings):
            try:
                if (
                    type(binding.instance) is not binding.guarded_class
                    or binding.guarded_class.__dict__.get("_execute_tool")
                    is not binding.owned_dispatch
                    or binding.guarded_class.__dict__.get("__setattr__")
                    is not binding.owned_setattr
                ):
                    raise ActivationV25Error("V25 instance rollback drifted")
                binding.instance.__class__ = binding.previous_class
            except BaseException as exc:
                errors.append(exc)
            else:
                self._bindings.remove(binding)
        for controller in reversed(self._controllers):
            try:
                controller.close()
            except BaseException as exc:
                errors.append(exc)
        self._controllers.clear()
        for instance in tuple(self._instances):
            try:
                if type(getattr(instance, HOST_CONTROLLER, None)) is CapabilityExtensionsControllerV1:
                    delattr(instance, HOST_CONTROLLER)
            except BaseException as exc:
                errors.append(exc)
        self._instances.clear()
        if self._owned_init is not None:
            try:
                wiring = self._wiring
                if wiring is None:
                    raise ActivationV25Error("V25 constructor rollback authority is missing")
                with wiring._lock:
                    if (
                        self.contract.onyx_live.__init__ is not self._owned_init
                        or wiring._installed_values.get("__init__") is not self._owned_init
                    ):
                        raise ActivationV25Error("V25 constructor rollback drifted")
                    self.contract.onyx_live.__init__ = self._original_init
                    wiring._installed_values["__init__"] = self._wiring_original_init
            except BaseException as exc:
                errors.append(exc)
        marker = getattr(self.contract.onyx_live, HOST_MARKER, None)
        if marker is self:
            delattr(self.contract.onyx_live, HOST_MARKER)
        elif marker is not None:
            errors.append(ActivationV25Error("V25 host marker rollback drifted"))
        declarations = getattr(self.contract.module, "TOOL_DECLARATIONS", None)
        if isinstance(declarations, list) and self._declaration is not None:
            declarations[:] = [item for item in declarations if item is not self._declaration]
        if self._policy_installed:
            try:
                self._remove_policy()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._policy_installed = False
        if getattr(self.contract.module, MODULE_MARKER, None) is self:
            delattr(self.contract.module, MODULE_MARKER)
        self._declaration = None
        self._original_init = None
        self._owned_init = None
        self._wiring_original_init = None
        self._wiring = None
        self._installed = False
        if errors:
            raise ActivationV25Error("V25 rollback completed with errors") from errors[0]

    def rollback_all(self) -> None:
        errors: list[BaseException] = []
        try:
            self.rollback_to_v24()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._base.rollback_all()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise ActivationV25Error("V25 full rollback completed with errors") from errors[0]


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    adapters: CapabilityExtensionAdaptersV1 | None = None,
) -> OnyxLiveActivationV25:
    source = os.environ if environ is None else environ
    controller = OnyxLiveActivationV25(
        ActivationFlagsV25.from_canonical_environ(source),
        preflight_host(module, source),
        adapters=adapters,
    )
    controller.install()
    setattr(module, MODULE_MARKER, controller)
    return controller


__all__ = [
    "ActivationFlagsV25",
    "ActivationV25Error",
    "CONTROL_FLAGS",
    "FEATURE_FLAG",
    "HOST_MARKER",
    "HostContractV25",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "MODULE_MARKER",
    "OnyxLiveActivationV25",
    "TOOL_NAME",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v24_environment",
    "tool_declaration_v25",
]
