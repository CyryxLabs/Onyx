from __future__ import annotations

import os
import runpy
import socket
import subprocess
import threading
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

import pytest

from core import onyx_live_activation_v14 as v14
from core import onyx_live_activation_v15 as v15
from core.phase11_governed_away_v1 import GovernedAwayUnavailable
from core.phase11_live_mission_v1 import FEATURE_FLAG, Phase11LiveMissionV1


ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "v15@invalid.local")
    _git(root, "config", "user.name", "V15 Tests")
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-qm", "initial")
    return root.resolve()


class FakeUI:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.muted = True
        self.current_file = None

    def write_log(self, value: str) -> None:
        self.logs.append(value)

    def set_state(self, _value: str) -> None:
        pass


class MemoryVault:
    def __init__(self) -> None:
        self.value = None

    def get_bytes(self):
        return self.value

    def set_bytes(self, value):
        self.value = bytes(value)


class FailingVault:
    def get_bytes(self):
        raise RuntimeError("injected native vault failure")

    def set_bytes(self, _value):
        raise RuntimeError("injected native vault failure")


def test_v15_rollback_restores_installation_and_base_after_bridge_close_failure() -> None:
    events: list[str] = []

    class Bridge:
        def close(self, timeout: float) -> None:
            events.append(f"bridge.close:{timeout}")
            raise RuntimeError("injected bridge close failure")

    class Base:
        def rollback_all(self) -> None:
            events.append("base.rollback")

    controller = object.__new__(v15.OnyxLiveActivationV15)
    controller._live_bridges = [Bridge()]
    controller._base = Base()
    controller.rollback_installation = lambda: events.append(
        "installation.rollback"
    )

    with pytest.raises(v15.ActivationV15Error, match="full rollback"):
        controller.rollback_all()

    assert events == [
        "bridge.close:15.0",
        "installation.rollback",
        "base.rollback",
    ]
    assert controller._live_bridges == []


def active_environment(tmp_path: Path, root: Path) -> dict[str, str]:
    result = dict(os.environ)
    for name in v15.CONTROL_FLAGS:
        result.pop(name, None)
    result.update(v15.exact_activation_environment((root,)))
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def test_external_agent_factory_signature_is_rejected_at_injection() -> None:
    with pytest.raises(v15.ActivationV15Error, match="must accept"):
        v15._validate_external_agent_factory_v1(lambda: object())

    v15._validate_external_agent_factory_v1(
        lambda **_binding: object()
    )


def test_v15_exact_environment_and_default_windows_bootstrap(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    environment = v15.exact_activation_environment((root,))
    flags = v15.ActivationFlagsV15.from_canonical_environ(environment)
    assert flags.master and flags.phase11
    assert flags.workspace_roots == (str(root),)
    assert environment[FEATURE_FLAG] == "true"

    bootstrap = runpy.run_path(
        str(ROOT / "scripts/bootstrap_onyx_live_v15.pyw"),
        run_name="_test_bootstrap_v15",
    )
    default_root = (tmp_path / "default-workspace").resolve()
    default_root.mkdir()
    with (
        patch("platform.system", return_value="Windows"),
        patch.dict(
            bootstrap["_bootstrap_environment"].__globals__,
            {"_default_workspace_root": lambda: default_root},
        ),
    ):
        default = bootstrap["_bootstrap_environment"]({"PATH": "preserved"})
    assert default["PATH"] == "preserved"
    assert default[FEATURE_FLAG] == "true"
    assert default["ONYX_WORKSPACE_ROOTS"] == str(default_root)
    v15.ActivationFlagsV15.from_canonical_environ(default)
    with (
        patch("platform.system", return_value="Windows"),
        patch.object(Path, "is_file", return_value=False),
        patch.dict(
            bootstrap["_bootstrap_environment"].__globals__,
            {"_default_workspace_root": lambda: default_root},
        ),
    ):
        without_docker = bootstrap["_bootstrap_environment"](
            {"PATH": "preserved"}
        )
    unavailable = v15.ActivationFlagsV15.from_canonical_environ(
        without_docker
    )
    assert unavailable.executable_sandbox is False

    with patch("platform.system", return_value="Linux"):
        fallback = bootstrap["_bootstrap_environment"]({"PATH": "preserved"})
    assert fallback == {"PATH": "preserved", **v14.exact_activation_environment()}
    assert FEATURE_FLAG not in fallback

    rollback = bootstrap["_bootstrap_environment"](
        {"PATH": "preserved", v15.LIVE_ROLLBACK_FLAG: "1"}
    )
    assert rollback == {
        "PATH": "preserved",
        v15.LIVE_ROLLBACK_FLAG: "1",
    }
    explicit_v14 = bootstrap["_bootstrap_environment"](
        {"PATH": "preserved", **v14.exact_activation_environment()}
    )
    assert explicit_v14 == {
        "PATH": "preserved",
        **v14.exact_activation_environment(),
    }
    with pytest.raises(RuntimeError, match="PARTIAL_CONFIGURATION"):
        bootstrap["_bootstrap_environment"](
            {"PATH": "preserved", v15.LIVE_MASTER_FLAG: "1"}
        )
    with pytest.raises(RuntimeError, match="PARTIAL_CONFIGURATION"):
        bootstrap["_bootstrap_environment"](
            {"ONYX_LIVE_ACTIVATION_V1": "1"}
        )
    with pytest.raises(RuntimeError, match="PARTIAL_CONFIGURATION"):
        bootstrap["_bootstrap_environment"](
            {
                v15.LIVE_ROLLBACK_FLAG: "1",
                FEATURE_FLAG: "true",
            }
        )

    prepared = bootstrap["_bootstrap_environment"](
        {"PATH": "preserved", **environment}
    )
    assert prepared["PATH"] == "preserved"
    assert {name: prepared[name] for name in environment} == environment
    with pytest.raises(RuntimeError, match="PARTIAL_CONFIGURATION"):
        bootstrap["_bootstrap_environment"]({FEATURE_FLAG: "true"})


def test_v15_direct_flags_and_controller_revalidate_executable_boundary(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    docker = (tmp_path / "docker.exe").resolve()
    docker.write_bytes(b"MZ")
    environment = dict(os.environ)
    for name in v15.CONTROL_FLAGS:
        environment.pop(name, None)
    environment.update(
        v15.exact_activation_environment(
            (root,), executable_docker_cli=str(docker)
        )
    )
    flags = v15.ActivationFlagsV15.from_canonical_environ(environment)

    def direct(**changes: object) -> v15.ActivationFlagsV15:
        values = {
            field.name: getattr(flags, field.name)
            for field in fields(flags)
        }
        values.update(changes)
        return v15.ActivationFlagsV15(**values)

    with pytest.raises(v15.ActivationV15Error, match="unavailable"):
        direct(executable_docker_cli=str(tmp_path / "missing.exe"))
    with pytest.raises(v15.ActivationV15Error, match="absolute"):
        direct(executable_docker_cli="docker.exe")
    with pytest.raises(v15.ActivationV15Error, match="npipe"):
        direct(executable_docker_host="tcp://127.0.0.1:2375")
    with pytest.raises(v15.ActivationV15Error, match="allowlist"):
        direct(executable_image_ids=("sha256:" + "A" * 64,))
    unavailable = direct(
        executable_sandbox=False,
        executable_docker_cli=str(tmp_path / "missing.exe"),
    )
    assert unavailable.executable_sandbox is False
    with pytest.raises(v15.ActivationV15Error, match="complete"):
        direct(project_autopilot=1)

    with patch.dict(os.environ, environment, clear=True):
        import main

        forged = object.__new__(v15.ActivationFlagsV15)
        for field in fields(flags):
            object.__setattr__(
                forged, field.name, getattr(flags, field.name)
            )
        object.__setattr__(
            forged, "executable_docker_host", "ssh://remote"
        )
        with pytest.raises(v15.ActivationV15Error, match="npipe"):
            v15.OnyxLiveActivationV15(
                forged,
                v15.preflight_host(main, environment),
            )

    stable = (ROOT / "scripts/bootstrap_onyx.pyw").read_text(encoding="utf-8")
    assert 'bootstrap_onyx_live_v19.pyw"' in stable
    assert 'bootstrap_onyx_live_v15.pyw"' not in stable
    launcher = (ROOT / "scripts/launch_onyx_live_v15.pyw").read_text(
        encoding="utf-8"
    )
    assert (
        'if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):'
        in launcher
    )
    assert "os._exit(0)" in launcher
    assert 'runtime_dir() / "phase11-authority-v1"' in launcher
    assert "onyx_main.runtime_dir = lambda: phase11_runtime" in launcher


def test_v15_invalid_or_relative_roots_fail_before_host_import(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    environment = v15.exact_activation_environment((root,))
    environment["ONYX_WORKSPACE_ROOTS"] = "relative"
    with pytest.raises(v15.ActivationV15Error, match="root"):
        v15.ActivationFlagsV15.from_canonical_environ(environment)
    environment = v15.exact_activation_environment((root,))
    environment[FEATURE_FLAG] = "TRUE"
    with pytest.raises(v15.ActivationV15Error, match="canonical"):
        v15.ActivationFlagsV15.from_canonical_environ(environment)


def test_v15_linked_root_is_rejected_before_resolution(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    linked = tmp_path / "linked-root"
    try:
        linked.symlink_to(root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory links unavailable: {exc}")
    with pytest.raises(v15.ActivationV15Error, match="linked|reparse"):
        v15.exact_activation_environment((linked,))


def test_v15_real_onyxlive_reaches_mission_worker_without_network(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    environment = active_environment(tmp_path, root)
    vault = MemoryVault()
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = v15.OnyxLiveActivationV15(
            v15.ActivationFlagsV15.from_canonical_environ(environment),
            v15.preflight_host(main, environment),
        )
        try:
            controller.install()
            with (
                    patch.object(
                        main, "memory_dir", return_value=tmp_path / "data" / "memory"
                    ),
                    patch.object(
                        main, "runtime_dir", return_value=tmp_path / "data" / "runtime"
                    ),
                patch(
                    "core.phase11_live_mission_v1.native_vault.NativeSecretVault",
                    return_value=vault,
                ),
                patch.object(
                    socket, "socket", side_effect=AssertionError("network used")
                ),
                patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network used"),
                ),
            ):
                instance = controller.instantiate_live(FakeUI())
            assert type(instance._phase11_missions) is Phase11LiveMissionV1
            assert instance._mission_worker.runner.__self__ is instance._phase11_missions
            assert not instance._mission_worker.running
            assert vault.value is not None
        finally:
            controller.rollback_all()
        assert not hasattr(main.OnyxLive, "_phase11_activation_v15")


def test_v15_missing_docker_degrades_executable_capability_without_host_fallback(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    missing_docker = (tmp_path / "missing-docker.exe").resolve()
    environment = dict(os.environ)
    for name in v15.CONTROL_FLAGS:
        environment.pop(name, None)
    environment.update(
        v15.exact_activation_environment(
            (root,),
            executable_docker_cli=str(missing_docker),
            executable_sandbox=False,
        )
    )
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["QSG_RHI_BACKEND"] = "software"
    vault = MemoryVault()
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = v15.OnyxLiveActivationV15(
            v15.ActivationFlagsV15.from_canonical_environ(environment),
            v15.preflight_host(main, environment),
        )
        try:
            controller.install()
            with (
                patch.object(
                    main, "memory_dir", return_value=tmp_path / "data" / "memory"
                ),
                patch.object(
                    main, "runtime_dir", return_value=tmp_path / "data" / "runtime"
                ),
                patch(
                    "core.phase11_live_mission_v1.native_vault.NativeSecretVault",
                    return_value=vault,
                ),
                patch.object(
                    socket, "socket", side_effect=AssertionError("network used")
                ),
                patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network used"),
                ),
            ):
                instance = controller.instantiate_live(FakeUI())
            assert controller.executable_capability == (
                "unavailable:docker_cli_missing"
            )
            assert type(instance._phase11_missions) is Phase11LiveMissionV1
            assert (
                instance._phase11_missions.autopilot._executable_sandbox_enabled
                is False
            )
            assert (
                instance._phase11_missions.autopilot._executable_sandbox_host
                is None
            )
            assert instance._mission_worker.runner.__self__ is (
                instance._phase11_missions
            )
        finally:
            controller.rollback_all()
        assert not hasattr(main.OnyxLive, "_phase11_activation_v15")


def test_v15_busy_away_root_degrades_only_away_and_rolls_back(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    environment = active_environment(tmp_path, root)
    vault = MemoryVault()
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = v15.OnyxLiveActivationV15(
            v15.ActivationFlagsV15.from_canonical_environ(environment),
            v15.preflight_host(main, environment),
        )
        try:
            controller.install()
            with (
                patch.object(
                    main, "memory_dir", return_value=tmp_path / "data" / "memory"
                ),
                patch.object(
                    main, "runtime_dir", return_value=tmp_path / "data" / "runtime"
                ),
                patch(
                    "core.phase11_live_mission_v1.native_vault.NativeSecretVault",
                    return_value=vault,
                ),
                patch(
                    "core.phase11_governed_away_v1._SecureAwayStoreV1",
                    side_effect=GovernedAwayUnavailable(
                        "away_storage_transient_busy"
                    ),
                ),
                patch.object(
                    socket, "socket", side_effect=AssertionError("network used")
                ),
                patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network used"),
                ),
            ):
                instance = controller.instantiate_live(FakeUI())
            bridge = instance._phase11_missions
            assert bridge.enabled is True
            assert bridge.audit is not None
            assert bridge.autopilot is not None
            assert bridge.away_mode is None
            assert (
                bridge.away_unavailable_reason
                == "away_storage_transient_busy"
            )
            assert controller.executable_capability == "available"
            assert (
                controller.away_capability
                == "unavailable:away_storage_transient_busy"
            )
            assert instance._mission_worker.runner.__self__ is bridge
        finally:
            controller.rollback_all()
        assert not hasattr(main.OnyxLive, "_phase11_activation_v15")


@pytest.mark.parametrize(
    "reason",
    [None, "", "away_storage_unknown", 1],
)
def test_v15_rejects_missing_or_invalid_away_degradation_reason(
    reason: object,
) -> None:
    bridge = type(
        "InvalidAwayBridge",
        (),
        {
            "away_mode": None,
            "away_unavailable_reason": reason,
        },
    )()
    with pytest.raises(
        v15.ActivationV15Error,
        match="missing or invalid",
    ):
        v15._validated_away_degradation_reason(
            bridge,
            phase11_enabled=True,
        )


@pytest.mark.parametrize("failure", ["root", "vault"])
def test_exact_phase11_startup_failure_refuses_runtime(
    tmp_path: Path, failure: str
) -> None:
    root = _workspace(tmp_path)
    environment = active_environment(tmp_path, root)
    if failure == "root":
        environment["ONYX_WORKSPACE_ROOTS"] = str(tmp_path / "missing")
    with patch.dict(os.environ, environment, clear=True):
        import main

        vault = FailingVault() if failure == "vault" else MemoryVault()
        with (
            patch.object(
                main, "memory_dir", return_value=tmp_path / "startup" / "memory"
            ),
            patch.object(
                main, "runtime_dir", return_value=tmp_path / "startup" / "runtime"
            ),
            patch(
                "core.phase11_live_mission_v1.native_vault.NativeSecretVault",
                return_value=vault,
            ),
            pytest.raises(Exception, match="root|directory|vault"),
        ):
            main.OnyxLive(FakeUI())


def test_v15_failpoint_rolls_back_exact_v14(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    environment = active_environment(tmp_path, root)
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = v15.OnyxLiveActivationV15(
            v15.ActivationFlagsV15.from_canonical_environ(environment),
            v15.preflight_host(main, environment),
        )
        with pytest.raises(v15.ActivationV15Error, match="injected V15"):
            controller.install(fail_after=controller.TOTAL_SEAM_COUNT)
        assert not hasattr(main.OnyxLive, "_phase11_activation_v15")
        assert v15.LIVE_MASTER_FLAG not in os.environ


def test_v15_launcher_modes_require_exact_roots(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    launcher = runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v15.pyw"),
        run_name="_test_launcher_v15",
    )
    assert launcher["_launch_mode"]({}) == "legacy"
    assert launcher["_launch_mode"](v14.exact_activation_environment()) == "v14"
    assert (
        launcher["_launch_mode"](v15.exact_activation_environment((root,)))
        == "active"
    )
    assert launcher["_launch_mode"]({v15.LIVE_ROLLBACK_FLAG: "1"}) == "rollback"
    assert launcher["_launch_mode"]({v15.LIVE_MASTER_FLAG: "1"}) == "refuse"


@pytest.mark.skipif(os.name != "nt", reason="Windows single-instance contract")
def test_v15_normal_gui_launcher_is_single_instance_and_releases(
    tmp_path: Path,
) -> None:
    launcher = runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v15.pyw"),
        run_name="_test_launcher_v15_mutex",
    )
    mutex_type = launcher["_WindowsSingleInstanceV1"]
    mutex_name = (
        rf"Local\CyryxLabs.Onyx.Test.{os.getpid()}."
        f"{abs(hash(str(tmp_path.resolve())))}"
    )
    first = mutex_type(name=mutex_name, wait_milliseconds=0)
    second = mutex_type(name=mutex_name, wait_milliseconds=25)
    second_result: list[bool] = []
    try:
        assert first.acquire() is True
        contender = threading.Thread(
            target=lambda: second_result.append(second.acquire())
        )
        contender.start()
        contender.join(timeout=2)
        assert contender.is_alive() is False
        assert second_result == [False]
    finally:
        second.close()
        first.close()

    released = mutex_type(name=mutex_name, wait_milliseconds=0)
    try:
        assert released.acquire() is True
    finally:
        released.close()


def test_v15_active_launcher_refuses_non_windows_platform(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    environment = active_environment(tmp_path, root)
    launcher = runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v15.pyw"),
        run_name="_test_launcher_v15_non_windows",
    )
    with (
        patch.dict(os.environ, environment, clear=True),
        patch.object(launcher["platform"], "system", return_value="Darwin"),
        pytest.raises(RuntimeError, match="PLATFORM_UNAVAILABLE_WINDOWS_REQUIRED"),
    ):
        launcher["run"]()
