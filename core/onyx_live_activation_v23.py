"""Operational event wiring over exact Onyx Live V22.

V23 keeps the existing engine, voice, HUD, DayOps and Phase 6 authorities. It
only wraps trusted DayOps callbacks so normalized calendar/mail/connectivity
state reaches the already-live awareness and governed-automation queues.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import onyx_live_activation_v22 as v22
from core.operational_event_controller_v1 import (
    HOST_CONTROLLER as OPERATIONAL_EVENT_CONTROLLER,
    OperationalEventControllerV1,
)
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1
from core.portable_host_capability_v1 import PortableHostBindingsV1


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V23"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V23"
FEATURE_FLAG: Final = "ONYX_OPERATIONAL_EVENTS_V1"
HOST_MARKER: Final = "_operational_events_activation_v23"
CONTROL_FLAGS: Final = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    FEATURE_FLAG,
    *v22.CONTROL_FLAGS,
)
_DAYOPS_CALLBACKS: Final = (
    "on_dayops_connect",
    "on_dayops_sign_in",
    "on_dayops_disconnect",
    "on_dayops_today_brief",
)


class ActivationV23Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ActivationFlagsV23:
    master: bool
    operational_events: bool
    base: v22.ActivationFlagsV22

    def __post_init__(self) -> None:
        if (
            self.master is not True
            or self.operational_events is not True
            or type(self.base) is not v22.ActivationFlagsV22
        ):
            raise ActivationV23Error("complete exact V23 flags are required")

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_endpoint_factory: object | None = None,
    ) -> "ActivationFlagsV23":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV23Error("rollback is not an active V23 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(FEATURE_FLAG) != "true":
            raise ActivationV23Error("activation environment is not canonical V23")
        options = (
            {}
            if runtime_endpoint_factory is None
            else {"runtime_endpoint_factory": runtime_endpoint_factory}
        )
        try:
            base = v22.ActivationFlagsV22.from_canonical_environ(
                restore_v22_environment(source), **options
            )
        except v22.ActivationV22Error as exc:
            raise ActivationV23Error("V22 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment(
    workspace_roots: Sequence[str | os.PathLike[str]],
    **v22_options: Any,
) -> dict[str, str]:
    result = v22.exact_activation_environment(workspace_roots, **v22_options)
    result[LIVE_MASTER_FLAG] = "1"
    result[FEATURE_FLAG] = "true"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v22_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(FEATURE_FLAG, None)
    return result


@dataclass(frozen=True, slots=True)
class HostContractV23:
    module: ModuleType
    onyx_live: type
    project: Path
    base: v22.HostContractV22


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
) -> HostContractV23:
    source = os.environ if environ is None else environ
    options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    ActivationFlagsV23.from_canonical_environ(source, **options)
    try:
        base = v22.preflight_host(
            module,
            restore_v22_environment(source),
            portable_bindings=portable_bindings,
            **options,
        )
    except v22.ActivationV22Error as exc:
        raise ActivationV23Error("V22 host preflight failed") from exc
    host = getattr(module, "OnyxLive", None)
    if (
        not isinstance(host, type)
        or host is not base.onyx_live
        or not callable(getattr(host, "__init__", None))
        or hasattr(host, HOST_MARKER)
    ):
        raise ActivationV23Error("V23 host contract is unavailable")
    return HostContractV23(module, host, base.project, base)


def _receipt_unavailable(error: BaseException) -> dict[str, object]:
    return {
        "contract": "OnyxOperationalEventReceipt.v1",
        "status": "not_published",
        "published": 0,
        "content_captured": False,
        "error": type(error).__name__,
        "background_workers": 0,
        "polling_interval": None,
    }


class OnyxLiveActivationV23:
    BASE_SEAM_COUNT = v22.OnyxLiveActivationV22.TOTAL_SEAM_COUNT
    V23_SEAM_COUNT = 2
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V23_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV23,
        contract: HostContractV23,
        **v22_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV23 or type(contract) is not HostContractV23:
            raise ActivationV23Error("exact V23 activation bindings are required")
        self.flags = flags
        self.contract = contract
        self._base = v22.OnyxLiveActivationV22(flags.base, contract.base, **v22_options)
        self._installed = False
        self._original_init: object | None = None
        self._owned_init: object | None = None
        self._wiring_original_init: object | None = None
        self._wiring: Phase6LiveWiringV1 | None = None
        self._instances: list[object] = []
        self._controllers: list[OperationalEventControllerV1] = []
        self._callback_bindings: list[
            tuple[object, dict[str, object], dict[str, object]]
        ] = []

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    @property
    def operational_events_capability(self) -> str:
        return "available_metadata_only_event_driven" if self._installed else "inactive"

    def _phase6_wiring(self) -> Phase6LiveWiringV1:
        cursor: object | None = self._base
        for _ in range(28):
            if cursor is None:
                break
            for name in ("wiring_controller", "_wiring_controller", "_wiring"):
                candidate = getattr(cursor, "__dict__", {}).get(name)
                if type(candidate) is Phase6LiveWiringV1:
                    return candidate
            cursor = getattr(cursor, "__dict__", {}).get("_base")
        raise ActivationV23Error("Phase 6 wiring authority is unavailable")

    @staticmethod
    def _callback(
        operation: str,
        original: object,
        controller: OperationalEventControllerV1,
    ) -> object:
        if not callable(original):
            raise ActivationV23Error("trusted DayOps callback is unavailable")

        def wrapped(*args: object, **kwargs: object) -> object:
            result = original(*args, **kwargs)
            if type(result) is not dict:
                return result
            public = dict(result)
            try:
                if operation == "today_brief":
                    receipt = controller.publish_dayops_brief(public)
                else:
                    receipt = controller.publish_connectivity_result(operation, public)
            except Exception as exc:
                receipt = _receipt_unavailable(exc)
            public["operational_event"] = receipt
            return public

        return wrapped

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not 1 <= fail_after <= self.TOTAL_SEAM_COUNT:
            raise ActivationV23Error("seam failpoint is outside V23 installation")
        base_failpoint = (
            fail_after if fail_after is not None and fail_after <= self.BASE_SEAM_COUNT else None
        )
        environment = dict(os.environ)
        os.environ.clear()
        os.environ.update(restore_v22_environment(environment))
        try:
            self._base.install(fail_after=base_failpoint)
        finally:
            os.environ.clear()
            os.environ.update(environment)
        if base_failpoint is not None:
            return

        host = self.contract.onyx_live
        original_init = host.__init__
        activation = self

        def host_init(instance: object, *args: object, **kwargs: object) -> None:
            original_init(instance, *args, **kwargs)
            if hasattr(instance, OPERATIONAL_EVENT_CONTROLLER):
                raise ActivationV23Error("operational event controller already exists")
            controller = OperationalEventControllerV1(instance)
            ui = getattr(instance, "ui", None)
            if ui is None:
                raise ActivationV23Error("trusted DayOps UI is unavailable")
            originals: dict[str, object] = {}
            owned: dict[str, object] = {}
            try:
                for name in _DAYOPS_CALLBACKS:
                    original = getattr(ui, name, None)
                    operation = name.removeprefix("on_dayops_")
                    callback = activation._callback(operation, original, controller)
                    originals[name] = original
                    owned[name] = callback
                    setattr(ui, name, callback)
                    if getattr(ui, name, None) is not callback:
                        raise ActivationV23Error("operational event callback binding drifted")
                setattr(instance, OPERATIONAL_EVENT_CONTROLLER, controller)
            except BaseException:
                for name, original in originals.items():
                    if getattr(ui, name, None) is owned.get(name):
                        setattr(ui, name, original)
                controller.close()
                raise
            activation._controllers.append(controller)
            activation._instances.append(instance)
            activation._callback_bindings.append((ui, originals, owned))

        try:
            wiring = self._phase6_wiring()
            with wiring._lock:
                wiring_original_init = wiring._installed_values.get("__init__")
                if wiring_original_init is not original_init:
                    raise ActivationV23Error("Phase 6 constructor authority diverged")
                host.__init__ = host_init
                wiring._installed_values["__init__"] = host_init
            self._wiring = wiring
            self._original_init = original_init
            self._owned_init = host_init
            self._wiring_original_init = wiring_original_init
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV23Error("injected V23 constructor failure")
            setattr(host, HOST_MARKER, self)
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV23Error("injected V23 marker failure")
            self._installed = True
        except BaseException:
            self.rollback_all()
            raise

    def instantiate_live(self, ui: object) -> object:
        if not self._installed:
            raise ActivationV23Error("V23 activation is not installed")
        instance = self._base.instantiate_live(ui)
        if type(getattr(instance, OPERATIONAL_EVENT_CONTROLLER, None)) is not OperationalEventControllerV1:
            raise ActivationV23Error("operational event controller did not reach V23")
        return instance

    def rollback_to_v22(self) -> None:
        errors: list[BaseException] = []
        host = self.contract.onyx_live
        wiring = self._wiring
        for ui, originals, owned in reversed(self._callback_bindings):
            for name, callback in owned.items():
                try:
                    if getattr(ui, name, None) is not callback:
                        raise ActivationV23Error("V23 callback rollback drift")
                    setattr(ui, name, originals[name])
                except BaseException as exc:
                    errors.append(exc)
        self._callback_bindings.clear()
        for controller in reversed(self._controllers):
            try:
                controller.close()
            except BaseException as exc:
                errors.append(exc)
        self._controllers.clear()
        for instance in tuple(self._instances):
            try:
                if type(getattr(instance, OPERATIONAL_EVENT_CONTROLLER, None)) is OperationalEventControllerV1:
                    delattr(instance, OPERATIONAL_EVENT_CONTROLLER)
            except BaseException as exc:
                errors.append(exc)
        self._instances.clear()
        if self._owned_init is not None:
            try:
                if wiring is None:
                    raise ActivationV23Error("V23 constructor rollback authority is missing")
                with wiring._lock:
                    if (
                        host.__init__ is not self._owned_init
                        or wiring._installed_values.get("__init__") is not self._owned_init
                    ):
                        raise ActivationV23Error("V23 constructor rollback drift")
                    host.__init__ = self._original_init
                    wiring._installed_values["__init__"] = self._wiring_original_init
            except BaseException as exc:
                errors.append(exc)
        marker = getattr(host, HOST_MARKER, None)
        if marker is self:
            delattr(host, HOST_MARKER)
        elif marker is not None:
            errors.append(ActivationV23Error("V23 marker rollback drift"))
        if getattr(self.contract.module, "_onyx_live_activation_v23", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v23")
        self._original_init = None
        self._owned_init = None
        self._wiring_original_init = None
        self._wiring = None
        self._installed = False
        if errors:
            raise ActivationV23Error("V23 rollback completed with errors") from errors[0]

    def rollback_all(self) -> None:
        errors: list[BaseException] = []
        try:
            self.rollback_to_v22()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._base.rollback_all()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise ActivationV23Error("V23 full rollback completed with errors") from errors[0]


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
    **v22_options: Any,
) -> OnyxLiveActivationV23:
    source = os.environ if environ is None else environ
    options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    controller = OnyxLiveActivationV23(
        ActivationFlagsV23.from_canonical_environ(source, **options),
        preflight_host(
            module,
            source,
            portable_bindings=portable_bindings,
            **options,
        ),
        portable_bindings=portable_bindings,
        **v22_options,
    )
    controller.install()
    module._onyx_live_activation_v23 = controller
    return controller


__all__ = [
    "ActivationFlagsV23",
    "ActivationV23Error",
    "CONTROL_FLAGS",
    "FEATURE_FLAG",
    "HOST_MARKER",
    "HostContractV23",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OPERATIONAL_EVENT_CONTROLLER",
    "OnyxLiveActivationV23",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v22_environment",
]
