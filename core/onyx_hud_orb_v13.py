"""Current teardown-guarded HUD successor over the exact installed HUD V12."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

import core.onyx_hud_orb_v12 as canonical_hud_v12


FLAG_NAME: Final = "ONYX_HUD_V13_LIVE"
ROOT_OBJECT: Final = "onyxLiveShellV12Root"
QML_RELATIVE_PATH: Final = Path("qml") / "OnyxLiveShellV12.qml"
V12_MODULE_RELATIVE_PATH: Final = Path("core") / "onyx_hud_orb_v12.py"
V12_MODULE_SHA256: Final = (
    "8d6805c29100568a45a51bbb9eed5ba1acf867a23431664286185b48acbc8f1b"
)
_INSTALLATION_TOKEN: Final = object()


@dataclass(frozen=True, slots=True)
class _InstallationRecordV13:
    ui_module: ModuleType
    hud_v12_module: ModuleType
    base_host: type
    installed_host: type
    previous_flag: object
    source: Path


_ACTIVE_INSTALLATIONS: dict[int, _InstallationRecordV13] = {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accepted_v12_host(ui_module: ModuleType, hud_v12_module: ModuleType) -> type:
    root = Path(ui_module.resource_root()).resolve()
    module_path = root / V12_MODULE_RELATIVE_PATH
    loaded_path = Path(getattr(hud_v12_module, "__file__", "")).resolve()
    if (
        loaded_path != module_path.resolve()
        or not module_path.is_file()
        or module_path.is_symlink()
        or _sha256(module_path) != V12_MODULE_SHA256
    ):
        raise RuntimeError("accepted HUD V12 artifacts failed authentication")
    installation = hud_v12_module._ACTIVE_INSTALLATIONS.get(id(ui_module))
    marker = getattr(ui_module, "_ONYX_HUD_V12_INSTALLATION", None)
    host = getattr(ui_module, "_CinematicHudV5Host", None)
    if (
        installation is None
        or installation.ui_module is not ui_module
        or installation.hud_v11_module is None
        or marker is not hud_v12_module._INSTALLATION_TOKEN
        or not isinstance(host, type)
        or installation.installed_host is not host
        or host.__module__ != hud_v12_module.__name__
        or host.__qualname__ != "_install.<locals>._CinematicHudV12Host"
        or getattr(ui_module, "HUD_V5_LIVE", None) is not True
    ):
        raise RuntimeError("accepted HUD V12 installation is unavailable")
    return host


def _accepted_direct_v5_base(ui_module: ModuleType, v12_host: type) -> type:
    """Resolve the authenticated original host without running successor swaps.

    V6 through V13 intentionally form an immutable authority chain.  Calling
    every ``__init__`` in that chain, however, used to load and clear five QML
    roots on the same ``QQuickWidget`` before the current root was retained.
    Windows UI Automation can keep accessibility listeners for those detached
    roots, which makes a later accessibility traversal fail-fast inside Qt.

    The accepted V12 class already proves the complete predecessor chain.  Its
    MRO therefore provides a closed, non-injectable route to the original V5
    resource owner; only that exact class may allocate the shared widget.
    """

    matches = [
        candidate
        for candidate in v12_host.__mro__
        if candidate.__module__ == ui_module.__name__
        and candidate.__qualname__ == "_CinematicHudV5Host"
    ]
    if len(matches) != 1:
        raise RuntimeError("accepted HUD V5 direct base is unavailable")
    return matches[0]


def candidate_requested(environ: dict[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(FLAG_NAME, "0") == "1"


def _install(
    ui_module: ModuleType,
    hud_v12_module: ModuleType,
) -> bool:
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V13_INSTALLATION", None)
    existing = _ACTIVE_INSTALLATIONS.get(key)
    if marker is not None or existing is not None:
        if (
            marker is not _INSTALLATION_TOKEN
            or existing is None
            or existing.ui_module is not ui_module
            or existing.hud_v12_module is not hud_v12_module
            or ui_module._CinematicHudV5Host is not existing.installed_host
            or ui_module.HUD_V5_LIVE is not True
        ):
            raise RuntimeError("HUD V13 installation drift denied")
        return True

    source = Path(ui_module.resource_root()) / QML_RELATIVE_PATH
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError(source)
    base_host = _accepted_v12_host(ui_module, hud_v12_module)
    previous_flag = ui_module.HUD_V5_LIVE

    class _CinematicHudV13Host(base_host):
        def __init__(self, owner, owner_name: str) -> None:
            # Allocate the one accepted QQuickWidget directly from V5, but do
            # not let V5's virtual load_source call publish its historical QML
            # root.  V12 was authenticated above, so skipping predecessor
            # constructors changes no authority or callback contract; it only
            # prevents obsolete roots from ever entering Qt's accessibility
            # tree during current-host construction.
            self._v13_bootstrapping = True
            self._v13_direct_base_bootstrapping = True
            self._v13_source_load_count = 0
            direct_base = _accepted_direct_v5_base(ui_module, base_host)
            try:
                direct_base.__init__(self, owner, owner_name)
            finally:
                self._v13_direct_base_bootstrapping = False
            self._source = source
            self._v13_bootstrapping = False
            self.load_source()

        def load_source(self) -> None:
            if getattr(self, "_v13_direct_base_bootstrapping", False):
                return
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
            self._v13_source_load_count += 1
            errors = "\n".join(error.toString() for error in self._quick.errors())
            root_object = self._quick.rootObject()
            expected = ROOT_OBJECT
            if (
                self._quick.status() != type(self._quick).Status.Ready
                or root_object is None
                or root_object.objectName() != expected
            ):
                self.suspend()
                raise RuntimeError(errors or "HUD V13 root failed its contract")
            self._loaded = True
            self._quick.show()
            self.sync_animation()

        @property
        def source_load_count(self) -> int:
            """Number of QML roots published by this current host instance."""

            return self._v13_source_load_count

        @property
        def renderer_mode(self) -> str:
            return "qml-v13-explicit-exit"

    record = _InstallationRecordV13(
        ui_module=ui_module,
        hud_v12_module=hud_v12_module,
        base_host=base_host,
        installed_host=_CinematicHudV13Host,
        previous_flag=previous_flag,
        source=source.resolve(),
    )
    try:
        ui_module._CinematicHudV5Host = _CinematicHudV13Host
        ui_module.HUD_V5_LIVE = True
        ui_module._ONYX_HUD_V13_INSTALLATION = _INSTALLATION_TOKEN
        _ACTIVE_INSTALLATIONS[key] = record
    except Exception:
        _ACTIVE_INSTALLATIONS.pop(key, None)
        ui_module._CinematicHudV5Host = base_host
        ui_module.HUD_V5_LIVE = previous_flag
        if hasattr(ui_module, "_ONYX_HUD_V13_INSTALLATION"):
            delattr(ui_module, "_ONYX_HUD_V13_INSTALLATION")
        raise
    return True


def install_candidate(
    ui_module: ModuleType,
    hud_v12_module: ModuleType | None = None,
) -> bool:
    if not candidate_requested():
        return False
    accepted_v12 = canonical_hud_v12 if hud_v12_module is None else hud_v12_module
    accepted_v12.install_current(ui_module)
    try:
        return _install(ui_module, accepted_v12)
    except BaseException:
        accepted_v12.uninstall_candidate(ui_module)
        raise


def install_current(
    ui_module: ModuleType,
    hud_v12_module: ModuleType | None = None,
) -> bool:
    """Install the packaged current HUD through an explicit local loader."""

    accepted_v12 = canonical_hud_v12 if hud_v12_module is None else hud_v12_module
    accepted_v12.install_current(ui_module)
    try:
        return _install(ui_module, accepted_v12)
    except BaseException:
        accepted_v12.uninstall_candidate(ui_module)
        raise


def uninstall_candidate(ui_module: ModuleType) -> bool:
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V13_INSTALLATION", None)
    installation = _ACTIVE_INSTALLATIONS.get(key)
    if marker is None and installation is None:
        return False
    if installation is None or installation.ui_module is not ui_module:
        raise RuntimeError("HUD V13 rollback authentication failed")
    if ui_module._CinematicHudV5Host is not installation.installed_host:
        raise RuntimeError("HUD V13 installed host drift denied")
    ui_module._CinematicHudV5Host = installation.base_host
    ui_module.HUD_V5_LIVE = installation.previous_flag
    _ACTIVE_INSTALLATIONS.pop(key)
    if hasattr(ui_module, "_ONYX_HUD_V13_INSTALLATION"):
        delattr(ui_module, "_ONYX_HUD_V13_INSTALLATION")
    installation.hud_v12_module.uninstall_candidate(ui_module)
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
