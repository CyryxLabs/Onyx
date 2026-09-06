from __future__ import annotations

import importlib
import ctypes.util
import json
import os
import platform
import runpy
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from core import native_startup_smoke_v1 as native
from core.native_activation_contract_v1 import activation_contract_for_system_v1


@pytest.mark.parametrize(
    ("system", "activation"),
    (
        ("Windows", "v24"),
        ("Darwin", "v8"),
        ("Linux", "v8"),
    ),
)
def test_platform_selection_is_explicit(system: str, activation: str) -> None:
    assert native._activation_for_system(system) == activation


def test_platform_selection_rejects_unknown_host() -> None:
    with pytest.raises(native.NativeStartupSmokeError, match="unsupported"):
        native._activation_for_system("Plan9")


def test_windows_v24_preparation_uses_exact_authority_without_v23_option_injection(
    tmp_path: Path,
) -> None:
    from core.onyx_live_activation_v24 import ActivationFlagsV24

    prepared = native._prepare_windows_v24(tmp_path)
    flags = ActivationFlagsV24.from_canonical_environ(prepared)
    v15 = flags.base.base.base.base.base.base.base.base.base

    assert v15.workspace_roots == (str(tmp_path.resolve()),)
    assert v15.executable_sandbox is True


def _bound_v24_host_fixture() -> tuple[object, object, ModuleType, object]:
    from core import onyx_live_activation_v24 as v24

    class OnyxLive:
        async def _execute_tool(self, _call: object) -> None:
            return None

    host_module = ModuleType("authenticated_v24_test_host")
    host_module.OnyxLive = OnyxLive
    instance = OnyxLive()
    owned_dispatch = v24._ProtectedDispatchV24(OnyxLive._execute_tool)

    def owned_setattr(owner: object, name: str, value: object) -> None:
        object.__setattr__(owner, name, value)

    guarded_class = type(
        f"OnyxLiveV24Guard_{id(instance):x}",
        (OnyxLive,),
        {
            "__slots__": (),
            "__module__": OnyxLive.__module__,
            "_execute_tool": owned_dispatch,
            "__setattr__": owned_setattr,
        },
    )
    instance.__class__ = guarded_class
    binding = v24._BindingV24(
        instance,
        OnyxLive,
        guarded_class,
        False,
        None,
        owned_dispatch,
        owned_setattr,
    )
    contract = object.__new__(v24.HostContractV24)
    object.__setattr__(contract, "module", host_module)
    object.__setattr__(contract, "project", Path.cwd())
    object.__setattr__(contract, "base", None)
    controller = object.__new__(v24.OnyxLiveActivationV24)
    controller.contract = contract
    controller._installed = True
    controller._rollback_pending = False
    controller._bindings = [binding]
    setattr(host_module, v24.HOST_MARKER, controller)
    return controller, instance, host_module, binding


def test_windows_v24_host_accepts_only_controller_owned_guard() -> None:
    controller, instance, host_module, _binding = _bound_v24_host_fixture()

    assert native._authenticated_windows_v24_host_v1(
        controller,
        instance,
        host_module,
    )


def test_windows_v24_host_rejects_unbound_or_drifted_guard() -> None:
    controller, instance, host_module, binding = _bound_v24_host_fixture()

    forged_type = type("ForgedV24Guard", (host_module.OnyxLive,), {})
    forged = forged_type()
    assert not native._authenticated_windows_v24_host_v1(
        controller,
        forged,
        host_module,
    )

    type(instance)._execute_tool = host_module.OnyxLive._execute_tool
    assert not native._authenticated_windows_v24_host_v1(
        controller,
        instance,
        host_module,
    )
    type(instance)._execute_tool = binding.owned_dispatch

    controller._bindings.append(binding)
    assert not native._authenticated_windows_v24_host_v1(
        controller,
        instance,
        host_module,
    )


@pytest.mark.parametrize("system", ("Darwin", "Linux"))
def test_portable_smoke_matches_normal_fallback_and_is_capability_limited(
    system: str,
) -> None:
    contract = activation_contract_for_system_v1(system)

    assert native._activation_for_system(system) == contract["normal_activation"]
    assert contract == {
        "contract": "OnyxHostActivation.v1",
        "normal_activation": "v8",
        "smoke_activation": "v8",
        "activation_profile": "portable-v8-fallback-capability-limited",
        "capability_limited": True,
        "v15_v19_parity": False,
    }


@pytest.mark.parametrize("system", ("Darwin", "Linux"))
def test_mocked_normal_no_arg_chain_and_smoke_both_terminate_at_v8(
    system: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(native.platform, "system", lambda: system)
    monkeypatch.setattr(native.sys, "argv", ["Onyx"])

    # V24 through V17 normal bootstraps explicitly descend on non-Windows.
    for version, lower in (
        (23, "v22"),
        (22, "v21"),
        (21, "v20"),
        (20, "v19"),
        (19, "v18"),
        (18, "v17"),
        (17, "v16"),
    ):
        namespace = runpy.run_path(
            str(root / "scripts" / f"bootstrap_onyx_live_v{version}.pyw"),
            run_name=f"normal_bootstrap_v{version}_{system}",
        )
        mode, _prepared = namespace["_bootstrap_environment"]({})
        assert mode == lower

    # V16 prepares the V14 envelope, then launchers V16 and V15 delegate it.
    v16_bootstrap = runpy.run_path(
        str(root / "scripts" / "bootstrap_onyx_live_v16.pyw"),
        run_name=f"normal_bootstrap_v16_{system}",
    )
    v14 = importlib.import_module("core.onyx_live_activation_v14")
    v14_environment = v14.exact_activation_environment()
    assert v16_bootstrap["_bootstrap_environment"]({}) == v14_environment

    observed: list[str] = []

    def assert_delegation(version: int, environment: dict[str, str]) -> None:
        namespace = runpy.run_path(
            str(root / "scripts" / f"launch_onyx_live_v{version}.pyw"),
            run_name=f"normal_launcher_v{version}_{system}",
        )
        lower = version - 1
        globals_ = namespace["run"].__globals__
        monkeypatch.setitem(
            globals_,
            f"_run_v{lower}",
            lambda _environment, target=lower: observed.append(f"v{target}"),
        )
        os.environ.clear()
        os.environ.update(environment)
        namespace["run"]()

    before = dict(os.environ)
    try:
        assert_delegation(16, v14_environment)
        assert_delegation(15, v14_environment)
        for version in range(14, 8, -1):
            module = importlib.import_module(f"core.onyx_live_activation_v{version}")
            assert_delegation(version, module.exact_activation_environment())
    finally:
        os.environ.clear()
        os.environ.update(before)

    assert observed == [
        "v15",
        "v14",
        "v13",
        "v12",
        "v11",
        "v10",
        "v9",
        "v8",
    ]
    contract = activation_contract_for_system_v1(system)
    assert contract["normal_activation"] == "v8"
    assert native._activation_for_system(system) == "v8"


def test_external_boundary_counts_and_restores_real_python_seams() -> None:
    original_connect = socket.create_connection
    original_run = subprocess.run

    with native.external_call_boundary_v1() as calls:
        with pytest.raises(native.NativeStartupSmokeError, match="network I/O"):
            socket.create_connection(("127.0.0.1", 9))
        with pytest.raises(native.NativeStartupSmokeError, match="child process"):
            subprocess.run(["definitely-not-started"], check=False)
        assert calls.network == 1
        assert calls.process == 1
        evidence = calls.evidence()
        assert evidence["scope"] == native.INTERCEPTION_SCOPE
        assert "network:socket.create_connection" in evidence["network_surfaces"]
        assert "process:subprocess.Popen" in evidence["process_surfaces"]

    assert socket.create_connection is original_connect
    assert subprocess.run is original_run


def _owner_probe_kwargs() -> dict[str, object]:
    return {
        "input": None,
        "text": True,
        "capture_output": True,
        "timeout": 15,
        "check": False,
        "shell": False,
    }


def _owner_lookup_argv() -> list[str]:
    return [
        "/usr/bin/secret-tool",
        "lookup",
        "service",
        "CyryxLabs.Onyx.OwnerProfileV8",
        "account",
        "journal-key-primary",
    ]


def _owner_health_argv() -> list[str]:
    return [
        "/usr/bin/secret-tool",
        "search",
        "--all",
        "service",
        "Onyx.NativeVault.HealthProbe",
        "account",
        f"probe-{os.getpid()}-{'a' * 32}",
    ]


def _owner_chain_lookup_argv() -> list[str]:
    return [
        "/bin/secret-tool",
        "lookup",
        "service",
        "Onyx.OwnerProfileChainHead.v1",
        "account",
        "owner-ebb5c3055dbe465c3cfa9457bad77797",
    ]


def test_linux_owner_probe_allowlist_uses_thread_local_run_popen_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    events: list[tuple[str, list[str]]] = []

    class FakePopen:
        def __init__(self, argv, **_kwargs):
            events.append(("popen", list(argv)))

    def fake_run(argv, **_kwargs):
        subprocess.Popen(
            argv,
            text=True,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        events.append(("run", list(argv)))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    commands = (
        _owner_lookup_argv(),
        _owner_chain_lookup_argv(),
        _owner_health_argv(),
    )

    with native.external_call_boundary_v1(
        allow_posix_owner_backend_probe=True,
    ) as calls:
        with native.posix_owner_backend_probe_capability_v1(calls):
            for argv in commands:
                result = subprocess.run(argv, **_owner_probe_kwargs())
                assert result.returncode == 1
        assert calls.process == 0
        assert calls.secure_backend_probe == 3
        assert calls.evidence()["secure_backend_probe_calls"] == 3
        assert calls.evidence()["secure_backend_probe_surfaces"] == [
            native.POSIX_OWNER_BACKEND_PROBE_SURFACE
        ]

    assert events == [
        ("popen", commands[0]),
        ("run", commands[0]),
        ("popen", commands[1]),
        ("run", commands[1]),
        ("popen", commands[2]),
        ("run", commands[2]),
    ]


def test_one_continuous_boundary_spans_subclass_import_and_runtime_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    events: list[str] = []

    class FakePopen:
        def __init__(self, _argv, **_kwargs):
            events.append("popen")

    def fake_run(argv, **_kwargs):
        subprocess.Popen(
            argv,
            text=True,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        events.append("run")
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    calls = native.ExternalCallCountersV1()

    with native.external_call_boundary_v1(
        counters=calls,
        allow_posix_owner_backend_probe=True,
    ):
        guarded_run = subprocess.run

        class ImportCompatibilityPopen(subprocess.Popen):
            pass

        assert issubclass(ImportCompatibilityPopen, FakePopen)
        with pytest.raises(native.NativeStartupSmokeError, match="child process"):
            subprocess.run(_owner_lookup_argv(), **_owner_probe_kwargs())
        with native.posix_owner_backend_probe_capability_v1(calls):
            result = subprocess.run(_owner_lookup_argv(), **_owner_probe_kwargs())
            assert result.returncode == 1
        with pytest.raises(native.NativeStartupSmokeError, match="child process"):
            guarded_run(_owner_lookup_argv(), **_owner_probe_kwargs())
        with pytest.raises(native.NativeStartupSmokeError, match="child process"):
            ImportCompatibilityPopen(_owner_lookup_argv())

    assert calls.process == 3
    assert calls.secure_backend_probe == 1
    assert events == ["popen", "run"]


def test_trace_during_capability_handoff_cannot_escape_process_or_network_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    fired = False
    denied: list[str] = []

    def tracer(frame, event, arg):
        nonlocal fired
        del arg
        if (
            not fired
            and event == "line"
            and frame.f_code
            is native.posix_owner_backend_probe_capability_v1.__wrapped__.__code__
        ):
            fired = True
            try:
                subprocess.run(["forbidden-transition-child"], check=False)
            except native.NativeStartupSmokeError:
                denied.append("process")
            try:
                socket.create_connection(("127.0.0.1", 9))
            except native.NativeStartupSmokeError:
                denied.append("network")
        return tracer

    with native.external_call_boundary_v1(
        allow_posix_owner_backend_probe=True,
    ) as calls:
        sys.settrace(tracer)
        try:
            with native.posix_owner_backend_probe_capability_v1(calls):
                assert fired
        finally:
            sys.settrace(None)

        assert denied == ["process", "network"]
        assert calls.process == 1
        assert calls.network == 1
        assert calls.secure_backend_probe == 0


def test_linux_portaudio_resolution_never_launches_ldconfig(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    authentic_calls: list[object] = []

    def fake_find_library(name):
        authentic_calls.append(name)
        return "must-not-be-used"

    monkeypatch.setattr(ctypes.util, "find_library", fake_find_library)
    with native.external_call_boundary_v1() as calls:
        assert ctypes.util.find_library("portaudio") == "libportaudio.so.2"
        with pytest.raises(native.NativeStartupSmokeError, match="child process"):
            ctypes.util.find_library("unexpected-library")

    assert authentic_calls == []
    assert calls.process == 1
    assert "process:ctypes.util.find_library" in calls.evidence()["process_surfaces"]


def test_approved_run_cannot_reenter_popen_with_different_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")

    def fake_run(_argv, **_kwargs):
        subprocess.Popen(
            ["/bin/sh", "-c", "forbidden"],
            text=True,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with native.external_call_boundary_v1(
        allow_posix_owner_backend_probe=True,
    ) as calls:
        with native.posix_owner_backend_probe_capability_v1(calls):
            with pytest.raises(native.NativeStartupSmokeError, match="child process"):
                subprocess.run(_owner_lookup_argv(), **_owner_probe_kwargs())
        assert calls.secure_backend_probe == 1
        assert calls.process == 1


@pytest.mark.parametrize(
    ("argv", "kwargs", "direct_popen"),
    (
        (
            [
                "/usr/bin/secret-tool",
                "store",
                "--label=forbidden",
                "service",
                "CyryxLabs.Onyx.OwnerProfileV8",
                "account",
                "journal-key-primary",
            ],
            {**_owner_probe_kwargs(), "input": "forbidden-secret"},
            False,
        ),
        (
            [
                "/usr/bin/secret-tool",
                "lookup",
                "service",
                "CyryxLabs.Onyx.OwnerProfileV8",
                "account",
                "wrong-account",
            ],
            _owner_probe_kwargs(),
            False,
        ),
        (
            _owner_lookup_argv(),
            {**_owner_probe_kwargs(), "env": {"FORBIDDEN": "1"}},
            False,
        ),
        (
            [*_owner_health_argv()[:-1], f"probe-{os.getpid() + 1}-{'a' * 32}"],
            _owner_probe_kwargs(),
            False,
        ),
        (_owner_lookup_argv(), {}, True),
    ),
)
def test_linux_owner_probe_allowlist_rejects_every_contract_variation(
    argv: list[str],
    kwargs: dict[str, object],
    direct_popen: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    with native.external_call_boundary_v1(
        allow_posix_owner_backend_probe=True,
    ) as calls:
        with native.posix_owner_backend_probe_capability_v1(calls):
            with pytest.raises(native.NativeStartupSmokeError, match="child process"):
                if direct_popen:
                    subprocess.Popen(argv)
                else:
                    subprocess.run(argv, **kwargs)
        assert calls.process == 1
        assert calls.secure_backend_probe == 0


def test_owner_probe_allowlist_is_disabled_by_default() -> None:
    with native.external_call_boundary_v1() as calls:
        with pytest.raises(native.NativeStartupSmokeError, match="child process"):
            subprocess.run(_owner_lookup_argv(), **_owner_probe_kwargs())
        assert calls.process == 1
        assert calls.secure_backend_probe == 0


def test_owner_probe_allowlist_is_denied_on_non_linux_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native.platform, "system", lambda: "Darwin")
    with native.external_call_boundary_v1(
        allow_posix_owner_backend_probe=True,
    ) as calls:
        with pytest.raises(native.NativeStartupSmokeError, match="child process"):
            subprocess.run(_owner_lookup_argv(), **_owner_probe_kwargs())
        assert calls.process == 1
        assert calls.secure_backend_probe == 0


def test_approved_run_ticket_allows_exactly_one_identical_popen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native.platform, "system", lambda: "Linux")
    opened = 0

    class FakePopen:
        def __init__(self, _argv, **_kwargs):
            nonlocal opened
            opened += 1

    def fake_run(argv, **_kwargs):
        popen_kwargs = {
            "text": True,
            "shell": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        subprocess.Popen(argv, **popen_kwargs)
        subprocess.Popen(argv, **popen_kwargs)

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    with native.external_call_boundary_v1(
        allow_posix_owner_backend_probe=True,
    ) as calls:
        with native.posix_owner_backend_probe_capability_v1(calls):
            with pytest.raises(native.NativeStartupSmokeError, match="child process"):
                subprocess.run(_owner_lookup_argv(), **_owner_probe_kwargs())
        assert opened == 1
        assert calls.secure_backend_probe == 1
        assert calls.process == 1


def test_external_boundary_denies_and_counts_udp_sendto() -> None:
    original_sendto = socket.socket.sendto
    datagram = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with native.external_call_boundary_v1() as calls:
            with pytest.raises(native.NativeStartupSmokeError, match="network I/O"):
                datagram.sendto(b"must-not-leave-process", ("127.0.0.1", 9))
            assert calls.network == 1
            assert (
                "network:socket.socket.sendto" in calls.evidence()["network_surfaces"]
            )
    finally:
        datagram.close()

    assert socket.socket.sendto is original_sendto


def test_provider_fence_is_host_local_and_never_mutates_sdk_global() -> None:
    from google import genai

    class HostModule:
        pass

    host = HostModule()
    host.genai = genai
    original_sdk_client = genai.Client
    original_host_genai = host.genai

    with native.external_call_boundary_v1(host_module=host) as calls:
        assert genai.Client is original_sdk_client
        assert host.genai is not genai
        with pytest.raises(
            native.NativeStartupSmokeError,
            match="provider construction",
        ):
            host.genai.Client(api_key="must-not-be-used")
        assert genai.Client is original_sdk_client
        assert calls.provider == 1
        assert calls.evidence()["provider_surfaces"] == ["provider:google.genai.Client"]

    assert genai.Client is original_sdk_client
    assert host.genai is original_host_genai


def test_provider_free_environment_avoids_native_vault_process_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import credentials

    original = {
        "GOOGLE_API_KEY": "must-not-survive",
        "ONYX_TEST_ENVIRONMENT_SENTINEL": "original",
    }
    prepared = native._provider_free_environment_v1(original)

    assert original == {
        "GOOGLE_API_KEY": "must-not-survive",
        "ONYX_TEST_ENVIRONMENT_SENTINEL": "original",
    }
    assert "GOOGLE_API_KEY" not in prepared
    assert prepared["GEMINI_API_KEY"] == (native._PROVIDER_FREE_CREDENTIAL_SENTINEL)

    monkeypatch.setattr(
        credentials,
        "_backend",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("native credential helper must remain lazy")
        ),
    )
    monkeypatch.setenv(
        "GEMINI_API_KEY",
        native._PROVIDER_FREE_CREDENTIAL_SENTINEL,
    )
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    assert credentials.status()["source"] == "environment"


def test_cleanup_continues_after_ui_and_controller_faults() -> None:
    events: list[str] = []

    class Window:
        def close(self) -> None:
            events.append("close")
            raise OSError("close failed")

    class App:
        def processEvents(self) -> None:
            events.append("events")
            raise RuntimeError("events failed")

    class UI:
        _win = Window()
        _app = App()

    class Controller:
        def rollback_all(self) -> None:
            events.append("rollback")
            raise ValueError("rollback failed")

    class Main:
        runtime_dir = "temporary"

    class Paths:
        private_control_plane_runtime_dir = "temporary-private"

    class Governance:
        native_vault = "temporary-vault"

    class ControlPlane:
        private_control_plane_runtime_dir = "temporary-control-plane"

    main = Main()
    paths = Paths()
    governance = Governance()
    control_plane = ControlPlane()
    failures = native._cleanup_host(
        ui=UI(),
        controller=Controller(),
        onyx_main=main,
        original_runtime_dir="original",
        paths_module=paths,
        original_private_control_plane_runtime_dir="original-private",
        governance_module=governance,
        original_governance_native_vault="original-vault",
        control_plane_module=control_plane,
        original_control_plane_runtime_dir="original-control-plane",
    )

    assert events == ["close", "events", "rollback"]
    assert main.runtime_dir == "original"
    assert paths.private_control_plane_runtime_dir == "original-private"
    assert governance.native_vault == "original-vault"
    assert control_plane.private_control_plane_runtime_dir == "original-control-plane"
    assert failures == (
        "ui.close:OSError",
        "ui.processEvents:RuntimeError",
        "activation.rollback_all:ValueError",
    )


def test_cleanup_closes_host_worker_and_phase11_before_activation() -> None:
    events: list[str] = []

    class Phase11:
        def begin_shutdown(self) -> None:
            events.append("phase11.begin")
            raise OSError("injected begin failure")

        def close(self, timeout: float) -> None:
            events.append(f"phase11.close:{timeout}")
            raise RuntimeError("injected close failure")

    class Worker:
        def stop(self, timeout: float) -> bool:
            events.append(f"worker.stop:{timeout}")
            return False

    class Host:
        _phase11_missions = Phase11()
        _mission_worker = Worker()

        def _stop_phase5_session(self, reason: str) -> None:
            events.append(f"phase5.stop:{reason}")
            raise ValueError("injected phase5 failure")

    class Controller:
        def rollback_all(self) -> None:
            events.append("activation.rollback")

    failures = native._cleanup_host(
        ui=None,
        controller=Controller(),
        onyx_main=None,
        original_runtime_dir=native._UNSET,
        instance=Host(),
    )

    assert events == [
        "phase5.stop:native-startup-smoke",
        "phase11.begin",
        "worker.stop:15.0",
        "phase11.close:15.0",
        "activation.rollback",
    ]
    assert failures == (
        "host.phase5.stop:ValueError",
        "host.phase11.begin_shutdown:OSError",
        "host.worker.stop:UnconfirmedStop",
        "host.phase11.close:RuntimeError",
    )


def test_success_restores_environment_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "result.json"
    monkeypatch.setenv(native.NATIVE_STARTUP_SMOKE_OUTPUT_ENV, str(output))
    monkeypatch.setenv("ONYX_TEST_ENVIRONMENT_SENTINEL", "original")
    before = dict(os.environ)

    def fake_run_host(_output: Path) -> dict[str, object]:
        os.environ.clear()
        os.environ["ONYX_TEST_ENVIRONMENT_SENTINEL"] = "mutated"
        return {"contract": native.NATIVE_STARTUP_SMOKE_CONTRACT, "status": "passed"}

    monkeypatch.setattr(native, "_run_host", fake_run_host)

    assert native.run_native_startup_smoke_v1()["status"] == "passed"
    assert dict(os.environ) == before


def test_failure_writes_honest_payload_and_restores_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "failure.json"
    monkeypatch.setenv(native.NATIVE_STARTUP_SMOKE_OUTPUT_ENV, str(output))
    monkeypatch.setenv("ONYX_TEST_ENVIRONMENT_SENTINEL", "original")
    before = dict(os.environ)

    def fake_run_host(_output: Path) -> dict[str, object]:
        os.environ.clear()
        os.environ["ONLY_IN_FAILED_SMOKE"] = "1"
        raise LookupError("expected failure")

    monkeypatch.setattr(native, "_run_host", fake_run_host)
    monkeypatch.setattr(native.platform, "system", lambda: "Windows")

    with pytest.raises(LookupError, match="expected failure"):
        native.run_native_startup_smoke_v1()

    assert dict(os.environ) == before
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "contract": native.NATIVE_STARTUP_SMOKE_CONTRACT,
        "error": "LookupError",
        "interception_scope": native.INTERCEPTION_SCOPE,
        "status": "failed",
        "system": "Windows",
        native.TERMINAL_FENCE_EVIDENCE_KEY: False,
    }


def test_terminal_smoke_api_requires_exact_frozen_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "terminal.json"
    monkeypatch.setenv(native.NATIVE_STARTUP_SMOKE_OUTPUT_ENV, str(output))
    monkeypatch.setattr(sys, "argv", ["Onyx", native.NATIVE_STARTUP_SMOKE_ARGUMENT])
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    with pytest.raises(native.NativeStartupSmokeError, match="exact frozen CLI"):
        native.run_terminal_native_startup_smoke_v1()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    observed: dict[str, object] = {}

    def fake_run_host(path: Path, *, terminal_fence: bool = False):
        observed.update(path=path, terminal_fence=terminal_fence)
        return {
            "contract": native.NATIVE_STARTUP_SMOKE_CONTRACT,
            "status": "passed",
            native.TERMINAL_FENCE_EVIDENCE_KEY: terminal_fence,
        }

    monkeypatch.setattr(native, "_run_host", fake_run_host)
    payload = native.run_terminal_native_startup_smoke_v1()
    assert observed == {"path": output.absolute(), "terminal_fence": True}
    assert payload[native.TERMINAL_FENCE_EVIDENCE_KEY] is True


def test_terminal_child_keeps_process_network_and_provider_fenced_after_context(
    tmp_path: Path,
) -> None:
    output = tmp_path / "terminal-child.json"
    script = r"""
import json
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from core.native_startup_smoke_v1 import (
    ExternalCallCountersV1,
    NativeStartupSmokeError,
    _provider_call_boundary_v1,
    _write_result,
    external_call_boundary_v1,
)

class Provider:
    def Client(self, *_args, **_kwargs):
        raise AssertionError("authentic provider was exposed")

host = SimpleNamespace(genai=Provider())
calls = ExternalCallCountersV1()
denied = []
fired = False

with external_call_boundary_v1(counters=calls, _restore_on_exit=False):
    with _provider_call_boundary_v1(host, calls, restore_on_exit=False):
        pass

def tracer(frame, event, arg):
    global fired
    del arg
    if not fired and event == "line" and frame.f_code.co_name == "handoff":
        fired = True
        for name, operation in (
            ("process", lambda: subprocess.run(["terminal-fence-escape"])),
            ("network", lambda: socket.create_connection(("127.0.0.1", 9))),
            ("provider", lambda: host.genai.Client(api_key="forbidden")),
        ):
            try:
                operation()
            except NativeStartupSmokeError:
                denied.append(name)
    return tracer

def handoff():
    marker = "launcher-epilogue"
    return marker

sys.settrace(tracer)
handoff()
sys.settrace(None)
_write_result(
    Path(sys.argv[1]),
    {
        "denied": denied,
        "fired": fired,
        "network_calls": calls.network,
        "process_calls": calls.process,
        "provider_calls": calls.provider,
    },
)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(output)],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "denied": ["process", "network", "provider"],
        "fired": True,
        "network_calls": 1,
        "process_calls": 1,
        "provider_calls": 1,
    }


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_posix_result_writer_rejects_symlink_parent(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(native.NativeStartupSmokeError, match="parent must preexist"):
        native._write_result(linked / "result.json", {"status": "passed"})
    assert not (real / "result.json").exists()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_run_smoke_keeps_lexical_output_authority_and_rejects_linked_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv(
        native.NATIVE_STARTUP_SMOKE_OUTPUT_ENV,
        str(linked / "result.json"),
    )
    monkeypatch.setattr(
        native,
        "_run_host",
        lambda _output: (_ for _ in ()).throw(LookupError("expected failure")),
    )

    with pytest.raises(
        native.NativeStartupSmokeError,
        match="parent must preexist without symlinks",
    ):
        native.run_native_startup_smoke_v1()

    assert not (target / "result.json").exists()
