"""Current HUD lifecycle successor that restores low-CPU ambient Orb motion.

HUD V11 deliberately constructs only one QML root.  Its direct-base bootstrap
also means the base host's initial visibility synchronization occurs before the
current root is marked loaded.  V12 preserves the authenticated V11 renderer
and performs the missing synchronization after that root becomes live.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

import core.onyx_hud_orb_v11 as canonical_hud_v11


V11_MODULE_RELATIVE: Final = Path("core") / "onyx_hud_orb_v11.py"
V11_MODULE_SHA256: Final = (
    "95007e7df5be24fa84b7ac7bf558b48eb4761d8bed2db232ede2fe4f4556be8a"
)
_INSTALLATION_TOKEN: Final = object()


@dataclass(frozen=True, slots=True)
class _InstallationRecordV12:
    ui_module: ModuleType
    hud_v11_module: ModuleType
    base_host: type
    installed_host: type


_ACTIVE_INSTALLATIONS: dict[int, _InstallationRecordV12] = {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accepted_v11_host(ui_module: ModuleType, hud_v11_module: ModuleType) -> type:
    root = Path(ui_module.resource_root()).resolve()
    module_path = root / V11_MODULE_RELATIVE
    loaded_path = Path(getattr(hud_v11_module, "__file__", "")).resolve()
    installation = hud_v11_module._ACTIVE_INSTALLATIONS.get(id(ui_module))
    marker = getattr(ui_module, "_ONYX_HUD_V11_INSTALLATION", None)
    host = getattr(ui_module, "_CinematicHudV5Host", None)
    if (
        loaded_path != module_path.resolve()
        or not module_path.is_file()
        or module_path.is_symlink()
        or _sha256(module_path) != V11_MODULE_SHA256
        or installation is None
        or installation.ui_module is not ui_module
        or marker is not hud_v11_module._INSTALLATION_TOKEN
        or not isinstance(host, type)
        or installation.installed_host is not host
        or host.__module__ != hud_v11_module.__name__
        or host.__qualname__ != "_install.<locals>._CinematicHudV11Host"
        or getattr(ui_module, "HUD_V5_LIVE", None) is not True
    ):
        raise RuntimeError("accepted HUD V11 installation is unavailable")
    return host


def _install(ui_module: ModuleType, hud_v11_module: ModuleType) -> bool:
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V12_INSTALLATION", None)
    existing = _ACTIVE_INSTALLATIONS.get(key)
    if marker is not None or existing is not None:
        if (
            marker is not _INSTALLATION_TOKEN
            or existing is None
            or existing.ui_module is not ui_module
            or existing.hud_v11_module is not hud_v11_module
            or ui_module._CinematicHudV5Host is not existing.installed_host
        ):
            raise RuntimeError("HUD V12 installation drift denied")
        return True

    base_host = _accepted_v11_host(ui_module, hud_v11_module)

    class _CinematicHudV12Host(base_host):
        def load_source(self) -> None:
            super().load_source()
            if getattr(self, "_loaded", False) and not getattr(
                self, "_shutdown", False
            ):
                # The existing OrbMotionPolicyV1 owns the bounded 8-24 FPS
                # cadence and stops while hidden, minimized, muted or reduced.
                # This call only connects that already accepted policy to the
                # newly loaded V11 root; it does not add a timer or renderer.
                self.sync_animation()

        @property
        def renderer_mode(self) -> str:
            # V12 does not replace the V11 QML renderer.  Preserve the accepted
            # renderer identity while adding only its missing lifecycle sync.
            return "qml-v11-explicit-exit"

    record = _InstallationRecordV12(
        ui_module=ui_module,
        hud_v11_module=hud_v11_module,
        base_host=base_host,
        installed_host=_CinematicHudV12Host,
    )
    try:
        ui_module._CinematicHudV5Host = _CinematicHudV12Host
        ui_module._ONYX_HUD_V12_INSTALLATION = _INSTALLATION_TOKEN
        _ACTIVE_INSTALLATIONS[key] = record
    except Exception:
        _ACTIVE_INSTALLATIONS.pop(key, None)
        ui_module._CinematicHudV5Host = base_host
        if hasattr(ui_module, "_ONYX_HUD_V12_INSTALLATION"):
            delattr(ui_module, "_ONYX_HUD_V12_INSTALLATION")
        raise
    return True


def install_current(
    ui_module: ModuleType,
    hud_v11_module: ModuleType | None = None,
) -> bool:
    accepted_v11 = canonical_hud_v11 if hud_v11_module is None else hud_v11_module
    accepted_v11.install_current(ui_module)
    try:
        return _install(ui_module, accepted_v11)
    except BaseException:
        accepted_v11.uninstall_candidate(ui_module)
        raise


def uninstall_candidate(ui_module: ModuleType) -> bool:
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V12_INSTALLATION", None)
    installation = _ACTIVE_INSTALLATIONS.get(key)
    if marker is None and installation is None:
        return False
    if installation is None or installation.ui_module is not ui_module:
        raise RuntimeError("HUD V12 rollback authentication failed")
    if ui_module._CinematicHudV5Host is not installation.installed_host:
        raise RuntimeError("HUD V12 installed host drift denied")
    ui_module._CinematicHudV5Host = installation.base_host
    _ACTIVE_INSTALLATIONS.pop(key)
    if hasattr(ui_module, "_ONYX_HUD_V12_INSTALLATION"):
        delattr(ui_module, "_ONYX_HUD_V12_INSTALLATION")
    installation.hud_v11_module.uninstall_candidate(ui_module)
    return True


__all__ = ["install_current", "uninstall_candidate"]
