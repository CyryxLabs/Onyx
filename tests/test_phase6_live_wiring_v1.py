from __future__ import annotations

import hashlib
import inspect
import json
import multiprocessing
from pathlib import Path
import socket
import threading
import types
from unittest.mock import patch

import pytest

import main
from core import onyx_live_activation_v7 as activation_v7
from core import phase6_agentic_core_v6 as agentic_v6
from core import phase6_live_integration_v2 as integration_v2
from core import phase6_live_wiring_v1 as wiring
from core.missions import MissionStore


ROOT = Path(__file__).resolve().parents[1]


class Snapshot:
    display_name = None
    reconciled = True
    state = types.SimpleNamespace(value="unknown")
    name_known = False


class Authority:
    def __init__(self) -> None:
        self.snapshot = Snapshot()

    def reconcile(self):
        return self.snapshot

    def begin_contact(self):
        return "Before we continue, what name should I use for you?"

    def prompt_directive(self):
        return "owner-directive"


class FakeUI:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.states: list[str] = []
        self.prompt_count = 0
        self.muted = False
        self._win = types.SimpleNamespace(_hud_v5_live=True)

    def write_log(self, value: str) -> None:
        self.logs.append(value)

    def set_state(self, value: str) -> None:
        self.states.append(value)

    def prompt_reconfig(self) -> None:
        self.prompt_count += 1


@pytest.fixture
def ready_v7(monkeypatch: pytest.MonkeyPatch):
    for name in activation_v7.CONTROL_FLAGS:
        monkeypatch.delenv(name, raising=False)
    environment = activation_v7.exact_activation_environment()
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    contract = activation_v7.preflight_host(main, environment)
    activation = activation_v7.OnyxLiveActivationV7(
        activation_v7.ActivationFlagsV7.from_canonical_environ(environment),
        contract,
        authority_factory=Authority,
    )
    activation.install()
    assert activation.start() is activation_v7.v6.ActivationV6State.READY
    host_type = contract.base.onyx_live
    lifecycle = {
        name: getattr(host_type, name)
        for name in wiring.Phase6LiveWiringV1.PATCHED_SEAMS
    }
    protected = {
        name: getattr(host_type, name)
        for name in wiring.Phase6LiveWiringV1.PROTECTED_SEAMS
    }
    controllers: list[wiring.Phase6LiveWiringV1] = []

    def create(state_root: Path) -> wiring.Phase6LiveWiringV1:
        controller = wiring.create_phase6_live_wiring_v1(
            gate=wiring.LiveWiringFeatureGateV1(True),
            activation=activation,
            state_root=state_root,
        )
        assert type(controller) is wiring.Phase6LiveWiringV1
        controllers.append(controller)
        return controller

    yield types.SimpleNamespace(
        activation=activation,
        environment=environment,
        host_type=host_type,
        lifecycle=lifecycle,
        protected=protected,
        create=create,
    )

    for controller in reversed(controllers):
        if controller.installed:
            controller.rollback_installation()
    assert all(
        getattr(host_type, name) is expected for name, expected in lifecycle.items()
    )
    assert all(
        getattr(host_type, name) is expected for name, expected in protected.items()
    )
    activation.rollback_installation()


def test_gate_is_exact_strict_default_off_and_has_zero_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "must-not-exist"
    threads = tuple(threading.enumerate())
    children = tuple(multiprocessing.active_children())
    monkeypatch.setattr(
        wiring,
        "_CORE_FACTORY",
        lambda **_kwargs: pytest.fail("disabled wiring constructed Agentic Core"),
    )
    monkeypatch.setattr(
        wiring,
        "_INTEGRATION_FACTORY",
        lambda **_kwargs: pytest.fail("disabled wiring constructed Live Integration"),
    )
    assert (
        wiring.create_phase6_live_wiring_v1(
            gate=wiring.LiveWiringFeatureGateV1(False),
            activation=None,
            state_root=root,
        )
        is None
    )
    assert root.exists() is False
    assert tuple(threading.enumerate()) == threads
    assert tuple(multiprocessing.active_children()) == children
    for value in ("", "1", "TRUE", "True", "yes", " true "):
        assert (
            wiring.LiveWiringFeatureGateV1.from_environ(
                {wiring.FEATURE_FLAG: value}
            ).enabled
            is False
        )
    assert (
        wiring.LiveWiringFeatureGateV1.from_environ(
            {wiring.FEATURE_FLAG: "true"}
        ).enabled
        is True
    )


def test_factory_is_sealed_and_identity_cannot_be_supplied_by_caller() -> None:
    assert tuple(inspect.signature(wiring.create_phase6_live_wiring_v1).parameters) == (
        "gate",
        "activation",
        "state_root",
    )
    assert tuple(inspect.signature(wiring.Phase6LiveWiringV1).parameters) == (
        "_key",
        "activation",
        "identity",
        "state_root",
    )
    source = inspect.getsource(wiring.create_phase6_live_wiring_v1)
    assert "identity = LiveWiringIdentityV1.from_activation(activation)" in source
    assert all(
        name not in inspect.signature(wiring.create_phase6_live_wiring_v1).parameters
        for name in (
            "identity",
            "invoker",
            "executor",
            "adapter",
            "core",
            "phase5",
            "mission_store",
            "workspace_scope",
        )
    )


def test_enabled_factory_requires_exact_ready_installed_v7_before_writes(
    tmp_path: Path,
) -> None:
    environment = activation_v7.exact_activation_environment()
    contract = activation_v7.preflight_host(main, environment)
    activation = activation_v7.OnyxLiveActivationV7(
        activation_v7.ActivationFlagsV7.from_canonical_environ(environment),
        contract,
        authority_factory=Authority,
    )
    root = tmp_path / "not-created"
    with pytest.raises(wiring.Phase6LiveWiringV1Denied):
        wiring.create_phase6_live_wiring_v1(
            gate=wiring.LiveWiringFeatureGateV1(True),
            activation=activation,
            state_root=root,
        )
    assert root.exists() is False


def test_identity_is_complete_immutable_and_derived_from_v7_only(
    tmp_path: Path, ready_v7
) -> None:
    root = tmp_path / "wiring"
    controller = ready_v7.create(root)
    assert controller.identity.payload() == {
        "workspace_id": "onyx-local-workspace",
        "account_id": "cyryx-local-account",
        "profile_id": "onyx-owner-profile",
        "principal_id": "onyx-owner",
    }
    assert len(controller.identity.digest) == 64
    with pytest.raises((AttributeError, TypeError)):
        controller.identity.workspace_id = "other"  # type: ignore[misc]
    assert root.exists() is False


@pytest.mark.parametrize("fail_after", (0, 1, 2, 3))
def test_partial_failure_before_or_after_each_patch_restores_exact_post_v7_seams(
    tmp_path: Path, ready_v7, fail_after: int
) -> None:
    controller = ready_v7.create(tmp_path / f"fail-{fail_after}")
    with pytest.raises(wiring.Phase6LiveWiringV1Error):
        controller.install(fail_after=fail_after)
    assert controller.installed is False
    assert all(
        getattr(ready_v7.host_type, name) is expected
        for name, expected in ready_v7.lifecycle.items()
    )
    assert all(
        getattr(ready_v7.host_type, name) is expected
        for name, expected in ready_v7.protected.items()
    )


def test_install_changes_only_three_lifecycle_seams_and_rollback_is_exact(
    tmp_path: Path, ready_v7
) -> None:
    controller = ready_v7.create(tmp_path / "rollback")
    controller.install()
    assert controller.installed is True
    assert all(
        getattr(ready_v7.host_type, name) is not expected
        for name, expected in ready_v7.lifecycle.items()
    )
    assert all(
        getattr(ready_v7.host_type, name) is expected
        for name, expected in ready_v7.protected.items()
    )
    instance = ready_v7.host_type(FakeUI())
    assert getattr(instance, wiring.SESSION_ATTRIBUTE) is None
    controller.rollback_installation()
    assert controller.installed is False
    assert hasattr(instance, wiring.SESSION_ATTRIBUTE) is False
    assert all(
        getattr(ready_v7.host_type, name) is expected
        for name, expected in ready_v7.lifecycle.items()
    )
    assert all(
        getattr(ready_v7.host_type, name) is expected
        for name, expected in ready_v7.protected.items()
    )


def test_real_host_session_constructs_exact_v2_without_network_and_tears_down(
    tmp_path: Path, ready_v7
) -> None:
    controller = ready_v7.create(tmp_path / "session")
    controller.install()
    instance = ready_v7.host_type(FakeUI())
    network_calls = 0

    def refuse_network(*_args: object, **_kwargs: object) -> None:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("wiring attempted network")

    with patch.object(socket.socket, "connect", refuse_network):
        instance._start_phase5_session()
    session = getattr(instance, wiring.SESSION_ATTRIBUTE)
    assert type(session) is wiring.LiveWiringSessionV1
    assert type(session.facade) is integration_v2.Phase6LiveIntegrationV2
    assert type(instance._missions) is MissionStore
    assert session.facade.identity == controller.identity.as_v2()
    assert session.state_path.is_file()
    assert session.receipt_path.is_file()
    assert session.receipt_path.parent == session.state_path.parent
    assert session.facade._core._missions is instance._missions
    assert type(session.facade._text._delegate._executor) is (
        agentic_v6.TerminableProcessExecutorV4
    )
    assert network_calls == 0
    assert controller.active_sessions == 1
    instance._stop_phase5_session("test")
    assert session.closed is True
    assert session.facade.closed is True
    assert getattr(instance, wiring.SESSION_ATTRIBUTE) is None
    assert instance._phase5 is None
    assert controller.active_sessions == 0


def test_double_reconnect_uses_collision_safe_session_paths_and_closes_each(
    tmp_path: Path, ready_v7
) -> None:
    controller = ready_v7.create(tmp_path / "reconnect")
    controller.install()
    instance = ready_v7.host_type(FakeUI())
    instance._start_phase5_session()
    first = getattr(instance, wiring.SESSION_ATTRIBUTE)
    first_bridge = instance._phase5
    instance._stop_phase5_session("reconnect")
    assert first.closed is True
    assert first_bridge.status_payload()["data"]["state"] == "TERMINATED"

    instance._start_phase5_session()
    second = getattr(instance, wiring.SESSION_ATTRIBUTE)
    second_bridge = instance._phase5
    assert second.session_key != first.session_key
    assert second.state_path != first.state_path
    assert second.receipt_path != first.receipt_path
    assert first.receipt_path.is_file()
    instance._stop_phase5_session("shutdown")
    assert second.closed is True
    assert second_bridge.status_payload()["data"]["state"] == "TERMINATED"
    assert controller.active_sessions == 0


def test_teardown_closes_v2_before_phase5_termination(
    tmp_path: Path, ready_v7, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = ready_v7.create(tmp_path / "ordering")
    controller.install()
    instance = ready_v7.host_type(FakeUI())
    instance._start_phase5_session()
    session = getattr(instance, wiring.SESSION_ATTRIBUTE)
    events: list[str] = []
    original_close = wiring.LiveWiringSessionV1.close
    original_stop = controller._originals["_stop_phase5_session"]

    def close_spy(value: wiring.LiveWiringSessionV1) -> None:
        events.append("v2-close")
        original_close(value)

    def stop_spy(value: object, reason: str) -> None:
        events.append("phase5-stop")
        original_stop(value, reason)

    monkeypatch.setattr(wiring.LiveWiringSessionV1, "close", close_spy)
    controller._originals["_stop_phase5_session"] = stop_spy
    try:
        instance._stop_phase5_session("ordered")
    finally:
        controller._originals["_stop_phase5_session"] = original_stop
    assert events == ["v2-close", "phase5-stop"]
    assert session.closed is True


def test_session_creation_failure_revokes_phase5_and_leaves_no_session_or_files(
    tmp_path: Path, ready_v7, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "session-failure"
    controller = ready_v7.create(root)
    controller.install()
    instance = ready_v7.host_type(FakeUI())

    def fail_paths(
        _bridge: object,
    ) -> tuple[str, Path, Path]:
        raise wiring.Phase6LiveWiringV1Denied("injected path failure")

    monkeypatch.setattr(controller, "_session_paths", fail_paths)
    with pytest.raises(wiring.Phase6LiveWiringV1Denied):
        instance._start_phase5_session()
    assert instance._phase5 is None
    assert getattr(instance, wiring.SESSION_ATTRIBUTE) is None
    assert root.exists() is False
    assert controller.active_sessions == 0


def test_post_construction_identity_or_factory_drift_fails_before_phase5_start(
    tmp_path: Path, ready_v7, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = ready_v7.create(tmp_path / "drift")
    controller.install()
    instance = ready_v7.host_type(FakeUI())
    original = ready_v7.activation.flags.account_id
    object.__setattr__(ready_v7.activation.flags, "account_id", "other-account")
    try:
        with pytest.raises(wiring.Phase6LiveWiringV1Denied):
            instance._start_phase5_session()
    finally:
        object.__setattr__(ready_v7.activation.flags, "account_id", original)
    assert instance._phase5 is None
    assert getattr(instance, wiring.SESSION_ATTRIBUTE) is None

    monkeypatch.setattr(
        integration_v2,
        "create_phase6_live_integration_v2",
        lambda **_kwargs: None,
    )
    with pytest.raises(wiring.Phase6LiveWiringV1Denied):
        instance._start_phase5_session()
    assert instance._phase5 is None


def test_symlink_or_reparse_state_root_is_rejected_when_supported(
    tmp_path: Path, ready_v7
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked-root"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable on this host")
    with pytest.raises(wiring.Phase6LiveWiringV1ContractError):
        ready_v7.create(link)


def test_frozen_v7_v2_core_and_live_host_anchors_remain_exact() -> None:
    expected = {
        "core/phase6_live_integration_v2.py": (
            "e3194a0d8e206d33218bc8291cbd518788e8dfb3931adfd2f067908655d409b5"
        ),
        "docs/onyx/checkpoints/phase6-live-integration-v2/manifest.json": (
            "d02b265e5d67c98fb9dd2e868440ead39360187bdd95592fcf89a44f4448833a"
        ),
        "core/phase6_agentic_core_v6.py": (
            "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a"
        ),
        "core/onyx_live_activation_v7.py": (
            "906c7c0e31cb5efc28e5357bb158545e903d65ff1f160b3899bc3e2fb3c1dc77"
        ),
        "docs/onyx/checkpoints/onyx-live-activation-v7/manifest.json": (
            "312d6654f3423f16f4b36f435638920836994bd56c3e9a8766a086e2c6d647da"
        ),
        "main.py": ("6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712"),
        "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
        "dashboard/server.py": (
            "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1"
        ),
        "scripts/launch_onyx_live_v7.pyw": (
            "a5dae76af4b09af90aa89b3638e2329fbed8c79a50fbcafa0a6179f38d82c531"
        ),
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "phase6_live_wiring_v1" not in source
        assert wiring.FEATURE_FLAG not in source


def test_manifest_recomputes_artifact_root() -> None:
    manifest_path = ROOT / "docs/onyx/checkpoints/phase6-live-wiring-v1/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = {item["path"]: item["sha256"] for item in manifest["artifacts"]}
    records = [f"{path}\0{digest}" for path, digest in artifacts.items()]
    root = hashlib.sha256("\n".join(sorted(records)).encode("utf-8")).hexdigest()
    assert len(artifacts) == len(manifest["artifacts"])
    assert all(
        hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
        for path, digest in artifacts.items()
    )
    assert root == manifest["artifact_root_sha256"]
