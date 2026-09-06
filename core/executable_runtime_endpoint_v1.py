"""Typed local runtime endpoints for portable executable sandboxes.

This module validates endpoint identity only.  It does not activate a sandbox,
open a transport, or modify the Windows V15/V19 activation contract.
"""

from __future__ import annotations

import os
import platform
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from core.host_security_boundary_v1 import HostSecurityBoundaryError


RuntimeTransportV1 = Literal["windows_named_pipe", "posix_unix_socket"]
_WINDOWS_PIPE = re.compile(r"npipe:////\./pipe/([A-Za-z0-9][A-Za-z0-9_.-]{0,95})")
_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]")
_MAX_UNIX_SOCKET_BYTES = 103


def _host_family(value: str | None) -> Literal["windows", "posix"]:
    selected = platform.system() if value is None else value
    if selected == "Windows":
        return "windows"
    if selected in {"Darwin", "Linux"}:
        return "posix"
    raise HostSecurityBoundaryError("executable_runtime_host_unsupported")


def _reject_linked_existing_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise HostSecurityBoundaryError("executable_runtime_socket_path_linked")


@dataclass(frozen=True, slots=True)
class ExecutableRuntimeEndpointV1:
    """Canonical, host-bound local endpoint accepted by an executable runtime."""

    transport: RuntimeTransportV1
    address: str
    socket_path: PurePosixPath | None = None

    @classmethod
    def parse(
        cls,
        value: str,
        *,
        platform_name: str | None = None,
        require_existing: bool = True,
    ) -> "ExecutableRuntimeEndpointV1":
        if (
            not isinstance(value, str)
            or not value
            or _CONTROL_OR_SPACE.search(value) is not None
            or type(require_existing) is not bool
        ):
            raise HostSecurityBoundaryError("executable_runtime_endpoint_invalid")
        family = _host_family(platform_name)
        if family == "windows":
            if _WINDOWS_PIPE.fullmatch(value) is None:
                raise HostSecurityBoundaryError("executable_runtime_named_pipe_invalid")
            return cls(transport="windows_named_pipe", address=value)

        if not value.startswith("unix://"):
            raise HostSecurityBoundaryError("executable_runtime_unix_socket_invalid")
        raw_path = value.removeprefix("unix://")
        path = PurePosixPath(raw_path)
        if (
            not raw_path.startswith("/")
            or raw_path.startswith("//")
            or "\\" in raw_path
            or not path.is_absolute()
            or any(part in {".", ".."} for part in path.parts)
            or str(path) != raw_path
            or len(os.fsencode(raw_path)) > _MAX_UNIX_SOCKET_BYTES
        ):
            raise HostSecurityBoundaryError("executable_runtime_unix_socket_invalid")
        if os.name != "posix":
            if require_existing:
                raise HostSecurityBoundaryError(
                    "executable_runtime_native_validation_unavailable"
                )
        else:
            native_path = Path(raw_path)
            _reject_linked_existing_components(native_path)
            try:
                info = native_path.lstat()
            except FileNotFoundError:
                if require_existing:
                    raise HostSecurityBoundaryError(
                        "executable_runtime_unix_socket_unavailable"
                    ) from None
            else:
                if not stat.S_ISSOCK(info.st_mode):
                    raise HostSecurityBoundaryError(
                        "executable_runtime_unix_socket_not_socket"
                    )
        return cls(
            transport="posix_unix_socket",
            address=f"unix://{path}",
            socket_path=path,
        )

    @property
    def is_local(self) -> bool:
        return True

    def command_value(self) -> str:
        """Return the exact canonical value for a local runtime CLI."""

        return self.address


def executable_runtime_endpoint_v1(
    value: str,
    *,
    platform_name: str | None = None,
    require_existing: bool = True,
) -> ExecutableRuntimeEndpointV1:
    """Validate and type one host-local executable runtime endpoint."""

    return ExecutableRuntimeEndpointV1.parse(
        value,
        platform_name=platform_name,
        require_existing=require_existing,
    )
