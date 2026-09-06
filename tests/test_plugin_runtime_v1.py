from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from core.plugin_runtime_v1 import (
    NATIVE_SANDBOX_CONTRACT,
    NativeSandboxAttestation,
    PluginContractError,
    PluginHostV1,
    native_sandbox_attestation_mac,
)

ATTESTATION_KEY = b"test-native-sandbox-attestation-key-v1"


class _AuthenticatedNativeSandbox:
    def __init__(self, *, tamper: str | None = None) -> None:
        self.tamper = tamper
        self.executions = 0

    def attest(
        self, challenge: str, launch_digest: str
    ) -> NativeSandboxAttestation:
        attestation = NativeSandboxAttestation(
            contract=NATIVE_SANDBOX_CONTRACT,
            challenge=challenge,
            capability_id="test-native-sandbox",
            launch_digest=launch_digest,
            mac=native_sandbox_attestation_mac(
                ATTESTATION_KEY,
                challenge=challenge,
                launch_digest=launch_digest,
                capability_id="test-native-sandbox",
            ),
        )
        if self.tamper == "challenge":
            return replace(attestation, challenge="attacker-controlled")
        if self.tamper == "digest":
            return replace(attestation, launch_digest="0" * 64)
        if self.tamper == "mac":
            return replace(attestation, mac="0" * 64)
        return attestation

    def execute(
        self,
        argv: list[str],
        *,
        input_text: str,
        environment: dict[str, str],
        cwd: Path,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        self.executions += 1
        return subprocess.run(
            argv,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            env=environment,
            cwd=cwd,
            timeout=timeout_seconds,
            check=False,
        )


class _DeterministicTimeoutSandbox(_AuthenticatedNativeSandbox):
    def execute(
        self,
        argv: list[str],
        *,
        input_text: str,
        environment: dict[str, str],
        cwd: Path,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        self.executions += 1
        raise subprocess.TimeoutExpired(argv, timeout_seconds)


class _CleanupTrackingNativeSandbox(_AuthenticatedNativeSandbox):
    def __init__(self) -> None:
        super().__init__()
        self.process: subprocess.Popen[str] | None = None
        self.terminated = False
        self.reaped = False

    def execute(
        self,
        argv: list[str],
        *,
        input_text: str,
        environment: dict[str, str],
        cwd: Path,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        self.executions += 1
        with subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            env=environment,
            cwd=cwd,
        ) as process:
            self.process = process
            try:
                stdout, stderr = process.communicate(input_text, timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                self.terminated = True
                process.communicate()
                self.reaped = process.poll() is not None
                raise
            return subprocess.CompletedProcess(
                argv, process.returncode, stdout=stdout, stderr=stderr
            )


def _plugin(tmp_path: Path, source: str | None = None, **overrides: object) -> Path:
    root = tmp_path / "plugin"
    root.mkdir(exist_ok=True)
    entrypoint = root / "plugin.py"
    if source is None:
        source = (Path(__file__).parents[1] / "plugins" / "_template.py").read_text(
            encoding="utf-8"
        )
    entrypoint.write_text(source, encoding="utf-8")
    manifest = {
        "manifest_version": 1,
        "protocol_version": "onyx.plugin/v1",
        "plugin_id": "test.echo",
        "version": "1.0.0",
        "entrypoint": "plugin.py",
        "workspace_id": "workspace-a",
        "source": "onyx-clean-room-test",
        "content_digest": hashlib.sha256(entrypoint.read_bytes()).hexdigest(),
        "license": "Proprietary-Test-Only",
        "requested_capabilities": ["test.echo"],
        "trust": "test-only",
    }
    manifest.update(overrides)
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _host(
    tmp_path: Path,
    *,
    enabled: bool = False,
    attested: bool = False,
    sandbox: _AuthenticatedNativeSandbox | None = None,
    timeout: float = 2.0,
) -> PluginHostV1:
    return PluginHostV1(
        tmp_path / "registry.json",
        workspace_id="workspace-a",
        allow_trusted_test_plugins=enabled,
        native_sandbox=sandbox or (_AuthenticatedNativeSandbox() if attested else None),
        native_sandbox_attestation_key=(
            ATTESTATION_KEY if attested or sandbox is not None else None
        ),
        timeout_seconds=timeout,
    )


def test_default_off_lifecycle_and_restart_recovery(tmp_path: Path) -> None:
    host = _host(tmp_path)
    installed = host.install(_plugin(tmp_path), approved_capabilities=["test.echo"])
    assert installed["state"] == "disabled"
    host.enable("test.echo")
    recovered = _host(tmp_path)
    assert recovered.inspect("test.echo")["state"] == "enabled"
    with pytest.raises(PluginContractError, match="disabled by default") as rejected:
        recovered.execute("test.echo", "test.echo", {"value": 1})
    assert rejected.value.code == "execution_disabled"
    recovered.disable("test.echo")
    removed = recovered.remove("test.echo")
    assert [event["event"] for event in removed["lifecycle"]][-2:] == [
        "disabled",
        "removed",
    ]
    assert recovered.list() == []


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"unexpected": True}, "invalid_manifest_fields"),
        ({"protocol_version": "onyx.plugin/v2"}, "unsupported_protocol"),
        ({"requested_capabilities": ["network"]}, "unknown_capability"),
        ({"trust": "untrusted"}, "untrusted_blocked"),
        ({"workspace_id": "workspace-b"}, "workspace_mismatch"),
        ({"entrypoint": "../escape.py"}, "invalid_entrypoint"),
    ],
)
def test_manifest_and_authority_fail_closed(
    tmp_path: Path, override: dict[str, object], code: str
) -> None:
    with pytest.raises(PluginContractError) as rejected:
        _host(tmp_path).install(_plugin(tmp_path, **override))
    assert rejected.value.code == code


def test_digest_tamper_blocks_install_and_execution(tmp_path: Path) -> None:
    manifest = _plugin(tmp_path, content_digest="0" * 64)
    with pytest.raises(PluginContractError) as rejected:
        _host(tmp_path).install(manifest)
    assert rejected.value.code == "digest_mismatch"
    manifest = _plugin(tmp_path)
    host = _host(tmp_path, enabled=True, attested=True)
    host.install(manifest, approved_capabilities=["test.echo"])
    host.enable("test.echo")
    (manifest.parent / "plugin.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )
    with pytest.raises(PluginContractError) as changed:
        host.execute("test.echo", "test.echo", None)
    assert changed.value.code == "runtime_integrity_failure"


def test_explicit_trusted_test_execution_uses_typed_authenticated_ipc(
    tmp_path: Path,
) -> None:
    host = _host(tmp_path, enabled=True, attested=True)
    host.install(_plugin(tmp_path), approved_capabilities=["test.echo"])
    host.enable("test.echo")
    response = host.execute("test.echo", "test.echo", {"unicode": "Olá"})
    assert response["result"] == {"unicode": "Olá"}
    assert "auth" not in response
    with pytest.raises(PluginContractError) as denied:
        host.execute("test.echo", "filesystem", {})
    assert denied.value.code == "capability_denied"


def test_child_receives_sanitized_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = """import json, os, sys
r=json.loads(sys.stdin.readline())
out={'protocol_version':r['protocol_version'],'type':'response','auth':r['auth'],'ok':True,'result':sorted(os.environ)}
print(json.dumps(out))
"""
    monkeypatch.setenv("ONYX_OWNER_SECRET", "must-not-leak")
    host = _host(tmp_path, enabled=True, attested=True)
    host.install(_plugin(tmp_path, source), approved_capabilities=["test.echo"])
    host.enable("test.echo")
    keys = host.execute("test.echo", "test.echo", None)["result"]
    assert "ONYX_OWNER_SECRET" not in keys
    assert set(keys) <= {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TMP",
        "TEMP",
        "PYTHONIOENCODING",
        "PYTHONNOUSERSITE",
        "LC_CTYPE",
    }


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("raise RuntimeError('boom')", "plugin_crash"),
        ("print('not-json')", "malformed_ipc"),
        (
            "import json,sys; r=json.loads(sys.stdin.readline()); print(json.dumps({'protocol_version':r['protocol_version'],'type':'response','auth':'wrong','ok':True,'result':None}))",
            "ipc_auth_failed",
        ),
    ],
)
def test_crash_malformed_and_auth_fail_closed(
    tmp_path: Path, source: str, code: str
) -> None:
    host = _host(tmp_path, enabled=True, attested=True)
    host.install(_plugin(tmp_path, source), approved_capabilities=["test.echo"])
    host.enable("test.echo")
    with pytest.raises(PluginContractError) as rejected:
        host.execute("test.echo", "test.echo", {})
    assert rejected.value.code == code


def test_timeout_classification_is_deterministic(tmp_path: Path) -> None:
    sandbox = _DeterministicTimeoutSandbox()
    host = _host(tmp_path, enabled=True, sandbox=sandbox)
    host.install(_plugin(tmp_path), approved_capabilities=["test.echo"])
    host.enable("test.echo")

    with pytest.raises(PluginContractError) as rejected:
        host.execute("test.echo", "test.echo", {})

    assert rejected.value.code == "plugin_timeout"
    assert sandbox.executions == 1


def test_real_timeout_terminates_child_and_closes_pipes(tmp_path: Path) -> None:
    sandbox = _CleanupTrackingNativeSandbox()
    host = _host(tmp_path, enabled=True, sandbox=sandbox, timeout=1.0)
    host.install(
        _plugin(tmp_path, "import time; time.sleep(30)"),
        approved_capabilities=["test.echo"],
    )
    host.enable("test.echo")

    with pytest.raises(PluginContractError) as rejected:
        host.execute("test.echo", "test.echo", {})

    assert rejected.value.code == "plugin_timeout"
    assert sandbox.terminated
    assert sandbox.reaped
    assert sandbox.process is not None
    assert sandbox.process.poll() is not None
    assert sandbox.process.stdin is not None and sandbox.process.stdin.closed
    assert sandbox.process.stdout is not None and sandbox.process.stdout.closed
    assert sandbox.process.stderr is not None and sandbox.process.stderr.closed


def test_path_read_plugin_never_starts_without_native_sandbox_attestation(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "plugin-started"
    source = f"""from pathlib import Path
Path({str(marker)!r}).write_text(Path({str(Path(__file__))!r}).read_text())
"""
    host = _host(tmp_path, enabled=True)
    host.install(_plugin(tmp_path, source), approved_capabilities=["test.echo"])
    host.enable("test.echo")

    with pytest.raises(PluginContractError) as rejected:
        host.execute("test.echo", "test.echo", {})

    assert rejected.value.code == "native_sandbox_required"
    assert not marker.exists()


@pytest.mark.parametrize("tamper", ["challenge", "digest", "mac"])
def test_forged_attestation_never_dispatches_plugin(
    tmp_path: Path, tamper: str
) -> None:
    sandbox = _AuthenticatedNativeSandbox(tamper=tamper)
    host = _host(tmp_path, enabled=True, sandbox=sandbox)
    host.install(_plugin(tmp_path), approved_capabilities=["test.echo"])
    host.enable("test.echo")

    with pytest.raises(PluginContractError) as rejected:
        host.execute("test.echo", "test.echo", {})

    assert rejected.value.code == "native_sandbox_attestation_failed"
    assert sandbox.executions == 0


def test_missing_attestation_key_denies_before_dispatch(tmp_path: Path) -> None:
    sandbox = _AuthenticatedNativeSandbox()
    host = PluginHostV1(
        tmp_path / "registry.json",
        workspace_id="workspace-a",
        allow_trusted_test_plugins=True,
        native_sandbox=sandbox,
    )
    host.install(_plugin(tmp_path), approved_capabilities=["test.echo"])
    host.enable("test.echo")

    with pytest.raises(PluginContractError) as rejected:
        host.execute("test.echo", "test.echo", {})

    assert rejected.value.code == "native_sandbox_required"
    assert sandbox.executions == 0


def test_cli_is_machine_readable_and_nonzero_on_rejection(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "scripts/onyx_plugin_cli.py",
        "--registry",
        str(tmp_path / "registry.json"),
        "--workspace",
        "workspace-a",
        "inspect",
        "missing",
    ]
    completed = subprocess.run(
        command,
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["error"]["code"] == "not_installed"
