"""Durable owner-private POSIX kill signal bound to one mission digest."""

from __future__ import annotations

import re
import threading

from core.host_security_boundary_v1 import (
    HostSecurityBoundaryBusy,
    HostSecurityBoundaryError,
    TrustedDirectoryV1,
)


_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


class PosixKillSignalV1:
    """Persist a one-way kill marker through a trusted-directory authority."""

    def __init__(
        self,
        *,
        directory: TrustedDirectoryV1,
        name: str,
        binding_digest: str,
    ) -> None:
        if _SAFE_NAME.fullmatch(name) is None:
            raise HostSecurityBoundaryError("posix_kill_signal_name_invalid")
        if _DIGEST.fullmatch(binding_digest) is None:
            raise HostSecurityBoundaryError("posix_kill_signal_digest_invalid")
        self._directory = directory
        self._relative = f"kill-{name}.signal"
        self._payload = f"onyx-posix-kill-v1:{binding_digest}\n".encode("ascii")
        self._closed = False
        self._guard = threading.Lock()

    def _ensure_open(self) -> None:
        if self._closed:
            raise HostSecurityBoundaryError("posix_kill_signal_closed")

    def is_set(self) -> bool:
        with self._guard:
            self._ensure_open()
            with self._directory.session() as session:
                payload = session.read_optional(
                    self._relative,
                    max_bytes=len(self._payload),
                )
            if payload is None:
                return False
            if payload != self._payload:
                raise HostSecurityBoundaryError("posix_kill_signal_binding_mismatch")
            return True

    def set(self) -> None:
        with self._guard:
            self._ensure_open()
            with self._directory.session() as session:
                existing = session.read_optional(
                    self._relative,
                    max_bytes=len(self._payload),
                )
                if existing is None:
                    try:
                        session.publish_create(self._relative, self._payload)
                    except HostSecurityBoundaryBusy:
                        existing = session.read(
                            self._relative,
                            max_bytes=len(self._payload),
                        )
                if existing is not None and existing != self._payload:
                    raise HostSecurityBoundaryError(
                        "posix_kill_signal_binding_mismatch"
                    )

    def close(self) -> None:
        with self._guard:
            self._closed = True
