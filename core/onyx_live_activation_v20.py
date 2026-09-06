"""Additive Advanced Operations V20 activation over exact V19.

V20 patches only the host constructor after V19 has installed.  The wrapper
lets V19 construct every existing voice, UI, governance, Phase 6 and DayOps
authority first, then attaches one lazy, zero-polling Advanced Operations
controller.  No protected provider, audio, tool-dispatch or mission seam is
changed.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import onyx_live_activation_v19 as v19
from core.advanced_operations_controller_v1 import (
    HOST_CONTROLLER,
    AdvancedOperationsControllerV1,
)
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1
from core.portable_host_capability_v1 import PortableHostBindingsV1
from core.native_workspace_events_v1 import FEATURE_FLAG as NATIVE_WORKSPACE_EVENTS_FLAG


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V20"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V20"
FEATURE_FLAG: Final = "ONYX_ADVANCED_OPERATIONS_LIVE_V1"
CONTROL_FLAGS: Final = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    FEATURE_FLAG,
    *v19.CONTROL_FLAGS,
)
HOST_MARKER: Final = "_advanced_operations_activation_v20"
UI_CALLBACKS: Final = ("on_advanced_status", "on_advanced_attention")
_PROTECTED_SEAMS: Final = (
    "_execute_tool",
    "_run_live_loop",
    "_send_realtime",
    "_start_phase5_session",
    "_stop_phase5_session",
)
_MISSING = object()
_ACTIVE_LOCK = threading.RLock()
_ACTIVE_HOST: tuple["OnyxLiveActivationV20", object] | None = None


class ActivationV20Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ActivationFlagsV20:
    master: bool
    advanced_operations: bool
    base: v19.ActivationFlagsV19

    def __post_init__(self) -> None:
        if (
            self.master is not True
            or self.advanced_operations is not True
            or type(self.base) is not v19.ActivationFlagsV19
        ):
            raise ActivationV20Error("complete exact V20 flags are required")

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_endpoint_factory: object | None = None,
    ) -> "ActivationFlagsV20":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV20Error("rollback is not an active V20 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(FEATURE_FLAG) != "true":
            raise ActivationV20Error("activation environment is not canonical V20")
        options = (
            {}
            if runtime_endpoint_factory is None
            else {"runtime_endpoint_factory": runtime_endpoint_factory}
        )
        try:
            base = v19.ActivationFlagsV19.from_canonical_environ(
                restore_v19_environment(source), **options
            )
        except v19.ActivationV19Error as exc:
            raise ActivationV20Error("V19 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment(
    workspace_roots: Sequence[str | os.PathLike[str]],
    **v19_options: Any,
) -> dict[str, str]:
    result = v19.exact_activation_environment(workspace_roots, **v19_options)
    result[LIVE_MASTER_FLAG] = "1"
    result[FEATURE_FLAG] = "true"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v19_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(FEATURE_FLAG, None)
    return result


@dataclass(frozen=True, slots=True)
class HostContractV20:
    module: ModuleType
    onyx_live: type
    project: Path
    base: v19.HostContractV19


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
) -> HostContractV20:
    source = os.environ if environ is None else environ
    options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    ActivationFlagsV20.from_canonical_environ(source, **options)
    try:
        base = v19.preflight_host(
            module,
            restore_v19_environment(source),
            portable_bindings=portable_bindings,
            **options,
        )
    except v19.ActivationV19Error as exc:
        raise ActivationV20Error("V19 host preflight failed") from exc
    host = getattr(module, "OnyxLive", None)
    if not isinstance(host, type) or host is not base.onyx_live or hasattr(host, HOST_MARKER):
        raise ActivationV20Error("V20 host contract is unavailable")
    return HostContractV20(module, host, base.project, base)


@dataclass(frozen=True, slots=True)
class _CallbackBindingV20:
    instance: object
    ui: object
    previous: tuple[tuple[str, object], ...]
    owned: tuple[tuple[str, object], ...]


ControllerFactoryV20 = Callable[[object], AdvancedOperationsControllerV1]


def _deny_owner_authority(
    _owner_profile_id: str,
    _workspace_id: str,
    _subject_id: str,
    _decision_digest: str,
) -> bool:
    # Promotion gets a dedicated trusted command in a later V20 slice.  Until
    # then suggestions may be projected but cannot silently promote themselves.
    return False


class OnyxLiveActivationV20:
    BASE_SEAM_COUNT = v19.OnyxLiveActivationV19.TOTAL_SEAM_COUNT
    V20_SEAM_COUNT = 2
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V20_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV20,
        contract: HostContractV20,
        *,
        controller_factory: ControllerFactoryV20 | None = None,
        **v19_options: Any,
    ) -> None:
        if (
            type(flags) is not ActivationFlagsV20
            or type(contract) is not HostContractV20
            or controller_factory is not None and not callable(controller_factory)
        ):
            raise ActivationV20Error("exact V20 activation bindings are required")
        self.flags = flags
        self.contract = contract
        self._base = v19.OnyxLiveActivationV19(flags.base, contract.base, **v19_options)
        self._controller_factory = controller_factory
        self._installed = False
        self._original_init: object | None = None
        self._owned_init: object | None = None
        self._wiring: Phase6LiveWiringV1 | None = None
        self._wiring_original_init: object | None = None
        self._protected: tuple[object, ...] | None = None
        self._controllers: list[AdvancedOperationsControllerV1] = []
        self._instances: list[object] = []
        self._callbacks: list[_CallbackBindingV20] = []

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    @property
    def advanced_operations_capability(self) -> str:
        return "available_lazy_zero_polling" if self._installed else "inactive"

    def _phase6_wiring(self) -> Phase6LiveWiringV1:
        cursor: object | None = self._base
        for _ in range(20):
            if cursor is None:
                break
            for name in ("wiring_controller", "_wiring_controller"):
                try:
                    candidate = getattr(cursor, name)
                except (AttributeError, RuntimeError):
                    continue
                if type(candidate) is Phase6LiveWiringV1:
                    return candidate
            cursor = getattr(cursor, "__dict__", {}).get("_base")
        raise ActivationV20Error("Phase 6 wiring authority is unavailable")

    def _create_controller(self, instance: object) -> AdvancedOperationsControllerV1:
        if self._controller_factory is None:
            return AdvancedOperationsControllerV1(
                instance, owner_authority=_deny_owner_authority
            )
        result = self._controller_factory(instance)
        if type(result) is not AdvancedOperationsControllerV1:
            raise ActivationV20Error("V20 controller factory returned drift")
        return result

    @staticmethod
    def _owned_callbacks(
        controller: AdvancedOperationsControllerV1,
    ) -> tuple[tuple[str, object], ...]:
        return (
            ("on_advanced_status", controller.ui_status),
            ("on_advanced_attention", controller.attention),
        )

    def initialize_host(self, instance: object) -> None:
        global _ACTIVE_HOST
        if not self._installed:
            raise ActivationV20Error("V20 activation is not installed")
        with _ACTIVE_LOCK:
            if _ACTIVE_HOST is not None:
                raise ActivationV20Error("another V20 host owns advanced operations")
            _ACTIVE_HOST = (self, instance)
        controller: AdvancedOperationsControllerV1 | None = None
        try:
            if hasattr(instance, HOST_CONTROLLER):
                raise ActivationV20Error("advanced operations controller already exists")
            controller = self._create_controller(instance)
            setattr(instance, HOST_CONTROLLER, controller)
            ui = getattr(instance, "ui", None)
            if ui is None:
                raise ActivationV20Error("trusted advanced operations UI is unavailable")
            previous = tuple((name, getattr(ui, name, _MISSING)) for name in UI_CALLBACKS)
            owned = self._owned_callbacks(controller)
            mutated: list[tuple[str, object]] = []
            try:
                for name, callback in owned:
                    setattr(ui, name, callback)
                    mutated.append((name, callback))
                    if getattr(ui, name, _MISSING) is not callback:
                        raise ActivationV20Error("trusted V20 callback did not bind exactly")
            except BaseException:
                prior = dict(previous)
                for name, callback in reversed(mutated):
                    if getattr(ui, name, _MISSING) is not callback:
                        continue
                    if prior[name] is _MISSING:
                        delattr(ui, name)
                    else:
                        setattr(ui, name, prior[name])
                raise
            self._controllers.append(controller)
            self._instances.append(instance)
            self._callbacks.append(_CallbackBindingV20(instance, ui, previous, owned))
            if os.environ.get(NATIVE_WORKSPACE_EVENTS_FLAG) == "true":
                # Host construction precedes the first Phase 6 live session.
                # Arm the feature here and let the trusted HUD callback create
                # the QFileSystemWatcher later on the Qt main thread.
                controller.request_native_workspace_events()
        except BaseException:
            if controller is not None:
                controller.close()
            if hasattr(instance, HOST_CONTROLLER):
                delattr(instance, HOST_CONTROLLER)
            with _ACTIVE_LOCK:
                if _ACTIVE_HOST == (self, instance):
                    _ACTIVE_HOST = None
            raise

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not 1 <= fail_after <= self.TOTAL_SEAM_COUNT:
            raise ActivationV20Error("seam failpoint is outside V20 installation")
        base_failpoint = (
            fail_after
            if fail_after is not None and fail_after <= self.BASE_SEAM_COUNT
            else None
        )
        environment = dict(os.environ)
        os.environ.clear()
        os.environ.update(restore_v19_environment(environment))
        try:
            self._base.install(fail_after=base_failpoint)
        finally:
            os.environ.clear()
            os.environ.update(environment)
        if base_failpoint is not None:
            return
        host = self.contract.onyx_live
        original_init = getattr(host, "__init__")
        protected = tuple(getattr(host, name) for name in _PROTECTED_SEAMS)
        activation = self

        def host_init(instance: object, *args: object, **kwargs: object) -> None:
            original_init(instance, *args, **kwargs)
            activation.initialize_host(instance)

        try:
            wiring = self._phase6_wiring()
            with wiring._lock:
                wiring_original_init = wiring._installed_values.get("__init__")
                if (
                    wiring._installed is not True
                    or wiring_original_init is not original_init
                ):
                    raise ActivationV20Error(
                        "Phase 6 constructor authority diverged"
                    )
                setattr(host, "__init__", host_init)
                wiring._installed_values["__init__"] = host_init
            self._original_init = original_init
            self._owned_init = host_init
            self._wiring = wiring
            self._wiring_original_init = wiring_original_init
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV20Error("injected V20 constructor failure")
            setattr(host, HOST_MARKER, self)
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV20Error("injected V20 marker failure")
            if protected != tuple(getattr(host, name) for name in _PROTECTED_SEAMS):
                raise ActivationV20Error("V20 altered a protected host seam")
            self._protected = protected
            self._installed = True
        except BaseException:
            self.rollback_all()
            raise

    def instantiate_live(self, ui: object) -> object:
        if not self._installed:
            raise ActivationV20Error("V20 activation is not installed")
        instance = self._base.instantiate_live(ui)
        if type(getattr(instance, HOST_CONTROLLER, None)) is not AdvancedOperationsControllerV1:
            raise ActivationV20Error("advanced operations did not reach live host")
        return instance

    def rollback_to_v19(self) -> None:
        global _ACTIVE_HOST
        errors: list[BaseException] = []
        for binding in reversed(self._callbacks):
            prior = dict(binding.previous)
            for name, callback in reversed(binding.owned):
                try:
                    if getattr(binding.ui, name, _MISSING) is not callback:
                        continue
                    if prior[name] is _MISSING:
                        delattr(binding.ui, name)
                    else:
                        setattr(binding.ui, name, prior[name])
                except BaseException as exc:
                    errors.append(exc)
        self._callbacks.clear()
        for controller in reversed(self._controllers):
            try:
                controller.close()
            except BaseException as exc:
                errors.append(exc)
        self._controllers.clear()
        for instance in tuple(self._instances):
            try:
                if type(getattr(instance, HOST_CONTROLLER, None)) is AdvancedOperationsControllerV1:
                    delattr(instance, HOST_CONTROLLER)
            except BaseException as exc:
                errors.append(exc)
        self._instances.clear()
        host = self.contract.onyx_live
        if self._owned_init is not None:
            try:
                wiring = self._wiring
                if wiring is None:
                    raise ActivationV20Error(
                        "V20 constructor rollback authority is missing"
                    )
                with wiring._lock:
                    if (
                        getattr(host, "__init__") is not self._owned_init
                        or wiring._installed_values.get("__init__")
                        is not self._owned_init
                    ):
                        raise ActivationV20Error(
                            "V20 constructor rollback drift"
                        )
                    setattr(host, "__init__", self._original_init)
                    wiring._installed_values["__init__"] = (
                        self._wiring_original_init
                    )
            except BaseException as exc:
                errors.append(exc)
        marker = getattr(host, HOST_MARKER, None)
        if marker is self:
            delattr(host, HOST_MARKER)
        elif marker is not None:
            errors.append(ActivationV20Error("V20 marker rollback drift"))
        if self._protected is not None and self._protected != tuple(
            getattr(host, name) for name in _PROTECTED_SEAMS
        ):
            errors.append(ActivationV20Error("V20 protected seam rollback drift"))
        if getattr(self.contract.module, "_onyx_live_activation_v20", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v20")
        with _ACTIVE_LOCK:
            if _ACTIVE_HOST is not None and _ACTIVE_HOST[0] is self:
                _ACTIVE_HOST = None
        self._original_init = None
        self._owned_init = None
        self._wiring = None
        self._wiring_original_init = None
        self._protected = None
        self._installed = False
        if errors:
            raise ActivationV20Error("V20 rollback completed with errors") from errors[0]

    def rollback_all(self) -> None:
        errors: list[BaseException] = []
        try:
            self.rollback_to_v19()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._base.rollback_all()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise ActivationV20Error("V20 full rollback completed with errors") from errors[0]


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
    **v19_options: Any,
) -> OnyxLiveActivationV20:
    source = os.environ if environ is None else environ
    options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    controller = OnyxLiveActivationV20(
        ActivationFlagsV20.from_canonical_environ(source, **options),
        preflight_host(
            module,
            source,
            portable_bindings=portable_bindings,
            **options,
        ),
        portable_bindings=portable_bindings,
        **v19_options,
    )
    controller.install()
    module._onyx_live_activation_v20 = controller
    return controller


__all__ = [
    "ActivationFlagsV20",
    "ActivationV20Error",
    "CONTROL_FLAGS",
    "FEATURE_FLAG",
    "HOST_MARKER",
    "HostContractV20",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV20",
    "UI_CALLBACKS",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v19_environment",
]
