"""Default-off Docker adapter for authenticated PluginHost V1 execution."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Mapping, Sequence

from core.plugin_runtime_v1 import (
    NATIVE_SANDBOX_CONTRACT,
    NativeSandboxAttestation,
    PluginExecutionCancelled,
    native_sandbox_attestation_mac,
)

FEATURE_FLAG = "ONYX_PLUGIN_DOCKER_SANDBOX_V1"
IMAGE_ID_ENV = "ONYX_PLUGIN_DOCKER_IMAGE_ID"
DOCKER_CLI_ENV = "ONYX_PLUGIN_DOCKER_CLI"
DOCKER_HOST_ENV = "ONYX_PLUGIN_DOCKER_HOST"
DEFAULT_WINDOWS_DOCKER_HOST = "npipe:////./pipe/docker_engine"
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_NPIPE_HOST = re.compile(r"^npipe:////\./pipe/[A-Za-z0-9_.-]+$")


class PluginDockerSandboxError(RuntimeError):
    """The Docker-backed plugin boundary could not be configured safely."""


class DockerNativeSandboxV1:
    """Launch one integrity-checked test plugin in a hardened local container."""

    def __init__(
        self,
        *,
        docker_cli: Path | str,
        docker_host: str,
        image_id: str,
        attestation_key: bytes,
    ) -> None:
        cli = Path(docker_cli).expanduser()
        if not cli.is_absolute() or not cli.is_file():
            raise PluginDockerSandboxError("plugin_docker_cli_invalid")
        if os.name == "nt":
            if _NPIPE_HOST.fullmatch(docker_host) is None:
                raise PluginDockerSandboxError("plugin_docker_host_must_be_local")
        elif not docker_host.startswith("unix:///"):
            raise PluginDockerSandboxError("plugin_docker_host_must_be_local")
        if _IMAGE_ID.fullmatch(image_id) is None:
            raise PluginDockerSandboxError("plugin_docker_image_must_be_digest_pinned")
        if not isinstance(attestation_key, bytes) or len(attestation_key) < 32:
            raise PluginDockerSandboxError("plugin_docker_attestation_key_invalid")
        self.docker_cli = cli.resolve()
        self.docker_host = docker_host
        self.image_id = image_id
        self._attestation_key = attestation_key

    def attest(self, challenge: str, launch_digest: str) -> NativeSandboxAttestation:
        capability_id = f"docker:{self.image_id}"
        return NativeSandboxAttestation(
            contract=NATIVE_SANDBOX_CONTRACT,
            challenge=challenge,
            capability_id=capability_id,
            launch_digest=launch_digest,
            mac=native_sandbox_attestation_mac(
                self._attestation_key,
                challenge=challenge,
                launch_digest=launch_digest,
                capability_id=capability_id,
            ),
        )

    def _docker(self, *arguments: str) -> list[str]:
        return [str(self.docker_cli), "--host", self.docker_host, *arguments]

    def execute(
        self,
        argv: Sequence[str],
        *,
        input_text: str,
        environment: Mapping[str, str],
        cwd: Path,
        timeout_seconds: float,
        cancellation: threading.Event | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del environment
        root = Path(cwd).resolve(strict=True)
        if len(argv) != 3 or argv[1] != "-I":
            raise OSError("plugin_docker_argv_invalid")
        entrypoint = Path(argv[2]).resolve(strict=True)
        if root not in entrypoint.parents or entrypoint.suffix != ".py":
            raise OSError("plugin_docker_entrypoint_invalid")
        relative = entrypoint.relative_to(root).as_posix()
        if any(character in str(root) for character in ("\x00", "\r", "\n", ",")):
            raise OSError("plugin_docker_mount_invalid")
        container_name = f"onyx-plugin-{secrets.token_hex(16)}"
        mount = (
            f"type=bind,source={root},target=/plugin,readonly,"
            "bind-propagation=rprivate"
        )
        command = self._docker(
            "run",
            "-i",
            "--rm",
            "--name",
            container_name,
            "--pull",
            "never",
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--log-driver",
            "none",
            "--read-only",
            "--no-healthcheck",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "65532:65532",
            "--pids-limit",
            "32",
            "--memory",
            "128m",
            "--memory-swap",
            "128m",
            "--cpus",
            "0.5",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
            "--mount",
            mount,
            "--workdir",
            "/plugin",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONIOENCODING=utf-8",
            "--env",
            "PYTHONNOUSERSITE=1",
            "--entrypoint",
            "python",
            self.image_id,
            "-I",
            f"/plugin/{relative}",
        )
        if cancellation is not None:
            return self._execute_cancellable_command(
                command, container_name, input_text, timeout_seconds, cancellation,
            )
        try:
            return subprocess.run(
                command,
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(
                self._docker("rm", "--force", "--volumes", container_name),
                capture_output=True,
                timeout=10,
                check=False,
            )
            raise

    def execute_cancellable(self, argv, *, cancellation, **kwargs):
        return self.execute(argv, cancellation=cancellation, **kwargs)

    def _remove_created_container(self, name: str) -> None:
        removed = subprocess.run(
            self._docker("rm", "--force", "--volumes", name),
            capture_output=True, timeout=10, check=False,
        )
        if removed.returncode == 0:
            return
        remaining = subprocess.run(
            self._docker("container", "ls", "--all", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"),
            capture_output=True, timeout=10, check=False,
        )
        if remaining.returncode != 0 or remaining.stdout.strip():
            raise OSError("plugin_docker_cleanup_unverified")

    def _execute_cancellable_command(self, command, name, input_text, timeout_seconds, cancellation):
        """Create before start so a cancellation cannot race a late run/create.

        Official protocol: https://docs.docker.com/reference/cli/docker/container/create/
        A timed-out create can leave only an inert container, never running code.
        Cleanup uncertainty is an error, never a successful cancellation receipt.
        """
        if cancellation.is_set():
            raise PluginExecutionCancelled("plugin_cancelled_before_create")
        deadline = time.monotonic() + timeout_seconds
        create = list(command)
        create[create.index("run")] = "create"
        create.remove("--rm")
        process = None
        try:
            created = subprocess.run(create, capture_output=True, text=True, timeout=timeout_seconds, check=False)
            if created.returncode != 0:
                raise OSError("plugin_docker_create_failed")
            if cancellation.is_set():
                raise PluginExecutionCancelled("plugin_cancelled_before_start")
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            process = subprocess.Popen(
                self._docker("start", "--attach", "--interactive", name),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="strict",
            )
            pending_input = input_text
            while True:
                if cancellation.is_set():
                    raise PluginExecutionCancelled("plugin_cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                try:
                    stdout, stderr = process.communicate(pending_input, timeout=min(0.1, remaining))
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    pending_input = None
        finally:
            cleanup_failed = False
            try:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=2)
            except (OSError, subprocess.TimeoutExpired, UnicodeError):
                cleanup_failed = True
            finally:
                if process is not None:
                    for pipe in (process.stdin, process.stdout, process.stderr):
                        if pipe is not None:
                            try:
                                pipe.close()
                            except OSError:
                                cleanup_failed = True
                try:
                    self._remove_created_container(name)
                except (OSError, subprocess.TimeoutExpired):
                    cleanup_failed = True
            if cleanup_failed:
                # Never let a cleanup timeout reach the host as a run timeout:
                # that would falsely assert that the plugin was terminated.
                raise OSError("plugin_docker_cleanup_unverified")


def create_plugin_docker_sandbox_v1(
    environment: Mapping[str, str] | None = None,
) -> tuple[DockerNativeSandboxV1 | None, bytes | None]:
    """Materialize the adapter only from explicit, secret-free local settings."""

    source = os.environ if environment is None else environment
    if source.get(FEATURE_FLAG) != "true":
        return None, None
    configured_cli = source.get(DOCKER_CLI_ENV, "").strip()
    discovered_cli = configured_cli or shutil.which("docker") or ""
    image_id = source.get(IMAGE_ID_ENV, "").strip()
    docker_host = source.get(DOCKER_HOST_ENV, "").strip()
    if not docker_host and os.name == "nt":
        docker_host = DEFAULT_WINDOWS_DOCKER_HOST
    key = secrets.token_bytes(32)
    adapter = DockerNativeSandboxV1(
        docker_cli=Path(discovered_cli),
        docker_host=docker_host,
        image_id=image_id,
        attestation_key=key,
    )
    return adapter, key


__all__ = [
    "DOCKER_CLI_ENV",
    "DOCKER_HOST_ENV",
    "DockerNativeSandboxV1",
    "FEATURE_FLAG",
    "IMAGE_ID_ENV",
    "PluginDockerSandboxError",
    "create_plugin_docker_sandbox_v1",
]
