"""Default-off V13 activation composing frozen Phase 6 Wiring V2 over V12."""

from __future__ import annotations

import hashlib
import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import onyx_live_activation_v12 as v12
from core import phase6_live_wiring_v1 as wiring_v1
from core import phase6_live_wiring_v2 as wiring_v2
from core.live_model import resolve_live_model
from scripts.verify_phase6_live_wiring_v2 import verify as verify_wiring_v2


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V13"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V13"
WIRING_V2_FLAG: Final = wiring_v2.FEATURE_FLAG
BOOTSTRAP_RELATIVE: Final = Path("scripts/bootstrap_onyx_live_v13.pyw")
CANONICAL_LAUNCHER_RELATIVE: Final = Path("scripts/launch_onyx_live_v13.pyw")
V12_FROZEN_ROOTS: Final = (
    (
        Path("core/onyx_live_activation_v12.py"),
        "9dbb3de15e0125b5c9fe9ac48b57b272360655f7d713d438f22c6580259e4fd7",
    ),
    (
        Path("scripts/bootstrap_onyx_live_v12.pyw"),
        "4b66dfcfed9a47e12c960e95769841fb4dd1f35a1b9be53da8de769020f44425",
    ),
    (
        Path("scripts/launch_onyx_live_v12.pyw"),
        "b1afb265bb3166567ff46aecc168ba38bc2e98210646430c7d9c4f0cb9ea91a2",
    ),
    (
        Path("core/onyx_hud_orb_v9.py"),
        "85bf425babd49271ebe1f71ed0e69a1a361646e595cbc3c5483e4e1774c321d1",
    ),
    (
        Path("qml/OnyxLiveShellV9.qml"),
        "61dbf4534378a4f27a46cba8c1ce73b6acb1d375b9466505d7258cdcc357b52b",
    ),
)
WIRING_V2_MANIFEST: Final = Path(
    "docs/onyx/checkpoints/phase6-live-wiring-v2/manifest.json"
)
WIRING_V2_MANIFEST_SHA256: Final = (
    "d29da31c06587c7fbef5c5bf69e7f6699cd7e39fe48ad547b854e036515ff8c5"
)
WIRING_V2_ARTIFACT_ROOT_SHA256: Final = (
    "dfdcd199147871cc10f3bf120db21cdffda339d12e0737b6e6e44526a7e5615b"
)
VERSION_CONTROL_FLAGS = tuple(
    name
    for version in range(1, 14)
    for name in (
        f"ONYX_LIVE_ACTIVATION_V{version}",
        f"ONYX_LIVE_ROLLBACK_V{version}",
    )
)
CONTROL_FLAGS = (*VERSION_CONTROL_FLAGS, WIRING_V2_FLAG, *v12.CONTROL_FLAGS)


class ActivationV13Error(RuntimeError):
    """The V13 Phase 6 composition was not exact."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_frozen_roots(project: Path) -> dict[str, object]:
    project = project.resolve()
    for relative, expected in V12_FROZEN_ROOTS:
        path = project / relative
        if path.is_symlink() or not path.is_file() or _sha256(path) != expected:
            raise ActivationV13Error(f"V12 predecessor drift: {relative}")
    manifest_path = project / WIRING_V2_MANIFEST
    if (
        manifest_path.is_symlink()
        or not manifest_path.is_file()
        or _sha256(manifest_path) != WIRING_V2_MANIFEST_SHA256
    ):
        raise ActivationV13Error("frozen Wiring V2 manifest drift")
    result = verify_wiring_v2()
    if (
        result.get("candidate") != wiring_v2.CANDIDATE
        or result.get("artifact_root_sha256") != WIRING_V2_ARTIFACT_ROOT_SHA256
        or result.get("component_roots") != 15
        or result.get("default_off") is not True
        or result.get("live_wiring") is not False
        or any(
            result.get(name) != 0
            for name in (
                "provider_calls",
                "process_calls",
                "network_calls",
                "live_calls",
            )
        )
    ):
        raise ActivationV13Error("frozen Wiring V2 candidate contract drift")
    for relative in (BOOTSTRAP_RELATIVE, CANONICAL_LAUNCHER_RELATIVE):
        path = project / relative
        if path.is_symlink() or not path.is_file():
            raise ActivationV13Error(f"V13 runtime file unavailable: {relative}")
    return result


@dataclass(frozen=True, slots=True)
class ActivationFlagsV13:
    master: bool
    wiring_v2: bool
    base: v12.ActivationFlagsV12

    def __post_init__(self) -> None:
        if (
            type(self.master) is not bool
            or type(self.wiring_v2) is not bool
            or not self.master
            or not self.wiring_v2
            or type(self.base) is not v12.ActivationFlagsV12
        ):
            raise ActivationV13Error("complete exact V13 flags are required")

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ActivationFlagsV13":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV13Error("rollback is not an active V13 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(WIRING_V2_FLAG) != "true":
            raise ActivationV13Error("activation environment is not canonical V13")
        try:
            base = v12.ActivationFlagsV12.from_canonical_environ(source)
        except v12.ActivationV12Error as exc:
            raise ActivationV13Error("V12 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment() -> dict[str, str]:
    result = v12.exact_activation_environment()
    result[LIVE_MASTER_FLAG] = "1"
    result[WIRING_V2_FLAG] = "true"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v12_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(WIRING_V2_FLAG, None)
    result.update(v12.exact_activation_environment())
    return result


@dataclass(frozen=True, slots=True)
class HostContractV13:
    module: ModuleType
    ui_module: ModuleType
    main_window: type
    project: Path
    base: v12.HostContractV12


@dataclass(frozen=True, slots=True)
class _RollbackAuthorityV13:
    controller: object
    main_window: type
    wiring_v2: wiring_v2.Phase6LiveWiringV2
    shortcut_v12: object


_ROLLBACK_AUTHORITIES: dict[int, _RollbackAuthorityV13] = {}


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
) -> HostContractV13:
    source = os.environ if environ is None else environ
    ActivationFlagsV13.from_canonical_environ(source)
    base = v12.preflight_host(module, restore_v12_environment(source))
    _verify_frozen_roots(base.project)
    return HostContractV13(
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
    ActivationFlagsV13.from_canonical_environ(source)
    v12.verify_activation_prerequisites(project, restore_v12_environment(source))
    _verify_frozen_roots(project)


class OnyxLiveActivationV13:
    """Exact V12 plus session-bound Wiring V2 and its shortcut seam."""

    BASE_SEAM_COUNT = v12.OnyxLiveActivationV12.TOTAL_SEAM_COUNT
    V13_SEAM_COUNT = 2
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V13_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV13,
        contract: HostContractV13,
        **v12_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV13 or type(contract) is not (
            HostContractV13
        ):
            raise ActivationV13Error("exact V13 flags and host contract are required")
        self.flags = flags
        self.contract = contract
        self._base = v12.OnyxLiveActivationV12(
            flags.base,
            contract.base,
            **v12_options,
        )
        self._wiring_v2: wiring_v2.Phase6LiveWiringV2 | None = None

    @property
    def state(self) -> object:
        return self._base.state

    @property
    def wiring_controller(self) -> object:
        return self._base.wiring_controller

    @property
    def phase6_wiring_v2(self) -> wiring_v2.Phase6LiveWiringV2 | None:
        return self._wiring_v2

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    def _create_v13_shortcut(self, instance: object) -> None:
        authority = _ROLLBACK_AUTHORITIES.get(id(self))
        if authority is None:
            raise ActivationV13Error("V13 shortcut authority is unavailable")
        if self.contract.ui_module.is_frozen() or platform.system() != "Windows":
            authority.shortcut_v12(instance)
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
            instance._log.append_log("SYS: Desktop shortcut created for Onyx Live V13.")
        except Exception as exc:
            instance._log.append_log(
                f"ERR: Shortcut failed safely ({type(exc).__name__})."
            )

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not (1 <= fail_after <= self.TOTAL_SEAM_COUNT):
            raise ActivationV13Error("seam failpoint is outside V13 installation")
        base_failpoint = (
            fail_after if fail_after and fail_after <= self.BASE_SEAM_COUNT else None
        )
        self._base.install(fail_after=base_failpoint)
        if base_failpoint is not None:
            return
        try:
            accepted_v1 = self._base.wiring_controller
            if type(accepted_v1) is not wiring_v1.Phase6LiveWiringV1:
                raise ActivationV13Error("installed Wiring V1 authority is unavailable")
            config_path = getattr(self.contract.module, "API_CONFIG_PATH", None)
            if not isinstance(config_path, Path):
                raise ActivationV13Error("live model configuration path is unavailable")
            controller = wiring_v2.create_phase6_live_wiring_v2(
                gate=wiring_v2.LiveWiringV2FeatureGate(True),
                wiring_v1=accepted_v1,
                project_root=self.contract.project,
                model_id=resolve_live_model(config_path),
            )
            if type(controller) is not wiring_v2.Phase6LiveWiringV2:
                raise ActivationV13Error("Wiring V2 construction was not exact")
            controller.install()
            original_shortcut = self.contract.main_window._create_desktop_shortcut
            self._wiring_v2 = controller
            _ROLLBACK_AUTHORITIES[id(self)] = _RollbackAuthorityV13(
                controller=self,
                main_window=self.contract.main_window,
                wiring_v2=controller,
                shortcut_v12=original_shortcut,
            )
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV13Error("injected V13 Wiring V2 seam failure")

            activation = self

            def create_desktop_shortcut(instance: object) -> None:
                activation._create_v13_shortcut(instance)

            self.contract.main_window._create_desktop_shortcut = create_desktop_shortcut
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV13Error("injected V13 shortcut seam failure")
        except Exception:
            self.rollback_installation()
            raise

    def rollback_installation(self) -> None:
        errors: list[Exception] = []
        authority = _ROLLBACK_AUTHORITIES.pop(id(self), None)
        if authority is not None and (
            type(authority) is not _RollbackAuthorityV13
            or authority.controller is not self
            or authority.main_window is not self.contract.main_window
            or authority.wiring_v2 is not self._wiring_v2
        ):
            errors.append(ActivationV13Error("V13 rollback authority drift denied"))
            authority = None
        if authority is not None:
            self.contract.main_window._create_desktop_shortcut = authority.shortcut_v12
            try:
                authority.wiring_v2.rollback_installation()
            except Exception as exc:
                errors.append(exc)
        elif self._wiring_v2 is not None:
            errors.append(ActivationV13Error("V13 rollback authority is unavailable"))
        self._wiring_v2 = None
        restored = restore_v12_environment(os.environ)
        os.environ.clear()
        os.environ.update(restored)
        if getattr(self.contract.module, "_onyx_live_activation_v13", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v13")
        if errors:
            raise ActivationV13Error(
                "V13 rollback completed with authority error"
            ) from errors[0]

    def rollback_all(self) -> None:
        self.rollback_installation()
        self._base.rollback_all()


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
) -> OnyxLiveActivationV13:
    source = os.environ if environ is None else environ
    flags = ActivationFlagsV13.from_canonical_environ(source)
    controller = OnyxLiveActivationV13(flags, preflight_host(module, source))
    controller.install()
    module._onyx_live_activation_v13 = controller
    return controller


__all__ = [
    "ActivationFlagsV13",
    "ActivationV13Error",
    "BOOTSTRAP_RELATIVE",
    "CANONICAL_LAUNCHER_RELATIVE",
    "CONTROL_FLAGS",
    "HostContractV13",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV13",
    "WIRING_V2_FLAG",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v12_environment",
    "verify_activation_prerequisites",
]
