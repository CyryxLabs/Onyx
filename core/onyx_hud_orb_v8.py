"""Default-off voice-reactive HUD V8 successor over accepted HUD V7."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

import core.onyx_hud_orb_v7 as hud_v7


FLAG_NAME: Final = "ONYX_HUD_V8_LIVE"
ROOT_OBJECT: Final = "onyxLiveShellV8Root"
QML_RELATIVE_PATH: Final = Path("qml") / "OnyxLiveShellV8.qml"
V7_QML_RELATIVE_PATH: Final = Path("qml") / "OnyxLiveShellV7.qml"
V7_MODULE_RELATIVE_PATH: Final = Path("core") / "onyx_hud_orb_v7.py"
V7_MANIFEST_RELATIVE_PATH: Final = (
    Path("docs") / "onyx" / "checkpoints" / "hud-orb-v7-candidate" / "manifest.json"
)
V7_MODULE_SHA256: Final = (
    "31fd7d0df7413ac9dbba3db463de28390bdfaa75e2173dae54c04dfd82a6c150"
)
V7_MANIFEST_SHA256: Final = (
    "38f77492b6b72eeb8bff8c1bddbe129081bbe79e67b7f8679054d86dff781f03"
)
_INSTALLATION_TOKEN: Final = object()


@dataclass(frozen=True, slots=True)
class _InstallationRecordV8:
    ui_module: ModuleType
    base_host: type
    installed_host: type
    previous_flag: object
    source: Path


_ACTIVE_INSTALLATIONS: dict[int, _InstallationRecordV8] = {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accepted_v7_host(ui_module: ModuleType) -> type:
    root = Path(ui_module.resource_root()).resolve()
    module_path = root / V7_MODULE_RELATIVE_PATH
    manifest_path = root / V7_MANIFEST_RELATIVE_PATH
    if (
        not module_path.is_file()
        or not manifest_path.is_file()
        or _sha256(module_path) != V7_MODULE_SHA256
        or _sha256(manifest_path) != V7_MANIFEST_SHA256
    ):
        raise RuntimeError("accepted HUD V7 artifacts failed authentication")
    installation = hud_v7._ACTIVE_INSTALLATIONS.get(id(ui_module))
    marker = getattr(ui_module, "_ONYX_HUD_V7_INSTALLATION", None)
    if (
        installation is None
        or installation.ui_module is not ui_module
        or marker is not hud_v7._INSTALLATION_TOKEN
    ):
        raise RuntimeError("accepted HUD V7 installation is unavailable")
    host = getattr(ui_module, "_CinematicHudV5Host", None)
    expected_source = (root / V7_QML_RELATIVE_PATH).resolve()
    if (
        not isinstance(host, type)
        or installation.installed_host is not host
        or installation.base_host is host
        or host.__bases__ != (installation.base_host,)
        or host.__module__ != "core.onyx_hud_orb_v7"
        or host.__qualname__ != "install_candidate.<locals>._CinematicHudV7Host"
        or installation.source.resolve() != expected_source
        or getattr(ui_module, "HUD_V5_LIVE", None) is not True
    ):
        raise RuntimeError("accepted HUD V7 host failed authentication")
    return host


def candidate_requested(environ: dict[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(FLAG_NAME, "0") == "1"


def install_candidate(ui_module: ModuleType) -> bool:
    """Overlay speaking-only internal particles while preserving the V7 shell."""
    if not candidate_requested():
        return False
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V8_INSTALLATION", None)
    existing = _ACTIVE_INSTALLATIONS.get(key)
    if marker is not None or existing is not None:
        if (
            marker is not _INSTALLATION_TOKEN
            or existing is None
            or existing.ui_module is not ui_module
            or ui_module._CinematicHudV5Host is not existing.installed_host
            or ui_module.HUD_V5_LIVE is not True
        ):
            raise RuntimeError("HUD V8 installation drift denied")
        return True
    source = Path(ui_module.resource_root()) / QML_RELATIVE_PATH
    if not source.is_file():
        raise FileNotFoundError(source)
    base_host = _accepted_v7_host(ui_module)
    previous_flag = ui_module.HUD_V5_LIVE

    class _CinematicHudV8Host(base_host):
        def __init__(self, owner, owner_name: str) -> None:
            self._v8_bootstrapping = True
            super().__init__(owner, owner_name)
            self.suspend()
            self._source = source
            self._v8_bootstrapping = False
            self.load_source()

        def load_source(self) -> None:
            if self._shutdown:
                raise RuntimeError("cinematic HUD host is shut down")
            if self._loaded:
                return
            self._quick.rootContext().setContextProperty(
                "onyxUIProjectionV3", self.projection
            )
            self._connect_scene_signal()
            self._quick.setSource(
                ui_module.QUrl.fromLocalFile(str(self._source.resolve()))
            )
            errors = "\n".join(error.toString() for error in self._quick.errors())
            root = self._quick.rootObject()
            if getattr(self, "_v6_bootstrapping", False):
                expected = "onyxLiveShellV5Root"
            elif getattr(self, "_v7_bootstrapping", False):
                expected = "onyxLiveShellV6Root"
            elif self._v8_bootstrapping:
                expected = "onyxLiveShellV7Root"
            else:
                expected = ROOT_OBJECT
            if (
                self._quick.status() != type(self._quick).Status.Ready
                or root is None
                or root.objectName() != expected
            ):
                self.suspend()
                raise RuntimeError(errors or "HUD V8 root failed its contract")
            self._loaded = True
            self._quick.show()

        @property
        def renderer_mode(self) -> str:
            return "qml-v8-voice-reactive"

    record = _InstallationRecordV8(
        ui_module=ui_module,
        base_host=base_host,
        installed_host=_CinematicHudV8Host,
        previous_flag=previous_flag,
        source=source.resolve(),
    )
    try:
        ui_module._CinematicHudV5Host = _CinematicHudV8Host
        ui_module.HUD_V5_LIVE = True
        ui_module._ONYX_HUD_V8_INSTALLATION = _INSTALLATION_TOKEN
        _ACTIVE_INSTALLATIONS[key] = record
    except Exception:
        _ACTIVE_INSTALLATIONS.pop(key, None)
        ui_module._CinematicHudV5Host = base_host
        ui_module.HUD_V5_LIVE = previous_flag
        if hasattr(ui_module, "_ONYX_HUD_V8_INSTALLATION"):
            delattr(ui_module, "_ONYX_HUD_V8_INSTALLATION")
        raise
    return True


def uninstall_candidate(ui_module: ModuleType) -> bool:
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V8_INSTALLATION", None)
    installation = _ACTIVE_INSTALLATIONS.get(key)
    if marker is None and installation is None:
        return False
    if installation is None or installation.ui_module is not ui_module:
        raise RuntimeError("HUD V8 rollback authentication failed")
    ui_module._CinematicHudV5Host = installation.base_host
    ui_module.HUD_V5_LIVE = installation.previous_flag
    _ACTIVE_INSTALLATIONS.pop(key)
    if hasattr(ui_module, "_ONYX_HUD_V8_INSTALLATION"):
        delattr(ui_module, "_ONYX_HUD_V8_INSTALLATION")
    return True


__all__ = [
    "FLAG_NAME",
    "QML_RELATIVE_PATH",
    "ROOT_OBJECT",
    "candidate_requested",
    "install_candidate",
    "uninstall_candidate",
]
