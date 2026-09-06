"""Onyx Live Activation V8: canonical desktop bootstrap shortcut.

V8 composes the frozen V7 candidate and adds one Windows source-checkout UI
seam. Packaged, macOS, and Linux shortcut behavior remains delegated to the
frozen implementation.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from core import onyx_live_activation_v7 as v7


LIVE_MASTER_FLAG = "ONYX_LIVE_ACTIVATION_V8"
LIVE_ROLLBACK_FLAG = "ONYX_LIVE_ROLLBACK_V8"
OWNER_PROFILE_FLAG = v7.OWNER_PROFILE_FLAG
HUD_FLAG = v7.HUD_FLAG
PHASE5_FLAGS = v7.PHASE5_FLAGS
CHILD_FLAGS = (OWNER_PROFILE_FLAG, HUD_FLAG, *PHASE5_FLAGS)
PHASE5_IDENTITY_FLAGS = v7.PHASE5_IDENTITY_FLAGS
PHASE5_IDENTITY_ALIASES = v7.PHASE5_IDENTITY_ALIASES
CANONICAL_PHASE5_IDENTITY = v7.CANONICAL_PHASE5_IDENTITY
CONTROL_FLAGS = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    *CHILD_FLAGS,
    *PHASE5_IDENTITY_FLAGS,
    *PHASE5_IDENTITY_ALIASES,
)

BOOTSTRAP_RELATIVE = Path("scripts") / "bootstrap_onyx_live_v8.pyw"
CANONICAL_LAUNCHER_RELATIVE = Path("scripts") / "launch_onyx_live_v8.pyw"
LEGACY_LAUNCHER_RELATIVE = Path("scripts") / "launch_onyx.pyw"


class ActivationV8Error(RuntimeError):
    """The V8 launch or shortcut contract was not exact."""


@dataclass(frozen=True, slots=True)
class ActivationFlagsV8:
    master: bool
    owner_profile: bool
    hud_v5: bool
    phase5: tuple[bool, ...]
    principal_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        if type(self.phase5) is not tuple or len(self.phase5) != len(PHASE5_FLAGS):
            raise ActivationV8Error("Phase 5 flag set is incomplete")
        booleans = (self.master, self.owner_profile, self.hud_v5, *self.phase5)
        if any(type(value) is not bool for value in booleans) or not all(booleans):
            raise ActivationV8Error("complete active V8 flags are required")
        observed = {
            v7.PHASE5_PRINCIPAL_ID: self.principal_id,
            v7.PHASE5_WORKSPACE_ID: self.workspace_id,
            v7.PHASE5_ACCOUNT_ID: self.account_id,
            v7.PHASE5_PROFILE_ID: self.profile_id,
        }
        if observed != CANONICAL_PHASE5_IDENTITY:
            raise ActivationV8Error("exact canonical Phase 5 identity is required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV8":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV8Error("rollback is not an active configuration")
        if any(name in source for name in PHASE5_IDENTITY_ALIASES):
            raise ActivationV8Error("Phase 5 identity aliases are forbidden")
        for name in (LIVE_MASTER_FLAG, *CHILD_FLAGS):
            if source.get(name) != "1":
                raise ActivationV8Error("activation environment is not canonical")
        for name, expected in CANONICAL_PHASE5_IDENTITY.items():
            if source.get(name) != expected:
                raise ActivationV8Error("Phase 5 identity environment is not canonical")
        return cls(
            True,
            True,
            True,
            (True,) * len(PHASE5_FLAGS),
            CANONICAL_PHASE5_IDENTITY[v7.PHASE5_PRINCIPAL_ID],
            CANONICAL_PHASE5_IDENTITY[v7.PHASE5_WORKSPACE_ID],
            CANONICAL_PHASE5_IDENTITY[v7.PHASE5_ACCOUNT_ID],
            CANONICAL_PHASE5_IDENTITY[v7.PHASE5_PROFILE_ID],
        )


def exact_activation_environment() -> dict[str, str]:
    result = v7.exact_activation_environment()
    result.pop(v7.LIVE_MASTER_FLAG, None)
    result[LIVE_MASTER_FLAG] = "1"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def _v7_activation_environment() -> dict[str, str]:
    return v7.exact_activation_environment()


@dataclass(frozen=True, slots=True)
class ShortcutSpecV8:
    link: str
    target: str
    arguments: str
    working_directory: str
    icon: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not str or not getattr(self, name):
                raise ActivationV8Error(
                    "shortcut fields must be non-empty exact strings"
                )
        argument = Path(self.arguments)
        if argument.name != BOOTSTRAP_RELATIVE.name:
            raise ActivationV8Error("shortcut must target the V8 bootstrap")
        if argument.name == LEGACY_LAUNCHER_RELATIVE.name:
            raise ActivationV8Error("legacy launcher is forbidden in V8 shortcut")


@dataclass(frozen=True, slots=True)
class HostContractV8:
    module: ModuleType
    ui_module: ModuleType
    main_window: type
    base: v7.HostContractV7


def preflight_host(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> HostContractV8:
    source = os.environ if environ is None else environ
    ActivationFlagsV8.from_canonical_environ(source)
    base = v7.preflight_host(module, _v7_activation_environment())
    ui_module = base.base.ui_module
    main_window = base.base.main_window
    namespace = getattr(main_window, "__dict__", {})
    for name in (
        "_create_desktop_shortcut",
        "_create_lnk_windows",
        "_desktop_path",
        "_build_onyx_icon",
    ):
        if name not in namespace and not hasattr(main_window, name):
            raise ActivationV8Error(f"required shortcut seam is absent: {name}")
    if not callable(getattr(ui_module, "is_frozen", None)):
        raise ActivationV8Error("frozen/package detector is unavailable")
    return HostContractV8(module, ui_module, main_window, base)


class OnyxLiveActivationV8:
    """One shortcut seam over the accepted default-off V7 candidate."""

    BASE_SEAM_COUNT = v7.OnyxLiveActivationV7.TOTAL_SEAM_COUNT
    V8_SEAM_COUNT = 1
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V8_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV8,
        contract: HostContractV8,
        **v7_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV8 or type(contract) is not HostContractV8:
            raise ActivationV8Error("exact V8 flags and host contract are required")
        self.flags = flags
        self.contract = contract
        self._base = v7.OnyxLiveActivationV7(
            v7.ActivationFlagsV7.from_canonical_environ(_v7_activation_environment()),
            contract.base,
            **v7_options,
        )
        self._shortcut_original: object | None = None

    @property
    def state(self) -> object:
        return self._base.state

    @property
    def failure_type(self) -> str | None:
        return self._base.failure_type

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    def _source_shortcut_spec(self, instance: object) -> ShortcutSpecV8:
        ui_module = self.contract.ui_module
        project_dir = Path(ui_module.__file__).resolve().parent
        desktop = instance._desktop_path("Windows")
        bootstrap = project_dir / BOOTSTRAP_RELATIVE
        legacy = project_dir / LEGACY_LAUNCHER_RELATIVE
        launcher = project_dir / CANONICAL_LAUNCHER_RELATIVE
        target = project_dir / ".venv" / "Scripts" / "pythonw.exe"
        icon = project_dir / "config" / "onyx.ico"
        if (
            not target.is_file()
            or not bootstrap.is_file()
            or not launcher.is_file()
            or bootstrap.resolve() == legacy.resolve()
            or launcher.resolve() == legacy.resolve()
        ):
            raise ActivationV8Error("canonical V8 shortcut entrypoint is unavailable")
        return ShortcutSpecV8(
            link=str(desktop / "Onyx.lnk"),
            target=str(target),
            arguments=str(bootstrap),
            working_directory=str(project_dir),
            icon=str(icon),
        )

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not (1 <= fail_after <= self.TOTAL_SEAM_COUNT):
            raise ActivationV8Error("seam failpoint is outside V8 installation")
        base_failpoint = (
            fail_after if fail_after and fail_after <= self.BASE_SEAM_COUNT else None
        )
        self._base.install(fail_after=base_failpoint)
        window_type = self.contract.main_window
        original = window_type._create_desktop_shortcut
        controller = self

        def create_desktop_shortcut(instance: object) -> None:
            ui_module = controller.contract.ui_module
            if ui_module.is_frozen() or platform.system() != "Windows":
                original(instance)
                return
            try:
                spec = controller._source_shortcut_spec(instance)
                icon_path = Path(spec.icon)
                if not icon_path.exists():
                    instance._build_onyx_icon(icon_path)
                instance._create_lnk_windows(
                    spec.link,
                    spec.target,
                    spec.arguments,
                    spec.working_directory,
                    spec.icon,
                )
                instance._log.append_log(
                    "SYS: Desktop shortcut created for Onyx Live V8."
                )
            except Exception as exc:
                instance._log.append_log(
                    f"ERR: Shortcut failed safely ({type(exc).__name__})."
                )

        try:
            window_type._create_desktop_shortcut = create_desktop_shortcut
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV8Error("injected V8 shortcut seam failure")
        except Exception:
            window_type._create_desktop_shortcut = original
            # V7 is intentionally retained: this is the exact post-V7 rollback
            # state requested for an additive V8 seam failure.
            raise
        self._shortcut_original = original

    def start(self) -> object:
        return self._base.start()

    def rollback_installation(self) -> None:
        """Remove only V8 and leave the exact installed V7 state."""

        if self._shortcut_original is not None:
            self.contract.main_window._create_desktop_shortcut = self._shortcut_original
            self._shortcut_original = None

    def rollback_all(self) -> None:
        """Test/termination helper that restores the original uninstalled host."""

        self.rollback_installation()
        self._base.rollback_installation()


def activate_main(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> OnyxLiveActivationV8:
    source = os.environ if environ is None else environ
    flags = ActivationFlagsV8.from_canonical_environ(source)
    controller = OnyxLiveActivationV8(flags, preflight_host(module, source))
    controller.install()
    controller.start()
    module._onyx_live_activation_v8 = controller
    return controller


__all__ = [
    "ActivationFlagsV8",
    "ActivationV8Error",
    "BOOTSTRAP_RELATIVE",
    "CANONICAL_LAUNCHER_RELATIVE",
    "CANONICAL_PHASE5_IDENTITY",
    "CHILD_FLAGS",
    "CONTROL_FLAGS",
    "HostContractV8",
    "LEGACY_LAUNCHER_RELATIVE",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV8",
    "PHASE5_IDENTITY_ALIASES",
    "PHASE5_IDENTITY_FLAGS",
    "ShortcutSpecV8",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
]
