"""Default-off V14 activation adding authorized read-only DayOps over V13."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import dayops_live_integration_v1 as dayops
from core import onyx_live_activation_v13 as v13
from core import permission_broker


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V14"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V14"
DAYOPS_FLAG: Final = dayops.FEATURE_FLAG
BOOTSTRAP_RELATIVE: Final = Path("scripts/bootstrap_onyx_live_v14.pyw")
CANONICAL_LAUNCHER_RELATIVE: Final = Path("scripts/launch_onyx_live_v14.pyw")
V13_FROZEN_ROOTS: Final = (
    (
        Path("core/onyx_live_activation_v13.py"),
        "f312d95c92ac5bbe89970cc528e7e8004140dc313d7b02a6150774e014c3f41f",
    ),
    (
        Path("scripts/bootstrap_onyx_live_v13.pyw"),
        "cc85021286b2aa1b84530eedb2883d1afeabc27e4417f54b4decf2e29d16020c",
    ),
    (
        Path("scripts/launch_onyx_live_v13.pyw"),
        "daa0ded847191d296c9e671a1afec8b6e81b8845e3657c287b6a6851d4563143",
    ),
)
VERSION_CONTROL_FLAGS = tuple(
    name
    for version in range(1, 15)
    for name in (
        f"ONYX_LIVE_ACTIVATION_V{version}",
        f"ONYX_LIVE_ROLLBACK_V{version}",
    )
)
CONTROL_FLAGS = (*VERSION_CONTROL_FLAGS, DAYOPS_FLAG, *v13.CONTROL_FLAGS)


class ActivationV14Error(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_v13_roots(project: Path) -> None:
    root = project.resolve()
    for relative, expected in V13_FROZEN_ROOTS:
        path = root / relative
        if path.is_symlink() or not path.is_file() or _sha256(path) != expected:
            raise ActivationV14Error(f"V13 predecessor drift: {relative}")
    for relative in (BOOTSTRAP_RELATIVE, CANONICAL_LAUNCHER_RELATIVE):
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ActivationV14Error(f"V14 runtime file unavailable: {relative}")


@dataclass(frozen=True, slots=True)
class ActivationFlagsV14:
    master: bool
    dayops: bool
    base: v13.ActivationFlagsV13

    def __post_init__(self) -> None:
        if (
            type(self.master) is not bool
            or type(self.dayops) is not bool
            or not self.master
            or not self.dayops
            or type(self.base) is not v13.ActivationFlagsV13
        ):
            raise ActivationV14Error("complete exact V14 flags are required")

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ActivationFlagsV14":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV14Error("rollback is not an active V14 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(DAYOPS_FLAG) != "true":
            raise ActivationV14Error("activation environment is not canonical V14")
        try:
            base = v13.ActivationFlagsV13.from_canonical_environ(source)
        except v13.ActivationV13Error as exc:
            raise ActivationV14Error("V13 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment() -> dict[str, str]:
    result = v13.exact_activation_environment()
    result[LIVE_MASTER_FLAG] = "1"
    result[DAYOPS_FLAG] = "true"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v13_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(DAYOPS_FLAG, None)
    result.update(v13.exact_activation_environment())
    return result


@dataclass(frozen=True, slots=True)
class HostContractV14:
    module: ModuleType
    onyx_live: type
    project: Path
    base: v13.HostContractV13


@dataclass(frozen=True, slots=True)
class _RollbackAuthorityV14:
    controller: object
    host_type: type
    declaration: dict[str, object]
    policy_existed: bool
    policy_value: str | None
    controller_attr_existed: bool
    controller_attr_value: object


_ROLLBACK_AUTHORITIES: dict[int, _RollbackAuthorityV14] = {}


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
) -> HostContractV14:
    source = os.environ if environ is None else environ
    ActivationFlagsV14.from_canonical_environ(source)
    base = v13.preflight_host(module, restore_v13_environment(source))
    _verify_v13_roots(base.project)
    onyx_live = getattr(module, "OnyxLive", None)
    declarations = getattr(module, "TOOL_DECLARATIONS", None)
    if (
        not isinstance(onyx_live, type)
        or not callable(getattr(onyx_live, "_execute_tool", None))
        or not isinstance(declarations, list)
        or not callable(getattr(module, "authorize_model_tool", None))
        or not callable(getattr(module, "append_tool_audit", None))
        or not callable(getattr(module, "set_audit_trace_id", None))
        or not callable(getattr(module, "reset_audit_trace_id", None))
        or not callable(getattr(module, "mark_audit_unhealthy", None))
    ):
        raise ActivationV14Error("V14 host contract is unavailable")
    if hasattr(onyx_live, "_dayops_controller_v14"):
        raise ActivationV14Error("DayOps controller binding already exists")
    if any(
        isinstance(item, dict) and item.get("name") == dayops.TOOL_NAME
        for item in declarations
    ):
        raise ActivationV14Error("DayOps declaration already exists")
    return HostContractV14(module, onyx_live, base.project, base)


def verify_activation_prerequisites(
    project: Path,
    environ: Mapping[str, str] | None = None,
) -> None:
    source = os.environ if environ is None else environ
    ActivationFlagsV14.from_canonical_environ(source)
    v13.verify_activation_prerequisites(project, restore_v13_environment(source))
    _verify_v13_roots(project)


class OnyxLiveActivationV14:
    """Exact V13 plus one authorized, audited, read-only DayOps dispatch."""

    BASE_SEAM_COUNT = v13.OnyxLiveActivationV13.TOTAL_SEAM_COUNT
    V14_SEAM_COUNT = 3
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V14_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV14,
        contract: HostContractV14,
        *,
        dayops_factory: dayops.AdapterFactoryV1 | None = None,
        **v13_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV14 or type(contract) is not HostContractV14:
            raise ActivationV14Error("exact V14 flags and host contract are required")
        self.flags = flags
        self.contract = contract
        self._base = v13.OnyxLiveActivationV13(
            flags.base,
            contract.base,
            **v13_options,
        )
        integration = dayops.create_dayops_live_integration_v1(
            gate=dayops.DayOpsFeatureGateV1(True),
            adapter_factory=dayops_factory,
        )
        if type(integration) is not dayops.DayOpsLiveIntegrationV1:
            raise ActivationV14Error("DayOps controller is unavailable")
        self._dayops = integration
        self._installed = False

    @property
    def state(self) -> object:
        return self._base.state

    @property
    def dayops_controller(self) -> dayops.DayOpsLiveIntegrationV1:
        return self._dayops

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not (1 <= fail_after <= self.TOTAL_SEAM_COUNT):
            raise ActivationV14Error("seam failpoint is outside V14 installation")
        base_failpoint = (
            fail_after if fail_after and fail_after <= self.BASE_SEAM_COUNT else None
        )
        self._base.install(fail_after=base_failpoint)
        if base_failpoint is not None:
            return
        declaration = dayops.tool_declaration_v1()
        declarations = self.contract.module.TOOL_DECLARATIONS
        policy_existed = dayops.TOOL_NAME in permission_broker.MODEL_TOOL_POLICIES
        policy_value = permission_broker.MODEL_TOOL_POLICIES.get(dayops.TOOL_NAME)
        controller_attr_existed = hasattr(
            self.contract.onyx_live,
            "_dayops_controller_v14",
        )
        controller_attr_value = getattr(
            self.contract.onyx_live,
            "_dayops_controller_v14",
            None,
        )
        authority = _RollbackAuthorityV14(
            controller=self,
            host_type=self.contract.onyx_live,
            declaration=declaration,
            policy_existed=policy_existed,
            policy_value=policy_value,
            controller_attr_existed=controller_attr_existed,
            controller_attr_value=controller_attr_value,
        )
        _ROLLBACK_AUTHORITIES[id(self)] = authority
        try:
            declarations.append(declaration)
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV14Error("injected V14 declaration seam failure")

            if policy_existed and policy_value != "always_confirm":
                raise ActivationV14Error("DayOps permission policy drift")
            permission_broker.MODEL_TOOL_POLICIES[dayops.TOOL_NAME] = "always_confirm"
            if fail_after == self.BASE_SEAM_COUNT + 2:
                raise ActivationV14Error("injected V14 policy seam failure")

            if controller_attr_existed:
                raise ActivationV14Error("DayOps controller binding drift")
            self.contract.onyx_live._dayops_controller_v14 = self._dayops
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV14Error("injected V14 controller seam failure")
            self._installed = True
        except Exception:
            self.rollback_installation()
            raise

    def rollback_installation(self) -> None:
        errors: list[Exception] = []
        authority = _ROLLBACK_AUTHORITIES.pop(id(self), None)
        if authority is not None and (
            type(authority) is not _RollbackAuthorityV14
            or authority.controller is not self
            or authority.host_type is not self.contract.onyx_live
        ):
            errors.append(ActivationV14Error("V14 rollback authority drift denied"))
            authority = None
        if authority is not None:
            if authority.controller_attr_existed:
                authority.host_type._dayops_controller_v14 = (
                    authority.controller_attr_value
                )
            else:
                try:
                    delattr(authority.host_type, "_dayops_controller_v14")
                except AttributeError:
                    pass
            declarations = self.contract.module.TOOL_DECLARATIONS
            declarations[:] = [
                item
                for item in declarations
                if item is not authority.declaration
            ]
            if authority.policy_existed:
                permission_broker.MODEL_TOOL_POLICIES[dayops.TOOL_NAME] = (
                    authority.policy_value
                )
            else:
                permission_broker.MODEL_TOOL_POLICIES.pop(dayops.TOOL_NAME, None)
        elif self._installed:
            errors.append(ActivationV14Error("V14 rollback authority is unavailable"))
        self._installed = False
        restored = restore_v13_environment(os.environ)
        os.environ.clear()
        os.environ.update(restored)
        if getattr(self.contract.module, "_onyx_live_activation_v14", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v14")
        if errors:
            raise ActivationV14Error(
                "V14 rollback completed with authority error"
            ) from errors[0]

    def rollback_all(self) -> None:
        self.rollback_installation()
        self._base.rollback_all()


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    dayops_factory: dayops.AdapterFactoryV1 | None = None,
) -> OnyxLiveActivationV14:
    source = os.environ if environ is None else environ
    controller = OnyxLiveActivationV14(
        ActivationFlagsV14.from_canonical_environ(source),
        preflight_host(module, source),
        dayops_factory=dayops_factory,
    )
    controller.install()
    module._onyx_live_activation_v14 = controller
    return controller


__all__ = [
    "ActivationFlagsV14",
    "ActivationV14Error",
    "BOOTSTRAP_RELATIVE",
    "CANONICAL_LAUNCHER_RELATIVE",
    "CONTROL_FLAGS",
    "DAYOPS_FLAG",
    "HostContractV14",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV14",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v13_environment",
    "verify_activation_prerequisites",
]
