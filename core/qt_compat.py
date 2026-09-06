"""Qt binding compatibility shim — PySide6 (LGPLv3) with PyQt6-style names.

Onyx migrated from PyQt6 (GPL-3.0) to PySide6 (LGPLv3) to remove the GPL
distribution blocker. PySide6's public API is nearly identical to PyQt6's, but
three names and the object-liveness helper differ. This module re-exports them
under their PyQt6 spellings so the (large) UI module bodies stay unchanged and
the diff is confined to import lines.

Mapping:
- ``pyqtSignal``   -> ``PySide6.QtCore.Signal``
- ``pyqtSlot``     -> ``PySide6.QtCore.Slot``
- ``pyqtProperty`` -> ``PySide6.QtCore.Property``
- ``sip.isdeleted(obj)`` -> ``not shiboken6.isValid(obj)``
- ``sip.delete(obj)`` -> ``shiboken6.delete(obj)``
"""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import Property as pyqtProperty  # noqa: F401
from PySide6.QtCore import Signal as pyqtSignal  # noqa: F401
from PySide6.QtCore import Slot as pyqtSlot  # noqa: F401


class sip:
    """Minimal ``PyQt6.sip`` compatibility surface backed by shiboken6."""

    @staticmethod
    def isdeleted(obj: object) -> bool:
        return not shiboken6.isValid(obj)

    @staticmethod
    def delete(obj: object) -> None:
        shiboken6.delete(obj)


__all__ = ["pyqtProperty", "pyqtSignal", "pyqtSlot", "sip"]
