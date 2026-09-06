"""Session-local undo journal for state changes performed by Onyx.

The journal stores only bounded reverse callables.  It never guesses a prior
state and it is deliberately not persisted across launches: a closure is valid
only while the process that observed the original state is still alive.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable


MAX_DEPTH = 16
MAX_AGE_SECONDS = 30 * 60


@dataclass(frozen=True)
class UndoEntryV1:
    label: str
    reverse: Callable[[], str]
    created_at: float = field(default_factory=time.monotonic)


_entries: list[UndoEntryV1] = []
_lock = threading.Lock()


def register_undo(label: str, reverse: Callable[[], str]) -> None:
    """Register one successful Onyx mutation without affecting its outcome."""

    if not callable(reverse):
        return
    try:
        entry = UndoEntryV1(label=str(label).strip()[:160], reverse=reverse)
        with _lock:
            _entries.append(entry)
            del _entries[:-MAX_DEPTH]
    except Exception:
        # A journal bookkeeping failure must never turn a completed operation
        # into a reported failure.
        return


def history() -> list[str]:
    with _lock:
        return [entry.label for entry in reversed(_entries)]


def peek() -> str:
    with _lock:
        return _entries[-1].label if _entries else ""


def undo_last() -> str:
    """Reverse the newest registered operation exactly once."""

    with _lock:
        entry = _entries.pop() if _entries else None
    if entry is None:
        return "There is nothing from this Onyx session to undo."
    if time.monotonic() - entry.created_at > MAX_AGE_SECONDS:
        return f"Could not undo '{entry.label}': the reversal window expired"
    try:
        detail = str(entry.reverse() or "").strip()
    except Exception as exc:  # noqa: BLE001 - report a fail-closed reversal
        return f"Could not undo '{entry.label}': {exc}"
    suffix = f" {detail}" if detail else ""
    return f"Undone: {entry.label}.{suffix}"


def clear() -> None:
    with _lock:
        _entries.clear()
