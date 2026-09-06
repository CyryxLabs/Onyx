"""Default-off V12 activation adding the arc-free HUD V9 over accepted V11."""

from __future__ import annotations

import hashlib
import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import onyx_hud_orb_v9 as hud_v9
from core import onyx_live_activation_v11 as v11


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V12"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V12"
HUD_V9_FLAG: Final = hud_v9.FLAG_NAME
BOOTSTRAP_RELATIVE: Final = Path("scripts/bootstrap_onyx_live_v12.pyw")
CANONICAL_LAUNCHER_RELATIVE: Final = Path("scripts/launch_onyx_live_v12.pyw")
V11_ACCEPTED_ROOTS: Final = (
    (
        Path("core/onyx_live_activation_v11.py"),
        "d0745edc218c7374dca744c78bc1824db2cbc512f09af4c56497a7631fab92d2",
    ),
)
HUD_V9_ROOTS: Final = (
    (
        Path("core/onyx_hud_orb_v9.py"),
        "85bf425babd49271ebe1f71ed0e69a1a361646e595cbc3c5483e4e1774c321d1",
    ),
    (
        Path("qml/OnyxLiveShellV9.qml"),
        "61dbf4534378a4f27a46cba8c1ce73b6acb1d375b9466505d7258cdcc357b52b",
    ),
)
VERSION_CONTROL_FLAGS = tuple(
    name
    for version in range(1, 13)
    for name in (
        f"ONYX_LIVE_ACTIVATION_V{version}",
        f"ONYX_LIVE_ROLLBACK_V{version}",
    )
)
CONTROL_FLAGS = (*VERSION_CONTROL_FLAGS, HUD_V9_FLAG, *v11.CONTROL_FLAGS)


class ActivationV12Error(RuntimeError):
    """The arc-free V12 visual activation was not exact."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_v9_roots(project: Path) -> None:
    root = project.resolve()
    for relative, expected in V11_ACCEPTED_ROOTS:
        path = project / relative
        if path.is_symlink() or not path.is_file() or _sha256(path) != expected:
            raise ActivationV12Error(f"V11 predecessor drift: {relative}")
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise ActivationV12Error(
                f"V11 predecessor path escapes project: {relative}"
            ) from exc
    for relative, expected in HUD_V9_ROOTS:
        path = project / relative
        if path.is_symlink() or not path.is_file():
            raise ActivationV12Error(f"HUD V9 artifact is unavailable: {relative}")
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise ActivationV12Error(f"HUD V9 path escapes project: {relative}") from exc
        if _sha256(path) != expected:
            raise ActivationV12Error(f"HUD V9 artifact drift: {relative}")
    for relative in (BOOTSTRAP_RELATIVE, CANONICAL_LAUNCHER_RELATIVE):
        path = project / relative
        if path.is_symlink() or not path.is_file():
            raise ActivationV12Error(f"V12 runtime file is unavailable: {relative}")


@dataclass(frozen=True, slots=True)
class ActivationFlagsV12:
    master: bool
    hud_v9: bool
    base: v11.ActivationFlagsV11

    def __post_init__(self) -> None:
        if (
            type(self.master) is not bool
            or type(self.hud_v9) is not bool
            or not self.master
            or not self.hud_v9
            or type(self.base) is not v11.ActivationFlagsV11
        ):
            raise ActivationV12Error("complete exact V12 flags are required")

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ActivationFlagsV12":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV12Error("rollback is not an active V12 configuration")
        if (
            source.get(LIVE_MASTER_FLAG) != "1"
            or source.get(HUD_V9_FLAG) != "1"
        ):
            raise ActivationV12Error("activation environment is not canonical V12")
        try:
            base = v11.ActivationFlagsV11.from_canonical_environ(source)
        except v11.ActivationV11Error as exc:
            raise ActivationV12Error("accepted V11 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment() -> dict[str, str]:
    result = v11.exact_activation_environment()
    result[LIVE_MASTER_FLAG] = "1"
    result[HUD_V9_FLAG] = "1"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v11_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(HUD_V9_FLAG, None)
    result.update(v11.exact_activation_environment())
    return result


@dataclass(frozen=True, slots=True)
class HostContractV12:
    module: ModuleType
    ui_module: ModuleType
    main_window: type
    project: Path
    base: v11.HostContractV11


@dataclass(frozen=True, slots=True)
class _RollbackAuthorityV12:
    controller: object
    main_window: type
    shortcut_v11: object | None = None
    hud_installed: bool = False


_ROLLBACK_AUTHORITIES: dict[int, _RollbackAuthorityV12] = {}


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
) -> HostContractV12:
    source = os.environ if environ is None else environ
    ActivationFlagsV12.from_canonical_environ(source)
    base = v11.preflight_host(module, restore_v11_environment(source))
    _verify_v9_roots(base.project)
    return HostContractV12(
        module=module,
        ui_module=base.ui_module,
        main_window=base.main_window,
        project=base.project,
        base=base,
    )


def verify_activation_prerequisites(
    project: Path,
    environ: Mapping[str, str] | None = None,
) -> None:
    source = os.environ if environ is None else environ
    ActivationFlagsV12.from_canonical_environ(source)
    v11.verify_activation_prerequisites(project, restore_v11_environment(source))
    _verify_v9_roots(project)


class OnyxLiveActivationV12:
    """Exact V11 plus one visual seam and its persistent shortcut seam."""

    BASE_SEAM_COUNT = v11.OnyxLiveActivationV11.TOTAL_SEAM_COUNT
    V12_SEAM_COUNT = 2
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V12_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV12,
        contract: HostContractV12,
        **v11_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV12 or type(contract) is not (
            HostContractV12
        ):
            raise ActivationV12Error("exact V12 flags and host contract are required")
        self.flags = flags
        self.contract = contract
        self._base = v11.OnyxLiveActivationV11(
            flags.base,
            contract.base,
            **v11_options,
        )

    @property
    def state(self) -> object:
        return self._base.state

    @property
    def wiring_controller(self) -> object:
        return self._base.wiring_controller

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    def _create_v12_shortcut(self, instance: object) -> None:
        if (
            self.contract.ui_module.is_frozen()
            or platform.system() != "Windows"
        ):
            authority = _ROLLBACK_AUTHORITIES[id(self)]
            authority.shortcut_v11(instance)
            return
        desktop = instance._desktop_path("Windows")
        icon = self.contract.project / "config" / "onyx.ico"
        pythonw = self.contract.project / ".venv" / "Scripts" / "pythonw.exe"
        bootstrap = self.contract.project / BOOTSTRAP_RELATIVE
        try:
            if not icon.exists():
                instance._build_onyx_icon(icon)
            instance._create_lnk_windows(
                str(desktop / "Onyx.lnk"),
                str(pythonw),
                str(bootstrap),
                str(self.contract.project),
                str(icon),
            )
            instance._log.append_log(
                "SYS: Desktop shortcut created for Onyx Live V12."
            )
        except Exception as exc:
            instance._log.append_log(
                f"ERR: Shortcut failed safely ({type(exc).__name__})."
            )

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not (1 <= fail_after <= self.TOTAL_SEAM_COUNT):
            raise ActivationV12Error("seam failpoint is outside V12 installation")
        base_failpoint = (
            fail_after if fail_after and fail_after <= self.BASE_SEAM_COUNT else None
        )
        self._base.install(fail_after=base_failpoint)
        if base_failpoint is not None:
            return
        try:
            accepted_v8 = self._base._hud_v8_module
            if accepted_v8 is None:
                raise ActivationV12Error("accepted V11 HUD V8 authority is unavailable")
            if hud_v9.install_candidate(self.contract.ui_module, accepted_v8) is not True:
                raise ActivationV12Error("HUD V9 installation was not exact")
            original_shortcut = self.contract.main_window._create_desktop_shortcut
            _ROLLBACK_AUTHORITIES[id(self)] = _RollbackAuthorityV12(
                controller=self,
                main_window=self.contract.main_window,
                shortcut_v11=original_shortcut,
                hud_installed=True,
            )
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV12Error("injected V12 HUD V9 seam failure")

            activation = self

            def create_desktop_shortcut(instance: object) -> None:
                activation._create_v12_shortcut(instance)

            self.contract.main_window._create_desktop_shortcut = (
                create_desktop_shortcut
            )
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV12Error("injected V12 shortcut seam failure")
        except Exception:
            self.rollback_installation()
            raise

    def rollback_installation(self) -> None:
        errors: list[Exception] = []
        authority = _ROLLBACK_AUTHORITIES.pop(id(self), None)
        if authority is not None and (
            type(authority) is not _RollbackAuthorityV12
            or authority.controller is not self
            or authority.main_window is not self.contract.main_window
        ):
            errors.append(ActivationV12Error("V12 rollback authority drift denied"))
            authority = None
        if authority is not None and authority.shortcut_v11 is not None:
            self.contract.main_window._create_desktop_shortcut = (
                authority.shortcut_v11
            )
        if authority is not None and authority.hud_installed:
            try:
                if hud_v9.uninstall_candidate(self.contract.ui_module) is not True:
                    raise ActivationV12Error("HUD V9 rollback was not exact")
            except Exception as exc:
                errors.append(exc)
        restored = restore_v11_environment(os.environ)
        os.environ.clear()
        os.environ.update(restored)
        if getattr(self.contract.module, "_onyx_live_activation_v12", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v12")
        if errors:
            raise ActivationV12Error(
                "V12 rollback completed with authority error"
            ) from errors[0]

    def rollback_all(self) -> None:
        self.rollback_installation()
        self._base.rollback_all()


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
) -> OnyxLiveActivationV12:
    source = os.environ if environ is None else environ
    flags = ActivationFlagsV12.from_canonical_environ(source)
    controller = OnyxLiveActivationV12(flags, preflight_host(module, source))
    controller.install()
    module._onyx_live_activation_v12 = controller
    return controller


__all__ = [
    "ActivationFlagsV12",
    "ActivationV12Error",
    "BOOTSTRAP_RELATIVE",
    "CANONICAL_LAUNCHER_RELATIVE",
    "CONTROL_FLAGS",
    "HUD_V9_FLAG",
    "HostContractV12",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV12",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v11_environment",
    "verify_activation_prerequisites",
]
