from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.plugin_docker_sandbox_v1 import (
    DockerNativeSandboxV1,
    PluginDockerSandboxError,
    create_plugin_docker_sandbox_v1,
)
from core.plugin_runtime_v1 import native_sandbox_attestation_mac


def _docker(tmp_path: Path) -> Path:
    path = tmp_path / "docker.exe"
    path.write_bytes(b"MZ")
    return path.resolve()


def test_factory_is_default_off_and_requires_a_digest_pinned_image(tmp_path) -> None:
    assert create_plugin_docker_sandbox_v1({}) == (None, None)
    with pytest.raises(PluginDockerSandboxError, match="image_must_be_digest_pinned"):
        create_plugin_docker_sandbox_v1(
            {
                "ONYX_PLUGIN_DOCKER_SANDBOX_V1": "true",
                "ONYX_PLUGIN_DOCKER_CLI": str(_docker(tmp_path)),
                "ONYX_PLUGIN_DOCKER_IMAGE_ID": "python:latest",
                "ONYX_PLUGIN_DOCKER_HOST": "npipe:////./pipe/docker_engine",
            }
        )


def test_attestation_is_bound_to_challenge_launch_and_image(tmp_path) -> None:
    key = b"plugin-docker-attestation-test-key" * 2
    image = "sha256:" + "a" * 64
    adapter = DockerNativeSandboxV1(
        docker_cli=_docker(tmp_path),
        docker_host="npipe:////./pipe/docker_engine",
        image_id=image,
        attestation_key=key,
    )
    attestation = adapter.attest("challenge", "launch")

    assert attestation.capability_id == f"docker:{image}"
    assert attestation.mac == native_sandbox_attestation_mac(
        key,
        challenge="challenge",
        launch_digest="launch",
        capability_id=f"docker:{image}",
    )


def test_execute_uses_hardened_container_and_forwards_bounded_ipc(
    tmp_path, monkeypatch
) -> None:
    key = b"plugin-docker-attestation-test-key" * 2
    adapter = DockerNativeSandboxV1(
        docker_cli=_docker(tmp_path),
        docker_host="npipe:////./pipe/docker_engine",
        image_id="sha256:" + "b" * 64,
        attestation_key=key,
    )
    entrypoint = tmp_path / "plugin.py"
    entrypoint.write_text("pass\n", encoding="utf-8")
    observed = {}

    def fake_run(command, **kwargs):
        observed.update({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = adapter.execute(
        ["host-python", "-I", str(entrypoint)],
        input_text='{"request":true}\n',
        environment={"OWNER_SECRET": "forbidden"},
        cwd=tmp_path,
        timeout_seconds=2.0,
    )

    command = observed["command"]
    assert result.returncode == 0
    assert command[command.index("run") + 1] == "-i"
    assert "--network" in command and "none" in command
    assert "--read-only" in command
    assert "--cap-drop" in command and "ALL" in command
    assert "OWNER_SECRET" not in " ".join(command)
    assert observed["input"] == '{"request":true}\n'
