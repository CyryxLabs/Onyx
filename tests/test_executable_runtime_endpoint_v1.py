from __future__ import annotations

import os
import socket
from pathlib import Path, PurePosixPath

import pytest

from core.executable_runtime_endpoint_v1 import executable_runtime_endpoint_v1
from core.host_security_boundary_v1 import HostSecurityBoundaryError


def test_windows_named_pipe_is_exact_and_typed() -> None:
    endpoint = executable_runtime_endpoint_v1(
        "npipe:////./pipe/docker_engine",
        platform_name="Windows",
    )

    assert endpoint.transport == "windows_named_pipe"
    assert endpoint.address == "npipe:////./pipe/docker_engine"
    assert endpoint.socket_path is None
    assert endpoint.command_value() == endpoint.address
    assert endpoint.is_local is True


@pytest.mark.parametrize(
    "value",
    [
        "tcp://127.0.0.1:2375",
        "ssh://localhost",
        "unix:///var/run/docker.sock",
        "npipe:////./pipe/../escape",
        "npipe:////./pipe/docker engine",
        "npipe:////./pipe/docker_engine\n",
    ],
)
def test_windows_endpoint_rejects_nonlocal_or_noncanonical_values(value: str) -> None:
    with pytest.raises(HostSecurityBoundaryError):
        executable_runtime_endpoint_v1(value, platform_name="Windows")


def test_posix_unix_socket_can_be_validated_before_creation() -> None:
    candidate = PurePosixPath("/var/run/onyx-runtime.sock")
    endpoint = executable_runtime_endpoint_v1(
        f"unix://{candidate}",
        platform_name="Linux",
        require_existing=False,
    )

    assert endpoint.transport == "posix_unix_socket"
    assert endpoint.address == f"unix://{candidate}"
    assert endpoint.socket_path == candidate


@pytest.mark.parametrize(
    "value",
    [
        "tcp://127.0.0.1:2375",
        "ssh://localhost",
        "unix://relative.sock",
        "unix:////tmp/runtime.sock",
        "unix:///tmp/../tmp/runtime.sock",
        "unix:///tmp\\runtime.sock",
        "unix:///tmp/runtime socket",
        "npipe:////./pipe/docker_engine",
    ],
)
def test_posix_endpoint_rejects_remote_relative_or_ambiguous_values(value: str) -> None:
    with pytest.raises(HostSecurityBoundaryError):
        executable_runtime_endpoint_v1(
            value,
            platform_name="Linux",
            require_existing=False,
        )


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX paths")
def test_posix_endpoint_rejects_linked_existing_component(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("host does not allow test symlinks")

    with pytest.raises(HostSecurityBoundaryError, match="path_linked"):
        executable_runtime_endpoint_v1(
            f"unix://{linked / 'runtime.sock'}",
            platform_name="Linux",
            require_existing=False,
        )


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX paths")
def test_posix_endpoint_requires_socket_when_path_exists(tmp_path: Path) -> None:
    regular = tmp_path / "runtime.sock"
    regular.write_bytes(b"not-a-socket")

    with pytest.raises(HostSecurityBoundaryError, match="not_socket"):
        executable_runtime_endpoint_v1(
            f"unix://{regular}",
            platform_name="Darwin",
            require_existing=False,
        )


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX paths")
def test_posix_endpoint_requires_existing_by_default(tmp_path: Path) -> None:
    with pytest.raises(HostSecurityBoundaryError, match="unavailable"):
        executable_runtime_endpoint_v1(
            f"unix://{tmp_path / 'missing.sock'}",
            platform_name="Linux",
        )


@pytest.mark.skipif(os.name != "posix", reason="requires native AF_UNIX socket")
def test_native_posix_socket_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        endpoint = executable_runtime_endpoint_v1(
            f"unix://{path}",
            platform_name="Linux",
        )
        assert endpoint.socket_path == path
    finally:
        server.close()


def test_unknown_host_fails_closed() -> None:
    with pytest.raises(HostSecurityBoundaryError, match="host_unsupported"):
        executable_runtime_endpoint_v1(
            "unix:///tmp/runtime.sock",
            platform_name="FreeBSD",
            require_existing=False,
        )
