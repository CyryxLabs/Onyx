"""Additive persistent DayOps V19 activation over exact V18.1."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import onyx_live_activation_v18 as v18
from core.dayops_connection_v19 import DayOpsConnectionControllerV19
from core.dayops_graph_factory_v19 import PersistentDayOpsGraphFactoryV19
from core.dayops_identity_provisioning_v19 import DayOpsIdentityProvisionerV19
from core.dayops_live_integration_v1 import DayOpsConfigurationRequiredV1
from core.dayops_profile_v19 import DayOpsProfileStoreV19
from core.governance_nucleus_v1 import GovernanceIdentityV1, GovernanceNucleusV1
from core.onyx_hud_current_acceptance_v19 import (
    CurrentHudAcceptanceV19Error,
    verify_current_hud_acceptance,
)
from core.portable_host_capability_v1 import (
    PortableHostBindingsV1,
    PortableHostCapabilityV1Error,
    require_portable_host_bindings_v1,
)


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V19"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V19"
FEATURE_FLAG: Final = "ONYX_DAYOPS_PERSISTENT_V19"
CONTROL_FLAGS: Final = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    FEATURE_FLAG,
    *v18.CONTROL_FLAGS,
)
HOST_MARKER: Final = "_dayops_activation_v19"
HOST_CONTROLLER: Final = "_dayops_connection_controller_v19"
UI_CALLBACKS: Final = (
    "on_dayops_status",
    "on_dayops_connect",
    "on_dayops_sign_in",
    "on_dayops_disconnect",
    "on_dayops_today_brief",
)
_MISSING = object()
_HOST_LOCK = threading.RLock()
_ACTIVE_HOST: tuple["OnyxLiveActivationV19", object] | None = None


class ActivationV19Error(RuntimeError):
    pass


class ActivationV19PlatformDenied(ActivationV19Error):
    pass


def _require_current_host_boundary_v19(
    portable_bindings: object | None,
    *,
    stage: str,
) -> None:
    if os.name == "nt":
        if portable_bindings is not None:
            raise ActivationV19PlatformDenied("portable bindings are invalid on Windows")
        return
    try:
        bindings = require_portable_host_bindings_v1(portable_bindings, stage=stage)
    except PortableHostCapabilityV1Error as exc:
        raise ActivationV19PlatformDenied(
            "dayops_v19_host_boundary_denied"
        ) from exc
    if bindings.governance_descriptor_io is not True:
        raise ActivationV19PlatformDenied(
            "dayops_v19_v16_descriptor_governance_unavailable"
        )


class _IdentityBoundFactoryProxyV19:
    """Late-bound callable supplied to the accepted V14 model-tool seam."""

    __slots__ = ("_factory", "_lock")

    def __init__(self) -> None:
        self._factory: PersistentDayOpsGraphFactoryV19 | None = None
        self._lock = threading.RLock()

    def bind(self, factory: PersistentDayOpsGraphFactoryV19) -> None:
        if type(factory) is not PersistentDayOpsGraphFactoryV19:
            raise ActivationV19Error("exact persistent DayOps factory is required")
        with self._lock:
            if self._factory is not None:
                raise ActivationV19Error("persistent DayOps factory already bound")
            self._factory = factory

    def unbind(self, factory: PersistentDayOpsGraphFactoryV19) -> None:
        with self._lock:
            if self._factory is factory:
                self._factory = None

    def __call__(self, now_ms: int):
        with self._lock:
            factory = self._factory
        if factory is None:
            raise DayOpsConfigurationRequiredV1(
                "DayOps persistent identity is not initialized"
            )
        return factory(now_ms)

    def close(self) -> None:
        with self._lock:
            factory = self._factory
        if factory is not None:
            factory.close()


@dataclass(frozen=True, slots=True)
class ActivationFlagsV19:
    master: bool
    dayops: bool
    base: v18.ActivationFlagsV18

    def __post_init__(self) -> None:
        if (
            self.master is not True
            or self.dayops is not True
            or type(self.base) is not v18.ActivationFlagsV18
        ):
            raise ActivationV19Error("complete exact V19 flags are required")

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_endpoint_factory: object | None = None,
    ) -> "ActivationFlagsV19":
        source = os.environ if environ is None else environ
        endpoint_options = (
            {}
            if runtime_endpoint_factory is None
            else {"runtime_endpoint_factory": runtime_endpoint_factory}
        )
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV19Error("rollback is not an active V19 configuration")
        if (
            source.get(LIVE_MASTER_FLAG) != "1"
            or source.get(FEATURE_FLAG) != "true"
        ):
            raise ActivationV19Error("activation environment is not canonical V19")
        try:
            base = v18.ActivationFlagsV18.from_canonical_environ(
                restore_v18_environment(source),
                **endpoint_options,
            )
        except v18.ActivationV18Error as exc:
            raise ActivationV19Error("V18 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment(
    workspace_roots: Sequence[str | os.PathLike[str]],
    **v18_options: Any,
) -> dict[str, str]:
    result = v18.exact_activation_environment(workspace_roots, **v18_options)
    result[LIVE_MASTER_FLAG] = "1"
    result[FEATURE_FLAG] = "true"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v18_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(FEATURE_FLAG, None)
    return result


@dataclass(frozen=True, slots=True)
class HostContractV19:
    module: ModuleType
    onyx_live: type
    project: Path
    base: v18.HostContractV18


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    platform_guard: object | None = None,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
) -> HostContractV19:
    if os.name != "nt":
        if platform_guard is not None:
            raise ActivationV19PlatformDenied(
                "arbitrary portable host bindings are denied"
            )
        try:
            sealed = require_portable_host_bindings_v1(
                portable_bindings,
                stage="dayops_preflight",
            )
        except PortableHostCapabilityV1Error as exc:
            raise ActivationV19PlatformDenied(
                "dayops_v19_host_boundary_denied"
            ) from exc
        if runtime_endpoint_factory not in (None, sealed.runtime_endpoint_factory):
            raise ActivationV19PlatformDenied(
                "arbitrary portable runtime endpoint factory is denied"
            )
        runtime_endpoint_factory = sealed.runtime_endpoint_factory
    _require_current_host_boundary_v19(
        portable_bindings,
        stage="dayops_preflight",
    )
    source = os.environ if environ is None else environ
    endpoint_options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    ActivationFlagsV19.from_canonical_environ(
        source,
        **endpoint_options,
    )
    try:
        base = v18.preflight_host(
            module,
            restore_v18_environment(source),
            portable_bindings=portable_bindings,
            **endpoint_options,
        )
    except v18.ActivationV18Error as exc:
        raise ActivationV19Error("V18 host contract is unavailable") from exc
    try:
        verify_current_hud_acceptance(base.project)
    except CurrentHudAcceptanceV19Error as exc:
        raise ActivationV19Error("current V19 HUD acceptance failed") from exc
    host = getattr(module, "OnyxLive", None)
    if not isinstance(host, type) or hasattr(host, HOST_MARKER):
        raise ActivationV19Error("V19 host contract is unavailable")
    return HostContractV19(module, host, base.project, base)


@dataclass(frozen=True, slots=True)
class _CallbackBindingV19:
    instance: object
    ui: object
    previous: tuple[tuple[str, object], ...]
    owned: tuple[tuple[str, object], ...]


ComponentFactoryV19 = Callable[
    [object, GovernanceIdentityV1],
    tuple[DayOpsConnectionControllerV19, PersistentDayOpsGraphFactoryV19],
]


class OnyxLiveActivationV19:
    BASE_SEAM_COUNT = v18.OnyxLiveActivationV18.TOTAL_SEAM_COUNT
    V19_SEAM_COUNT = 2
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V19_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV19,
        contract: HostContractV19,
        *,
        component_factory: ComponentFactoryV19 | None = None,
        **v18_options: Any,
    ) -> None:
        if "executable_sandbox_factory" in v18_options:
            raise ActivationV19Error(
                "arbitrary executable sandbox factory is denied"
            )
        if (
            type(flags) is not ActivationFlagsV19
            or type(contract) is not HostContractV19
            or component_factory is not None
            and not callable(component_factory)
            or "dayops_factory" in v18_options
        ):
            raise ActivationV19Error("exact V19 activation bindings are required")
        self.flags = flags
        self.contract = contract
        self._proxy = _IdentityBoundFactoryProxyV19()
        self._base = v18.OnyxLiveActivationV18(
            flags.base,
            contract.base,
            dayops_factory=self._proxy,
            **v18_options,
        )
        self._component_factory = component_factory
        self._installed = False
        self._controllers: list[DayOpsConnectionControllerV19] = []
        self._factories: list[PersistentDayOpsGraphFactoryV19] = []
        self._instances: list[object] = []
        self._callbacks: list[_CallbackBindingV19] = []

    @property
    def dayops_capability(self) -> str:
        return "available_read_only" if self._installed else "inactive"

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    def _components(
        self, instance: object, identity: GovernanceIdentityV1
    ) -> tuple[DayOpsConnectionControllerV19, PersistentDayOpsGraphFactoryV19]:
        if self._component_factory is not None:
            result = self._component_factory(instance, identity)
            if (
                type(result) is not tuple
                or len(result) != 2
                or type(result[0]) is not DayOpsConnectionControllerV19
                or type(result[1]) is not PersistentDayOpsGraphFactoryV19
            ):
                raise ActivationV19Error("V19 component factory returned drift")
            return result
        profile_store = DayOpsProfileStoreV19(identity)
        factory = PersistentDayOpsGraphFactoryV19(
            identity,
            profile_store,
            graph_factory_options={"project_root": self.contract.project},
        )
        provisioner = DayOpsIdentityProvisionerV19(
            identity,
            profile_store,
            project_root=self.contract.project,
        )
        controller = DayOpsConnectionControllerV19(
            identity,
            profile_store,
            provisioner,
            factory,
        )
        return controller, factory

    @staticmethod
    def _owned_callbacks(
        controller: DayOpsConnectionControllerV19,
    ) -> tuple[tuple[str, object], ...]:
        return (
            ("on_dayops_status", controller.status),
            ("on_dayops_connect", controller.connect),
            ("on_dayops_sign_in", controller.sign_in),
            ("on_dayops_disconnect", controller.disconnect),
            ("on_dayops_today_brief", controller.today_brief),
        )

    def initialize_host(self, instance: object) -> None:
        global _ACTIVE_HOST
        if not self._installed:
            raise ActivationV19Error("V19 activation is not installed")
        with _HOST_LOCK:
            if _ACTIVE_HOST is not None:
                raise ActivationV19Error("another V19 host owns DayOps")
            _ACTIVE_HOST = (self, instance)
        controller: DayOpsConnectionControllerV19 | None = None
        factory: PersistentDayOpsGraphFactoryV19 | None = None
        try:
            if hasattr(instance, HOST_CONTROLLER):
                raise ActivationV19Error("V19 DayOps controller already exists")
            nucleus = getattr(instance, "_governance_nucleus_v1", None)
            if type(nucleus) is not GovernanceNucleusV1:
                raise ActivationV19Error("Governance V16 must precede DayOps V19")
            controller, factory = self._components(instance, nucleus.identity)
            self._proxy.bind(factory)
            setattr(instance, HOST_CONTROLLER, controller)
            ui = getattr(instance, "ui", None)
            if ui is None:
                raise ActivationV19Error("trusted DayOps UI is unavailable")
            previous = tuple(
                (name, getattr(ui, name, _MISSING)) for name in UI_CALLBACKS
            )
            owned = self._owned_callbacks(controller)
            mutated: list[tuple[str, object]] = []
            try:
                for name, callback in owned:
                    setattr(ui, name, callback)
                    mutated.append((name, callback))
                    if getattr(ui, name, _MISSING) is not callback:
                        raise ActivationV19Error(
                            "trusted DayOps callback did not bind exactly"
                        )
            except BaseException as bind_error:
                prior = dict(previous)
                for name, callback in reversed(mutated):
                    if getattr(ui, name, _MISSING) is not callback:
                        continue
                    try:
                        if prior[name] is _MISSING:
                            delattr(ui, name)
                        else:
                            setattr(ui, name, prior[name])
                    except BaseException as restore_error:
                        raise ActivationV19Error(
                            "trusted DayOps callback restore failed"
                        ) from restore_error
                raise bind_error
            self._controllers.append(controller)
            self._factories.append(factory)
            self._instances.append(instance)
            self._callbacks.append(
                _CallbackBindingV19(instance, ui, previous, owned)
            )
        except BaseException:
            if factory is not None:
                self._proxy.unbind(factory)
            if controller is not None:
                controller.close()
            if hasattr(instance, HOST_CONTROLLER):
                delattr(instance, HOST_CONTROLLER)
            with _HOST_LOCK:
                if _ACTIVE_HOST == (self, instance):
                    _ACTIVE_HOST = None
            raise

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not 1 <= fail_after <= self.TOTAL_SEAM_COUNT:
            raise ActivationV19Error("seam failpoint is outside V19 installation")
        base_failpoint = (
            fail_after
            if fail_after is not None and fail_after <= self.BASE_SEAM_COUNT
            else None
        )
        environment = dict(os.environ)
        os.environ.clear()
        os.environ.update(restore_v18_environment(environment))
        try:
            self._base.install(fail_after=base_failpoint)
        finally:
            os.environ.clear()
            os.environ.update(environment)
        if base_failpoint is not None:
            return
        try:
            if hasattr(self.contract.onyx_live, HOST_MARKER):
                raise ActivationV19Error("V19 host marker already exists")
            setattr(self.contract.onyx_live, HOST_MARKER, self)
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV19Error("injected V19 marker failure")
            self._installed = True
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV19Error("injected V19 activation failure")
        except BaseException:
            self.rollback_all()
            raise

    def instantiate_live(self, ui: object) -> object:
        if not self._installed:
            raise ActivationV19Error("V19 activation is not installed")
        instance = self._base.instantiate_live(ui)
        if type(getattr(instance, HOST_CONTROLLER, None)) is not DayOpsConnectionControllerV19:
            raise ActivationV19Error("persistent DayOps did not reach live host")
        return instance

    def rollback_to_v18(self) -> None:
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
        for instance in tuple(self._instances):
            try:
                if type(getattr(instance, HOST_CONTROLLER, None)) is DayOpsConnectionControllerV19:
                    delattr(instance, HOST_CONTROLLER)
            except BaseException as exc:
                errors.append(exc)
        self._instances.clear()
        for controller, factory in zip(self._controllers, self._factories, strict=False):
            self._proxy.unbind(factory)
            try:
                controller.close()
            except BaseException as exc:
                errors.append(exc)
        self._controllers.clear()
        self._factories.clear()
        with _HOST_LOCK:
            if _ACTIVE_HOST is not None and _ACTIVE_HOST[0] is self:
                _ACTIVE_HOST = None
        marker = getattr(self.contract.onyx_live, HOST_MARKER, None)
        if marker is self:
            delattr(self.contract.onyx_live, HOST_MARKER)
        elif marker is not None:
            errors.append(ActivationV19Error("V19 rollback marker drift"))
        if getattr(self.contract.module, "_onyx_live_activation_v19", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v19")
        self._installed = False
        if errors:
            raise ActivationV19Error("V19 rollback completed with errors") from errors[0]

    def rollback_all(self) -> None:
        errors: list[BaseException] = []
        try:
            self.rollback_to_v18()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._base.rollback_to_v17()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise ActivationV19Error("V19 full rollback completed with errors") from errors[0]


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    platform_guard: object | None = None,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
    **v18_options: Any,
) -> OnyxLiveActivationV19:
    if "executable_sandbox_factory" in v18_options:
        raise ActivationV19Error("arbitrary executable sandbox factory is denied")
    source = os.environ if environ is None else environ
    if os.name != "nt":
        if platform_guard is not None:
            raise ActivationV19PlatformDenied(
                "arbitrary portable host bindings are denied"
            )
        try:
            sealed = require_portable_host_bindings_v1(
                portable_bindings,
                stage="dayops_preflight",
            )
        except PortableHostCapabilityV1Error as exc:
            raise ActivationV19PlatformDenied(
                "dayops_v19_host_boundary_denied"
            ) from exc
        if runtime_endpoint_factory not in (None, sealed.runtime_endpoint_factory):
            raise ActivationV19PlatformDenied(
                "arbitrary portable runtime endpoint factory is denied"
            )
        runtime_endpoint_factory = sealed.runtime_endpoint_factory
    endpoint_options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    controller = OnyxLiveActivationV19(
        ActivationFlagsV19.from_canonical_environ(
            source,
            **endpoint_options,
        ),
        preflight_host(
            module,
            source,
            portable_bindings=portable_bindings,
            **endpoint_options,
        ),
        portable_bindings=portable_bindings,
        **v18_options,
    )
    controller.install()
    module._onyx_live_activation_v19 = controller
    return controller


__all__ = [
    "ActivationFlagsV19",
    "ActivationV19Error",
    "ActivationV19PlatformDenied",
    "CONTROL_FLAGS",
    "FEATURE_FLAG",
    "HOST_CONTROLLER",
    "HOST_MARKER",
    "HostContractV19",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV19",
    "UI_CALLBACKS",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v18_environment",
]
