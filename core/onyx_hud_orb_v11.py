"""Current teardown-guarded HUD successor over the exact installed HUD V10."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

import core.onyx_hud_orb_v10 as canonical_hud_v10


FLAG_NAME: Final = "ONYX_HUD_V11_LIVE"
ROOT_OBJECT: Final = "onyxLiveShellV11Root"
QML_RELATIVE_PATH: Final = Path("qml") / "OnyxLiveShellV11.qml"
V10_QML_RELATIVE_PATH: Final = Path("qml") / "OnyxLiveShellV10.qml"
V10_MODULE_RELATIVE_PATH: Final = Path("core") / "onyx_hud_orb_v10.py"
V10_MODULE_SHA256: Final = (
    "057b0cb0f85434a4d980949bb6be95e9da1536b2d9c624aff8881cc35dfc8f47"
)
V10_QML_SHA256: Final = (
    "daa6c7019db1360bd333aa886a5c51250496438f2413f386bbd507a62f3f9f9b"
)
_INSTALLATION_TOKEN: Final = object()


@dataclass(frozen=True, slots=True)
class _InstallationRecordV11:
    ui_module: ModuleType
    hud_v10_module: ModuleType
    base_host: type
    installed_host: type
    previous_flag: object
    source: Path


_ACTIVE_INSTALLATIONS: dict[int, _InstallationRecordV11] = {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accepted_v10_host(ui_module: ModuleType, hud_v10_module: ModuleType) -> type:
    root = Path(ui_module.resource_root()).resolve()
    module_path = root / V10_MODULE_RELATIVE_PATH
    qml_path = root / V10_QML_RELATIVE_PATH
    loaded_path = Path(getattr(hud_v10_module, "__file__", "")).resolve()
    if (
        loaded_path != module_path.resolve()
        or not module_path.is_file()
        or module_path.is_symlink()
        or not qml_path.is_file()
        or qml_path.is_symlink()
        or _sha256(module_path) != V10_MODULE_SHA256
        or _sha256(qml_path) != V10_QML_SHA256
    ):
        raise RuntimeError("accepted HUD V10 artifacts failed authentication")
    installation = hud_v10_module._ACTIVE_INSTALLATIONS.get(id(ui_module))
    marker = getattr(ui_module, "_ONYX_HUD_V10_INSTALLATION", None)
    host = getattr(ui_module, "_CinematicHudV5Host", None)
    if (
        installation is None
        or installation.ui_module is not ui_module
        or installation.hud_v9_module is None
        or marker is not hud_v10_module._INSTALLATION_TOKEN
        or not isinstance(host, type)
        or installation.installed_host is not host
        or host.__module__ != hud_v10_module.__name__
        or host.__qualname__ != "_install.<locals>._CinematicHudV10Host"
        or installation.source.resolve() != qml_path.resolve()
        or getattr(ui_module, "HUD_V5_LIVE", None) is not True
    ):
        raise RuntimeError("accepted HUD V10 installation is unavailable")
    return host


def _accepted_direct_v5_base(ui_module: ModuleType, v10_host: type) -> type:
    """Resolve the authenticated original host without running successor swaps.

    V6 through V11 intentionally form an immutable authority chain.  Calling
    every ``__init__`` in that chain, however, used to load and clear five QML
    roots on the same ``QQuickWidget`` before the current root was retained.
    Windows UI Automation can keep accessibility listeners for those detached
    roots, which makes a later accessibility traversal fail-fast inside Qt.

    The accepted V10 class already proves the complete predecessor chain.  Its
    MRO therefore provides a closed, non-injectable route to the original V5
    resource owner; only that exact class may allocate the shared widget.
    """

    matches = [
        candidate
        for candidate in v10_host.__mro__
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
    hud_v10_module: ModuleType,
) -> bool:
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V11_INSTALLATION", None)
    existing = _ACTIVE_INSTALLATIONS.get(key)
    if marker is not None or existing is not None:
        if (
            marker is not _INSTALLATION_TOKEN
            or existing is None
            or existing.ui_module is not ui_module
            or existing.hud_v10_module is not hud_v10_module
            or ui_module._CinematicHudV5Host is not existing.installed_host
            or ui_module.HUD_V5_LIVE is not True
        ):
            raise RuntimeError("HUD V11 installation drift denied")
        return True

    source = Path(ui_module.resource_root()) / QML_RELATIVE_PATH
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError(source)
    base_host = _accepted_v10_host(ui_module, hud_v10_module)
    previous_flag = ui_module.HUD_V5_LIVE

    class _CinematicHudV11Host(base_host):
        def __init__(self, owner, owner_name: str) -> None:
            # Allocate the one accepted QQuickWidget directly from V5, but do
            # not let V5's virtual load_source call publish its historical QML
            # root.  V10 was authenticated above, so skipping predecessor
            # constructors changes no authority or callback contract; it only
            # prevents obsolete roots from ever entering Qt's accessibility
            # tree during current-host construction.
            self._v11_bootstrapping = True
            self._v11_direct_base_bootstrapping = True
            self._v11_source_load_count = 0
            direct_base = _accepted_direct_v5_base(ui_module, base_host)
            try:
                direct_base.__init__(self, owner, owner_name)
            finally:
                self._v11_direct_base_bootstrapping = False
            self._source = source
            self._v11_bootstrapping = False
            self.load_source()

        def load_source(self) -> None:
            if getattr(self, "_v11_direct_base_bootstrapping", False):
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
            self._v11_source_load_count += 1
            errors = "\n".join(error.toString() for error in self._quick.errors())
            root_object = self._quick.rootObject()
            if getattr(self, "_v6_bootstrapping", False):
                expected = "onyxLiveShellV5Root"
            elif getattr(self, "_v7_bootstrapping", False):
                expected = "onyxLiveShellV6Root"
            elif getattr(self, "_v8_bootstrapping", False):
                expected = "onyxLiveShellV7Root"
            elif getattr(self, "_v9_bootstrapping", False):
                expected = "onyxLiveShellV8Root"
            elif getattr(self, "_v10_bootstrapping", False):
                expected = "onyxLiveShellV9Root"
            elif self._v11_bootstrapping:
                expected = "onyxLiveShellV10Root"
            else:
                expected = ROOT_OBJECT
            if (
                self._quick.status() != type(self._quick).Status.Ready
                or root_object is None
                or root_object.objectName() != expected
            ):
                self.suspend()
                raise RuntimeError(errors or "HUD V11 root failed its contract")
            self._loaded = True
            self._quick.show()

        @property
        def source_load_count(self) -> int:
            """Number of QML roots published by this current host instance."""

            return self._v11_source_load_count

        @property
        def renderer_mode(self) -> str:
            return "qml-v11-explicit-exit"

    record = _InstallationRecordV11(
        ui_module=ui_module,
        hud_v10_module=hud_v10_module,
        base_host=base_host,
        installed_host=_CinematicHudV11Host,
        previous_flag=previous_flag,
        source=source.resolve(),
    )
    try:
        ui_module._CinematicHudV5Host = _CinematicHudV11Host
        ui_module.HUD_V5_LIVE = True
        ui_module._ONYX_HUD_V11_INSTALLATION = _INSTALLATION_TOKEN
        _ACTIVE_INSTALLATIONS[key] = record
    except Exception:
        _ACTIVE_INSTALLATIONS.pop(key, None)
        ui_module._CinematicHudV5Host = base_host
        ui_module.HUD_V5_LIVE = previous_flag
        if hasattr(ui_module, "_ONYX_HUD_V11_INSTALLATION"):
            delattr(ui_module, "_ONYX_HUD_V11_INSTALLATION")
        raise
    return True


def install_candidate(
    ui_module: ModuleType,
    hud_v10_module: ModuleType | None = None,
) -> bool:
    if not candidate_requested():
        return False
    accepted_v10 = canonical_hud_v10 if hud_v10_module is None else hud_v10_module
    accepted_v10.install_current(ui_module)
    try:
        return _install(ui_module, accepted_v10)
    except BaseException:
        accepted_v10.uninstall_candidate(ui_module)
        raise


def install_current(
    ui_module: ModuleType,
    hud_v10_module: ModuleType | None = None,
) -> bool:
    """Install the packaged current HUD through an explicit local loader."""

    accepted_v10 = canonical_hud_v10 if hud_v10_module is None else hud_v10_module
    accepted_v10.install_current(ui_module)
    try:
        return _install(ui_module, accepted_v10)
    except BaseException:
        accepted_v10.uninstall_candidate(ui_module)
        raise


def uninstall_candidate(ui_module: ModuleType) -> bool:
    key = id(ui_module)
    marker = getattr(ui_module, "_ONYX_HUD_V11_INSTALLATION", None)
    installation = _ACTIVE_INSTALLATIONS.get(key)
    if marker is None and installation is None:
        return False
    if installation is None or installation.ui_module is not ui_module:
        raise RuntimeError("HUD V11 rollback authentication failed")
    if ui_module._CinematicHudV5Host is not installation.installed_host:
        raise RuntimeError("HUD V11 installed host drift denied")
    ui_module._CinematicHudV5Host = installation.base_host
    ui_module.HUD_V5_LIVE = installation.previous_flag
    _ACTIVE_INSTALLATIONS.pop(key)
    if hasattr(ui_module, "_ONYX_HUD_V11_INSTALLATION"):
        delattr(ui_module, "_ONYX_HUD_V11_INSTALLATION")
    installation.hud_v10_module.uninstall_candidate(ui_module)
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
