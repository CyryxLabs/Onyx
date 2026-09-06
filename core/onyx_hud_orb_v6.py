"""Default-off HUD/Orb V6 visual candidate for the accepted V5 runtime.

The module deliberately leaves ``ui.py`` and the accepted V5 files untouched.
Calling :func:`install_candidate` swaps only the V5 host class in memory and
only when ``ONYX_HUD_V6_CANDIDATE`` is exactly ``"1"``.  The established V5
projection, callbacks, governor, fallback and one-QQuickWidget lifecycle remain
authoritative.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import ModuleType
from typing import Final

FLAG_NAME: Final = "ONYX_HUD_V6_CANDIDATE"
ROOT_OBJECT: Final = "onyxLiveShellV6Root"
QML_RELATIVE_PATH: Final = Path("qml") / "OnyxLiveShellV6.qml"


def candidate_requested(environ: dict[str, str] | None = None) -> bool:
    """Return true only for the canonical, explicit candidate opt-in."""

    source = os.environ if environ is None else environ
    return source.get(FLAG_NAME, "0") == "1"


def install_candidate(ui_module: ModuleType) -> bool:
    """Install the visual host into ``ui_module`` without touching disk state.

    The mutation is transactional: validation occurs before the accepted V5
    class reference or activation boolean is changed. Repeated installation is
    idempotent. The caller can restore the exact previous state with
    :func:`uninstall_candidate`.
    """

    if not candidate_requested():
        return False
    existing = getattr(ui_module, "_ONYX_HUD_V6_INSTALLATION", None)
    if existing is not None:
        return True

    source = Path(ui_module.resource_root()) / QML_RELATIVE_PATH
    if not source.is_file():
        raise FileNotFoundError(source)

    base_host = ui_module._CinematicHudV5Host
    previous_flag = ui_module.HUD_V5_LIVE

    class _CinematicHudV6Host(base_host):
        """The accepted V5 host with a new source and root contract only."""

        def __init__(self, owner, owner_name: str) -> None:
            self._v6_bootstrapping = True
            super().__init__(owner, owner_name)
            # V5 has already proven the scene-graph/projection boundary. Swap
            # sources on the same widget, never allocate a second renderer.
            self.suspend()
            self._source = source
            self._v6_bootstrapping = False
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
            expected_root = (
                "onyxLiveShellV5Root" if self._v6_bootstrapping else ROOT_OBJECT
            )
            if (
                self._quick.status() != type(self._quick).Status.Ready
                or root is None
                or root.objectName() != expected_root
            ):
                self.suspend()
                raise RuntimeError(errors or "HUD V6 root failed its contract")
            self._loaded = True
            self._quick.show()

        @property
        def renderer_mode(self) -> str:
            return "qml-v6-candidate"

    try:
        ui_module._CinematicHudV5Host = _CinematicHudV6Host
        ui_module.HUD_V5_LIVE = True
        ui_module._ONYX_HUD_V6_INSTALLATION = {
            "base_host": base_host,
            "previous_flag": previous_flag,
            "source": str(source),
        }
    except Exception:
        ui_module._CinematicHudV5Host = base_host
        ui_module.HUD_V5_LIVE = previous_flag
        raise
    return True


def uninstall_candidate(ui_module: ModuleType) -> bool:
    """Restore the exact pre-install V5 class reference and flag."""

    installation = getattr(ui_module, "_ONYX_HUD_V6_INSTALLATION", None)
    if installation is None:
        return False
    ui_module._CinematicHudV5Host = installation["base_host"]
    ui_module.HUD_V5_LIVE = installation["previous_flag"]
    delattr(ui_module, "_ONYX_HUD_V6_INSTALLATION")
    return True


__all__ = [
    "FLAG_NAME",
    "QML_RELATIVE_PATH",
    "ROOT_OBJECT",
    "candidate_requested",
    "install_candidate",
    "uninstall_candidate",
]
