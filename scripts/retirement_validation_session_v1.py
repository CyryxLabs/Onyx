"""Bound redundant predecessor traversal to one verification transaction.

Frozen verifiers call a predecessor both for its route count and its claims.
Memoize that pure traversal only while one outer verification is executing;
never cache file hashes, exceptions, or authority across verification calls.
This helper is test orchestration, not installed runtime authorization.
"""

from __future__ import annotations

from copy import deepcopy
from contextvars import ContextVar
from functools import wraps
from importlib import import_module
from pathlib import Path
from threading import RLock
from typing import Callable, TypeVar

_LOCK = RLock()
_VERSIONS = (1, *range(16, 31))
_ACTIVE: ContextVar[dict | None] = ContextVar("onyx_retirement_validation", default=None)
T = TypeVar("T")


def install() -> Callable[[], None]:
    """Install traversal wrappers; each outer claims call gets a fresh cache."""
    with _LOCK:
        originals = []
        try:
            for version in _VERSIONS:
                module = import_module(
                    f"scripts.verify_current_successor_retirement_v{version}"
                )
                original = module._current_claims
                originals.append((module, original))

                def bind(function, default, identity):
                    @wraps(function)
                    def cached(project=default):
                        cache = _ACTIVE.get()
                        token = None
                        if cache is None:
                            cache = {}
                            token = _ACTIVE.set(cache)
                        try:
                            # Preserve path spelling; never cache a file hash.
                            key = (identity, str(Path(project).absolute()))
                            if key not in cache:
                                cache[key] = deepcopy(function(project))
                            return deepcopy(cache[key])
                        finally:
                            if token is not None:
                                _ACTIVE.reset(token)

                    return cached

                module._current_claims = bind(original, module.PROJECT, object())
        except BaseException:
            for module, original in reversed(originals):
                module._current_claims = original
            raise

        def restore():
            with _LOCK:
                for module, original in reversed(originals):
                    module._current_claims = original

        return restore


def validate_once(operation: Callable[[], T]) -> T:
    """Temporarily install traversal deduplication for a standalone verifier."""
    with _LOCK:
        restore = install()
        try:
            return operation()
        finally:
            restore()
