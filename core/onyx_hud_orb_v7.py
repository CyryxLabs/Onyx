"""Default-off cinematic HUD/Orb V7 successor over the accepted V6 host."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from types import ModuleType
from typing import Final

FLAG_NAME: Final = "ONYX_HUD_V7_LIVE"
ROOT_OBJECT: Final = "onyxLiveShellV7Root"
QML_RELATIVE_PATH: Final = Path("qml") / "OnyxLiveShellV7.qml"
V6_QML_RELATIVE_PATH: Final = Path("qml") / "OnyxLiveShellV6.qml"
V6_MODULE_RELATIVE_PATH: Final = Path("core") / "onyx_hud_orb_v6.py"
V6_MANIFEST_RELATIVE_PATH: Final = (
    Path("docs") / "onyx" / "checkpoints" / "hud-orb-v6-candidate" / "manifest.json"
)
V6_MODULE_SHA256: Final = (
    "ee5f5f62ab0c799313e7b9ffcf7b3f5364af8b1d80d2d126a63fa4b2290b4233"
)
V6_MANIFEST_SHA256: Final = (
    "ba034588791b1003a6743bf037ae32a11285adcac7c4084cba1bc5bb3923ae1c"
)
_INSTALLATION_TOKEN: Final = object()


@dataclass(frozen=True, slots=True)
class _InstallationRecordV7:
    ui_module: ModuleType
    base_host: type
    installed_host: type
    previous_flag: object
    source: Path


_ACTIVE_INSTALLATIONS: dict[int, _InstallationRecordV7] = {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accepted_v6_host(ui_module: ModuleType) -> type:
    root = Path(ui_module.resource_root()).resolve()
    module_path = root / V6_MODULE_RELATIVE_PATH
    manifest_path = root / V6_MANIFEST_RELATIVE_PATH
    if (
        not module_path.is_file()
        or not manifest_path.is_file()
        or _sha256(module_path) != V6_MODULE_SHA256
        or _sha256(manifest_path) != V6_MANIFEST_SHA256
    ):
        raise RuntimeError("accepted HUD V6 artifacts failed authentication")
    installation = getattr(ui_module, "_ONYX_HUD_V6_INSTALLATION", None)
    if type(installation) is not dict or set(installation) != {
        "base_host",
        "previous_flag",
        "source",
    }:
        raise RuntimeError("accepted HUD V6 installation is unavailable")
    host = getattr(ui_module, "_CinematicHudV5Host", None)
    base_host = installation["base_host"]
    expected_source = (root / V6_QML_RELATIVE_PATH).resolve()
    try:
        installed_source = Path(installation["source"]).resolve()
    except (TypeError, ValueError):
        raise RuntimeError(
            "accepted HUD V6 installation failed authentication"
        ) from None
    renderer = getattr(host, "renderer_mode", None)
    renderer_getter = getattr(renderer, "fget", None)
    if (
        not isinstance(host, type)
        or not isinstance(base_host, type)
        or host is base_host
        or host.__bases__ != (base_host,)
        or host.__module__ != "core.onyx_hud_orb_v6"
        or host.__qualname__ != "install_candidate.<locals>._CinematicHudV6Host"
        or renderer_getter is None
        or renderer_getter.__module__ != "core.onyx_hud_orb_v6"
        or installed_source != expected_source
        or getattr(ui_module, "HUD_V5_LIVE", None) is not True
    ):
        raise RuntimeError("accepted HUD V6 host failed authentication")
    return host


def candidate_requested(environ: dict[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(FLAG_NAME, "0") == "1"


def install_candidate(ui_module: ModuleType) -> bool:
    """Swap only the accepted V6 host source; retain one QQuickWidget."""
    if not candidate_requested():
        return False
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V7_INSTALLATION", None)
    existing = _ACTIVE_INSTALLATIONS.get(key)
    if marker is not None or existing is not None:
        if (
            marker is not _INSTALLATION_TOKEN
            or existing is None
            or existing.ui_module is not ui_module
            or ui_module._CinematicHudV5Host is not existing.installed_host
            or ui_module.HUD_V5_LIVE is not True
        ):
            raise RuntimeError("HUD V7 installation drift denied")
        return True
    source = Path(ui_module.resource_root()) / QML_RELATIVE_PATH
    if not source.is_file():
        raise FileNotFoundError(source)
    base_host = _accepted_v6_host(ui_module)
    previous_flag = ui_module.HUD_V5_LIVE

    class _CinematicHudV7Host(base_host):
        def __init__(self, owner, owner_name: str) -> None:
            self._v7_bootstrapping = True
            super().__init__(owner, owner_name)
            self.suspend()
            self._source = source
            self._v7_bootstrapping = False
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
            elif self._v7_bootstrapping:
                expected = "onyxLiveShellV6Root"
            else:
                expected = ROOT_OBJECT
            if (
                self._quick.status() != type(self._quick).Status.Ready
                or root is None
                or root.objectName() != expected
            ):
                self.suspend()
                raise RuntimeError(errors or "HUD V7 root failed its contract")
            self._loaded = True
            self._quick.show()

        @property
        def renderer_mode(self) -> str:
            return "qml-v7-cinematic"

    record = _InstallationRecordV7(
        ui_module=ui_module,
        base_host=base_host,
        installed_host=_CinematicHudV7Host,
        previous_flag=previous_flag,
        source=source.resolve(),
    )
    try:
        ui_module._CinematicHudV5Host = _CinematicHudV7Host
        ui_module.HUD_V5_LIVE = True
        ui_module._ONYX_HUD_V7_INSTALLATION = _INSTALLATION_TOKEN
        _ACTIVE_INSTALLATIONS[key] = record
    except Exception:
        _ACTIVE_INSTALLATIONS.pop(key, None)
        ui_module._CinematicHudV5Host = base_host
        ui_module.HUD_V5_LIVE = previous_flag
        if hasattr(ui_module, "_ONYX_HUD_V7_INSTALLATION"):
            delattr(ui_module, "_ONYX_HUD_V7_INSTALLATION")
        raise
    return True


def uninstall_candidate(ui_module: ModuleType) -> bool:
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V7_INSTALLATION", None)
    installation = _ACTIVE_INSTALLATIONS.get(key)
    if marker is None and installation is None:
        return False
    if installation is None or installation.ui_module is not ui_module:
        raise RuntimeError("HUD V7 rollback authentication failed")
    ui_module._CinematicHudV5Host = installation.base_host
    ui_module.HUD_V5_LIVE = installation.previous_flag
    _ACTIVE_INSTALLATIONS.pop(key)
    if hasattr(ui_module, "_ONYX_HUD_V7_INSTALLATION"):
        delattr(ui_module, "_ONYX_HUD_V7_INSTALLATION")
    return True


__all__ = [
    "FLAG_NAME",
    "QML_RELATIVE_PATH",
    "ROOT_OBJECT",
    "candidate_requested",
    "install_candidate",
    "uninstall_candidate",
]
