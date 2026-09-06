"""Transparent-compositor successor over the authenticated current HUD V16."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

import core.onyx_hud_orb_v16 as canonical_hud_v16


FLAG_NAME: Final = "ONYX_HUD_V17_LIVE"
ROOT_OBJECT: Final = "onyxLiveShellV16Root"
QML_RELATIVE_PATH: Final = Path("qml") / "OnyxLiveShellV16.qml"
V16_MODULE_RELATIVE_PATH: Final = Path("core") / "onyx_hud_orb_v16.py"
V16_MODULE_SHA256: Final = (
    "40388959bf7d43e7b8efd7a6c3e4beaf5dd2eb0f4d39015da869928f70363c06"
)
_INSTALLATION_TOKEN: Final = object()


@dataclass(frozen=True, slots=True)
class _InstallationRecordV17:
    ui_module: ModuleType
    hud_v16_module: ModuleType
    base_host: type
    installed_host: type
    previous_flag: object
    source: Path


_ACTIVE_INSTALLATIONS: dict[int, _InstallationRecordV17] = {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accepted_v16_host(ui_module: ModuleType, hud_v16_module: ModuleType) -> type:
    root = Path(ui_module.resource_root()).resolve()
    module_path = root / V16_MODULE_RELATIVE_PATH
    loaded_path = Path(getattr(hud_v16_module, "__file__", "")).resolve()
    installation = hud_v16_module._ACTIVE_INSTALLATIONS.get(id(ui_module))
    marker = getattr(ui_module, "_ONYX_HUD_V16_INSTALLATION", None)
    host = getattr(ui_module, "_CinematicHudV5Host", None)
    if (
        loaded_path != module_path.resolve()
        or not module_path.is_file()
        or module_path.is_symlink()
        or _sha256(module_path) != V16_MODULE_SHA256
        or installation is None
        or installation.ui_module is not ui_module
        or marker is not hud_v16_module._INSTALLATION_TOKEN
        or not isinstance(host, type)
        or installation.installed_host is not host
        or host.__module__ != hud_v16_module.__name__
        or host.__qualname__ != "_install.<locals>._CinematicHudV16Host"
        or getattr(ui_module, "HUD_V5_LIVE", None) is not True
    ):
        raise RuntimeError("accepted HUD V16 installation is unavailable")
    return host


def candidate_requested(environ: dict[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(FLAG_NAME, "0") == "1"


def _install(ui_module: ModuleType, hud_v16_module: ModuleType) -> bool:
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V17_INSTALLATION", None)
    existing = _ACTIVE_INSTALLATIONS.get(key)
    if marker is not None or existing is not None:
        if (
            marker is not _INSTALLATION_TOKEN
            or existing is None
            or existing.ui_module is not ui_module
            or existing.hud_v16_module is not hud_v16_module
            or ui_module._CinematicHudV5Host is not existing.installed_host
        ):
            raise RuntimeError("HUD V17 installation drift denied")
        return True

    source = Path(ui_module.resource_root()) / QML_RELATIVE_PATH
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError(source)
    base_host = _accepted_v16_host(ui_module, hud_v16_module)
    previous_flag = ui_module.HUD_V5_LIVE

    class _CinematicHudV17Host(base_host):
        def load_source(self) -> None:
            if getattr(self, "_v13_direct_base_bootstrapping", False):
                return
            if self._shutdown:
                raise RuntimeError("cinematic HUD host is shut down")
            if self._loaded:
                return
            self._source = source
            self._quick.rootContext().setContextProperty(
                "onyxUIProjectionV3", self.projection
            )
            self._connect_scene_signal()
            self._quick.setSource(
                ui_module.QUrl.fromLocalFile(str(self._source.resolve()))
            )
            self._v13_source_load_count += 1
            errors = "\n".join(error.toString() for error in self._quick.errors())
            root_object = self._quick.rootObject()
            if (
                self._quick.status() != type(self._quick).Status.Ready
                or root_object is None
                or root_object.objectName() != ROOT_OBJECT
            ):
                self.suspend()
                raise RuntimeError(errors or "HUD V17 root failed its contract")
            self._loaded = True
            self._quick.show()
            self.sync_animation()

        @property
        def renderer_mode(self) -> str:
            return "qml-v17-humanoid-transparent"

    record = _InstallationRecordV17(
        ui_module=ui_module,
        hud_v16_module=hud_v16_module,
        base_host=base_host,
        installed_host=_CinematicHudV17Host,
        previous_flag=previous_flag,
        source=source.resolve(),
    )
    ui_module._CinematicHudV5Host = _CinematicHudV17Host
    ui_module.HUD_V5_LIVE = True
    ui_module._ONYX_HUD_V17_INSTALLATION = _INSTALLATION_TOKEN
    _ACTIVE_INSTALLATIONS[key] = record
    return True


def install_candidate(
    ui_module: ModuleType,
    hud_v16_module: ModuleType | None = None,
) -> bool:
    if not candidate_requested():
        return False
    accepted = canonical_hud_v16 if hud_v16_module is None else hud_v16_module
    accepted.install_current(ui_module)
    try:
        return _install(ui_module, accepted)
    except BaseException:
        accepted.uninstall_candidate(ui_module)
        raise


def install_current(
    ui_module: ModuleType,
    hud_v16_module: ModuleType | None = None,
) -> bool:
    accepted = canonical_hud_v16 if hud_v16_module is None else hud_v16_module
    # Authenticate our existing installation before re-entering predecessors:
    # their host pointers correctly refer to classes superseded by this host.
    if id(ui_module) in _ACTIVE_INSTALLATIONS or getattr(
        ui_module, "_ONYX_HUD_V17_INSTALLATION", None
    ) is not None:
        return _install(ui_module, accepted)
    accepted.install_current(ui_module)
    try:
        return _install(ui_module, accepted)
    except BaseException:
        accepted.uninstall_candidate(ui_module)
        raise


def uninstall_candidate(ui_module: ModuleType) -> bool:
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V17_INSTALLATION", None)
    installation = _ACTIVE_INSTALLATIONS.get(key)
    if marker is None and installation is None:
        return False
    if installation is None or installation.ui_module is not ui_module:
        raise RuntimeError("HUD V17 rollback authentication failed")
    if ui_module._CinematicHudV5Host is not installation.installed_host:
        raise RuntimeError("HUD V17 installed host drift denied")
    ui_module._CinematicHudV5Host = installation.base_host
    ui_module.HUD_V5_LIVE = installation.previous_flag
    _ACTIVE_INSTALLATIONS.pop(key)
    if hasattr(ui_module, "_ONYX_HUD_V17_INSTALLATION"):
        delattr(ui_module, "_ONYX_HUD_V17_INSTALLATION")
    installation.hud_v16_module.uninstall_candidate(ui_module)
    return True


__all__ = [
    "FLAG_NAME",
    "QML_RELATIVE_PATH",
    "ROOT_OBJECT",
    "candidate_requested",
    "install_candidate",
    "install_current",
    "uninstall_candidate",
]
