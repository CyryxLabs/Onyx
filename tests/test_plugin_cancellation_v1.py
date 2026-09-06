"""Actual concurrent latch regression and controlled Docker process lifecycle."""

import io
import hashlib
import json
import subprocess
import threading

import pytest

from core import permission_broker
from core.capability_expansion_runtime_v1 import CapabilityExpansionDenied
from core.capability_expansion_service_v1 import CapabilityExpansionServiceV1
from core.plugin_docker_sandbox_v1 import DockerNativeSandboxV1
from core.plugin_runtime_v1 import (
    NATIVE_SANDBOX_CONTRACT, NativeSandboxAttestation, PluginContractError,
    PluginExecutionCancelled, PluginHostV1, native_sandbox_attestation_mac,
)


@pytest.mark.parametrize("operation", ["kill", "revoke"])
def test_service_can_cancel_while_plugin_callback_is_running(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(permission_broker, "_audit_healthy", True)
    monkeypatch.setattr(permission_broker, "authorize_capability_operation", lambda *a: (True, "approved"))
    service = CapabilityExpansionServiceV1(
        tmp_path, owner_profile_id="owner", workspace_id="workspace",
        config={"ONYX_PLUGIN_RUNTIME_V1": True}, environ={},
    )
    entered, finished, stopped = threading.Event(), threading.Event(), threading.Event()
    errors = []

    def plugin(*_args):
        entered.set()
        assert service.plugin._cancelled.wait(2), "kill was blocked by the callback"
        raise PluginContractError("plugin_cancelled", "cancelled")

    monkeypatch.setattr(service.plugin, "execute", plugin)

    def execute():
        try:
            service.dispatch_model({"capability": "plugin", "operation": "execute", "plugin_id": "test.echo", "plugin_operation": "test.echo"})
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    def stop():
        service.kill() if operation == "kill" else service.revoke("plugin")
        stopped.set()

    worker = threading.Thread(target=execute)
    worker.start()
    stopper = threading.Thread(target=stop)
    try:
        assert entered.wait(2)
        stopper.start()
        assert stopped.wait(0.5), "stop cannot wait for plugin completion"
        assert finished.wait(1)
        assert len(errors) == 1 and isinstance(errors[0], PluginContractError)
        assert errors[0].code == "plugin_cancelled"
        with pytest.raises(CapabilityExpansionDenied):
            service.dispatch_model({"capability": "plugin", "operation": "list"})
    finally:
        service.plugin._cancelled.set()
        worker.join(3)
        if stopper.ident is not None:
            stopper.join(3)


def _adapter(tmp_path):
    cli = tmp_path / "docker.exe"
    cli.write_bytes(b"test-only")
    plugin = tmp_path / "plugin.py"
    plugin.write_text("pass\n")
    return DockerNativeSandboxV1(
        docker_cli=cli.resolve(), docker_host="npipe:////./pipe/docker_engine",
        image_id="sha256:" + "a" * 64, attestation_key=b"k" * 32,
    ), plugin


@pytest.mark.parametrize("mode", ["success", "cancel", "timeout", "cleanup-failed", "cleanup-timeout", "reap-timeout"])
def test_docker_cancellation_reaps_client_and_verifies_container_cleanup(tmp_path, monkeypatch, mode):
    adapter, plugin = _adapter(tmp_path)
    cancellation = threading.Event()
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert "--host" in command
        if mode == "cleanup-timeout" and "rm" in command:
            raise subprocess.TimeoutExpired(command, 10)
        failed_cleanup = mode == "cleanup-failed" and ("rm" in command or "ls" in command)
        return subprocess.CompletedProcess(command, 1 if failed_cleanup else 0, "", "")

    class Process:
        def __init__(self, command, **kwargs):
            commands.append(command)
            self.returncode = None
            self.killed = False
            self.stdin, self.stdout, self.stderr = io.StringIO(), io.StringIO(), io.StringIO()

        def communicate(self, input=None, timeout=None):
            if mode == "reap-timeout" and self.killed:
                raise subprocess.TimeoutExpired("reap", timeout)
            if mode == "success" or self.killed:
                self.returncode = 0
                return "{}\n", ""
            if mode != "timeout":
                cancellation.set()
            raise subprocess.TimeoutExpired("controlled-process", timeout)

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

    processes = []
    def popen(*args, **kwargs):
        process = Process(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", popen)
    def execute():
        return adapter.execute_cancellable(
            ["python", "-I", str(plugin)], input_text="{}\n", environment={},
            cwd=tmp_path, timeout_seconds=0.05, cancellation=cancellation,
        )
    if mode == "success":
        assert execute().stdout == "{}\n"
    elif mode == "timeout":
        with pytest.raises(subprocess.TimeoutExpired):
            execute()
    elif mode in {"cleanup-failed", "cleanup-timeout", "reap-timeout"}:
        with pytest.raises(OSError, match="cleanup_unverified") as failure:
            execute()
        assert not isinstance(failure.value, PluginExecutionCancelled)
    else:
        with pytest.raises(PluginExecutionCancelled):
            execute()
    assert "create" in commands[0] and "start" in commands[1]
    assert "--network" in commands[0] and "none" in commands[0]
    assert "--pull" in commands[0] and "never" in commands[0]
    assert "--read-only" in commands[0] and "--rm" not in commands[0]
    name = commands[0][commands[0].index("--name") + 1]
    removal = next(command for command in commands if "rm" in command)
    assert removal[-1] == name and name.startswith("onyx-plugin-")
    assert processes[0].poll() is not None
    assert all(pipe.closed for pipe in (processes[0].stdin, processes[0].stdout, processes[0].stderr))
    if mode != "success":
        assert processes[0].killed


def test_precancelled_sandbox_never_creates_a_container(tmp_path, monkeypatch):
    adapter, plugin = _adapter(tmp_path)
    cancellation = threading.Event()
    cancellation.set()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("must not invoke Docker"))
    with pytest.raises(PluginExecutionCancelled):
        adapter.execute_cancellable(["python", "-I", str(plugin)], input_text="{}", environment={}, cwd=tmp_path, timeout_seconds=2, cancellation=cancellation)


def test_real_plugin_host_propagates_cancellation_to_authenticated_sandbox(tmp_path):
    key = b"k" * 32
    entered = threading.Event()
    outcomes = []
    class Sandbox:
        def attest(self, challenge, launch_digest):
            return NativeSandboxAttestation(
                NATIVE_SANDBOX_CONTRACT, challenge, "test-cancellable", launch_digest,
                native_sandbox_attestation_mac(key, challenge=challenge, launch_digest=launch_digest, capability_id="test-cancellable"),
            )

        def execute(self, *a, **kw):
            pytest.fail("host must select the cancellable adapter")

        def execute_cancellable(self, *a, cancellation, **kw):
            entered.set()
            assert cancellation.wait(2)
            raise PluginExecutionCancelled("cleanup verified by controlled adapter")

    entry = tmp_path / "plugin.py"
    entry.write_text("pass\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "manifest_version": 1, "protocol_version": "onyx.plugin/v1",
        "plugin_id": "test.echo", "version": "1.0.0", "entrypoint": "plugin.py",
        "workspace_id": "workspace", "source": "onyx-test", "license": "test-only",
        "content_digest": hashlib.sha256(entry.read_bytes()).hexdigest(),
        "requested_capabilities": ["test.echo"], "trust": "test-only",
    }))
    host = PluginHostV1(tmp_path / "registry.json", workspace_id="workspace", allow_trusted_test_plugins=True, native_sandbox=Sandbox(), native_sandbox_attestation_key=key)
    host.install(manifest, approved_capabilities=["test.echo"])
    host.enable("test.echo")
    def execute():
        try:
            host.execute("test.echo", "test.echo", {})
        except BaseException as exc:
            outcomes.append(exc)
    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert entered.wait(2)
        host.cancel()
        worker.join(2)
        assert not worker.is_alive()
        assert len(outcomes) == 1 and isinstance(outcomes[0], PluginContractError)
        assert outcomes[0].code == "plugin_cancelled"
        assert host.status()["execution_enabled"] is False
        with pytest.raises(PluginContractError, match="latched"):
            host.execute("test.echo", "test.echo", {})
    finally:
        host.cancel()
        worker.join(3)


def test_authenticated_binding_revoke_cancels_only_its_plugin_execution(tmp_path, monkeypatch):
    from core.capability_ports.plugin_v1 import PluginCapabilityPortV1
    from core.governance_nucleus_v1 import GovernanceIdentityV1, GovernanceNucleusV1
    from core.governed_capability_host_v1 import GovernedCapabilityHostV1

    class Vault:
        value = None
        def get_bytes(self):
            return self.value
        def set_bytes(self, value):
            self.value = bytes(value)
        def delete(self):
            self.value = None
            return True

    monkeypatch.setattr(permission_broker, "_audit_healthy", True)
    nucleus = GovernanceNucleusV1(
        path=tmp_path / "authority.sqlite3",
        identity=GovernanceIdentityV1("owner", "workspace", "account", "profile"),
        key_vault=Vault(), head_vault=Vault(), pending_vault=Vault(),
    )
    plugin = PluginHostV1(tmp_path / "registry.json", workspace_id="workspace")
    port = PluginCapabilityPortV1(plugin)
    governed = GovernedCapabilityHostV1(nucleus=nucleus, registry={"plugin": (port, frozenset({"execute.test.echo"}))})
    session = nucleus.begin_session()
    entered = [threading.Event(), threading.Event()]
    release = threading.Event()
    signals, receipts = {}, {}
    def execute(_plugin, _operation, payload, *, cancellation):
        signals[payload] = cancellation
        entered[payload].set()
        assert release.wait(3)
        if cancellation.is_set():
            raise PluginContractError("plugin_cancelled", "cancelled")
        return {"ok": True}
    monkeypatch.setattr(plugin, "execute", execute)
    arguments = [{"plugin_id": "test.echo", "payload": i} for i in (0, 1)]
    bindings = [governed.bind(session, "plugin", "execute.test.echo", args) for args in arguments]
    def dispatch(index):
        receipts[index] = governed.dispatch(bindings[index], arguments[index])
    workers = [threading.Thread(target=dispatch, args=(i,)) for i in (0, 1)]
    try:
        for worker in workers:
            worker.start()
        assert all(event.wait(2) for event in entered)
        governed.revoke(bindings[0].binding_id)
        assert signals[0].is_set()
        assert not signals[1].is_set()
        assert not plugin._cancelled.is_set()
        release.set()
        for worker in workers:
            worker.join(2)
            assert not worker.is_alive()
        assert receipts[0].uncertainty is True
        assert receipts[1].outcome == "completed"
        assert port._active == {}
    finally:
        release.set()
        for worker in workers:
            worker.join(3)
        nucleus.close()


@pytest.mark.parametrize("operation", ["execute.test.echo", "lifecycle.list", "local_catalog_read", "read"])
def test_registered_namespace_operation_syntax(operation):
    from core.governance_nucleus_v1 import _capability_operation
    assert _capability_operation(operation) == operation


@pytest.mark.parametrize("operation", ["execute..echo", ".execute", "execute.", "execute/echo", "execute:echo", "Execute.echo", "execute echo", "a" * 129, True, None])
def test_malformed_operation_syntax_still_fails_closed(operation):
    from core.governance_nucleus_v1 import _capability_operation, GovernanceV1ContractError
    with pytest.raises(GovernanceV1ContractError):
        _capability_operation(operation)
