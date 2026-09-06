from __future__ import annotations

import json
import hashlib
import subprocess
import threading
import time
from pathlib import Path

import pytest

from core.missions import MissionError, MissionStore, MissionWorker, worker_once
from core.permission_broker import set_permission_callback
from core.phase11_governed_away_v1 import (
    GovernedAwayUnavailable,
    PlaywrightBrowserDriverV1,
)
from core.phase11_live_mission_v1 import Phase11LiveMissionError, Phase11LiveMissionV1


KEY = b"b" * 32


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Onyx Away")
    _git(root, "config", "user.email", "away@example.invalid")
    (root / "project.txt").write_text("governed away\n", encoding="utf-8")
    _git(root, "add", "project.txt")
    _git(root, "commit", "-qm", "base")
    return root.resolve()


class _Vault:
    def __init__(self) -> None:
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)


class _Driver:
    def __init__(self, *, block: bool = False, fail: bool = False) -> None:
        self.calls = 0
        self.block = block
        self.fail = fail
        self.started = threading.Event()
        self.release = threading.Event()

    def resolve_public_host(self, host):
        return ("93.184.216.34",)

    def preflight(self, *, envelope, dns_pins):
        assert set(dns_pins) == set(envelope.allowed_domains)

    def execute(
        self,
        *,
        envelope,
        profile_dir,
        publish_artifact,
        cancel,
        control,
        runtime_deadline,
        dns_pins,
    ):
        self.calls += 1
        self.started.set()
        control.wait_until_running(cancel)
        if self.block:
            self.release.wait(10)
        if self.fail:
            raise RuntimeError("provider outcome unknown")
        screenshot = b"redacted screenshot"
        artifact_ref = publish_artifact("screenshot", screenshot)
        text = b"public observation"
        return {
            "status": "succeeded",
            "final_url": envelope.target_url,
            "final_origin": envelope.target_origin,
            "final_domain": envelope.target_domain,
            "text_sha256": hashlib.sha256(text).hexdigest(),
            "text_bytes": len(text),
            "artifact_ref": artifact_ref,
            "screenshot_sha256": hashlib.sha256(screenshot).hexdigest(),
            "screenshot_bytes": len(screenshot),
            "policy_flags": [],
            "clipboard": "not_accessed",
            "downloads": "blocked",
            "uploads": "unsupported",
            "headed_preview": True,
        }

    def stop(self, mission_id: str, *, timeout: float) -> bool:
        self.release.set()
        return True


def _bridge(
    tmp_path: Path,
    root: Path,
    store: MissionStore,
    driver: _Driver,
    vaults: dict[str, _Vault] | None = None,
) -> Phase11LiveMissionV1:
    vaults = vaults if vaults is not None else {}
    return Phase11LiveMissionV1(
        store,
        binding_dir=tmp_path / "bindings",
        allowed_roots=(root,),
        enabled=True,
        key=KEY,
        anchor_vault_factory=lambda reference: vaults.setdefault(
            reference.account, _Vault()
        ),
        governed_away_enabled=True,
        governed_away_driver=driver,
    )


def _create(bridge: Phase11LiveMissionV1, root: Path):
    return bridge.create_away(
        title="Observe exact public target",
        workspace_root=str(root),
        workspace_id="cyryx-labs",
        target_url="https://example.com/",
        allowed_domains=["example.com"],
        capture_screenshot=True,
        max_seconds=30,
    )


@pytest.fixture(autouse=True)
def _permission() -> None:
    set_permission_callback(lambda request: request["digest"])
    yield
    set_permission_callback(None)


def test_live_missionstore_executes_one_bound_read_and_persists_receipt(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    driver = _Driver()
    bridge = _bridge(tmp_path, root, store, driver)
    try:
        mission = _create(bridge, root)
        binding = bridge._read_binding(mission.id)
        assert binding["mission_type"] == "governed_browser_away_v1"
        away = binding["away"]
        assert away["mission_id"] == mission.id
        assert away["approval_digest"] == binding["plan_digest"]
        assert away["max_uses"] == 1
        assert away["paid_cost_budget"] == 0
        assert away["account_id"] == "none"
        assert binding["fixed_steps"][0]["tool"] == (
            "phase11_governed_browser_away_v1"
        )
        bridge.approve(mission.id)
        result = worker_once(store, "away-worker", bridge.runner, lease_seconds=5)
        assert result is not None and result.state == "succeeded"
        assert driver.calls == 1
        status = bridge.status(mission.id)
        assert status["away_mode"]["attempt_state"] == "receipt_persisted"
        persisted = json.dumps(store.events(mission.id), sort_keys=True)
        assert "public observation" not in persisted
        assert str(tmp_path) not in persisted
        assert "screenshot_ref" not in persisted
        assert "owner-local" in json.dumps(binding)
    finally:
        bridge.close()


def test_missing_chromium_runtime_blocks_creation_before_intent(
    tmp_path: Path,
) -> None:
    class MissingRuntimeDriver(PlaywrightBrowserDriverV1):
        @staticmethod
        def available():
            return False, "chromium-executable-missing"

    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    bridge = _bridge(tmp_path, root, store, MissingRuntimeDriver())
    try:
        with pytest.raises(Phase11LiveMissionError, match="executable-missing"):
            _create(bridge, root)
        assert store.list() == []
        assert not (tmp_path / "phase11-away-v1" / "attempts").exists()
    finally:
        bridge.close()


def test_attempt_unknown_is_never_redispatched_after_restart(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    driver = _Driver(fail=True)
    vaults: dict[str, _Vault] = {}
    bridge = _bridge(tmp_path, root, store, driver, vaults)
    mission = _create(bridge, root)
    bridge.approve(mission.id)
    first = worker_once(store, "away-worker", bridge.runner, lease_seconds=5)
    assert first is not None and first.state == "waiting"
    assert driver.calls == 1
    bridge.close()
    store = MissionStore(tmp_path / "missions.sqlite3")
    restarted_driver = _Driver()
    restarted = _bridge(tmp_path, root, store, restarted_driver, vaults)
    try:
        assert worker_once(
            store, "away-worker-restart", restarted.runner, lease_seconds=5
        ) is None
        assert restarted_driver.calls == 0
        status = restarted.status(mission.id)
        assert status["away_mode"]["attempt_state"] == "attempted_unknown"
        assert status["away_mode"]["redispatch_permitted"] is False
        still = restarted.reconcile_away_attempt(
            mission.id, decision="still_unknown"
        )
        assert still["state"] == "waiting"
        assert still["redispatch_permitted"] is False
        abandoned = restarted.reconcile_away_attempt(
            mission.id, decision="abandon"
        )
        assert abandoned["state"] == "cancelled"
        assert restarted_driver.calls == 0
    finally:
        restarted.close()


def test_pause_is_terminal_and_does_not_change_signed_action(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    driver = _Driver()
    bridge = _bridge(tmp_path, root, store, driver)
    try:
        mission = _create(bridge, root)
        original = bridge._read_binding(mission.id)["binding_digest"]
        bridge.away_control(mission.id, "pause")
        with pytest.raises(Phase11LiveMissionError, match="terminal"):
            bridge.away_control(mission.id, "resume")
        assert bridge._read_binding(mission.id)["binding_digest"] == original
        bridge.approve(mission.id)
        completed = worker_once(
            store, "away-worker", bridge.runner, lease_seconds=5
        )
        assert completed is not None and completed.state == "waiting"
        assert driver.calls == 0
    finally:
        bridge.close()


def test_active_pause_stops_driver_and_discards_late_result(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    driver = _Driver(block=True)
    bridge = _bridge(tmp_path, root, store, driver)
    mission = _create(bridge, root)
    bridge.approve(mission.id)
    outcome: list[object] = []
    thread = threading.Thread(
        target=lambda: outcome.append(
            worker_once(store, "away-worker", bridge.runner, lease_seconds=5)
        )
    )
    thread.start()
    assert driver.started.wait(5)
    started = time.monotonic()
    result = bridge.away_control(mission.id, "pause")
    assert time.monotonic() - started < 2
    assert result["away_control_state"] == "paused"
    thread.join(10)
    assert not thread.is_alive()
    assert outcome and outcome[0].state == "waiting"
    assert not any(
        item["event"] == "mission.succeeded" for item in store.events(mission.id)
    )
    bridge.close()


def test_stop_exception_is_exposed_and_control_remains_terminal(
    tmp_path: Path,
) -> None:
    class StopFailureDriver(_Driver):
        def stop(self, mission_id: str, *, timeout: float) -> bool:
            self.release.set()
            raise RuntimeError("owner-thread stop failed")

    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    driver = StopFailureDriver(block=True)
    bridge = _bridge(tmp_path, root, store, driver)
    mission = _create(bridge, root)
    bridge.approve(mission.id)
    thread = threading.Thread(
        target=lambda: worker_once(
            store, "away-worker", bridge.runner, lease_seconds=5
        )
    )
    thread.start()
    assert driver.started.wait(5)
    with pytest.raises(Phase11LiveMissionError, match="stop failed"):
        bridge.away_control(mission.id, "pause")
    thread.join(10)
    assert not thread.is_alive()
    assert bridge.status(mission.id)["away_mode"]["control_state"] == "paused"
    bridge.close()


def test_durable_kill_precedes_driver_stop_and_late_success_cannot_commit(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    driver = _Driver(block=True)
    bridge = _bridge(tmp_path, root, store, driver)
    mission = _create(bridge, root)
    bridge.approve(mission.id)
    outcome: list[object] = []
    thread = threading.Thread(
        target=lambda: outcome.append(
            worker_once(store, "away-worker", bridge.runner, lease_seconds=5)
        )
    )
    thread.start()
    assert driver.started.wait(5)
    assert bridge.request_kill(mission.id) is True
    events_before_cancel = store.events(mission.id)
    assert any(item["event"] == "phase11.kill" for item in events_before_cancel)
    store.cancel(mission.id)
    thread.join(10)
    assert not thread.is_alive()
    assert store.get(mission.id).state == "cancelled"
    assert not any(item["event"] == "mission.succeeded" for item in store.events(mission.id))
    assert driver.calls == 1
    bridge.close()


def test_global_kill_blocks_new_away_missions_and_native_computer_is_false(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    bridge = _bridge(tmp_path, root, store, _Driver())
    try:
        mission = _create(bridge, root)
        result = bridge.request_global_away_kill()
        assert result["global_kill"] == "latched"
        assert mission.id in result["missions_killed"]
        status = bridge.status(mission.id)
        assert status["away_mode"]["browser"] is False
        assert status["away_mode"]["computer"] is False
        assert (
            status["away_mode"]["computer_reason"]
            == "no_verified_window_dpi_driver"
        )
        with pytest.raises(Phase11LiveMissionError, match="global Away kill"):
            _create(bridge, root)
    finally:
        bridge.close()


def test_global_kill_reports_incomplete_on_corrupt_binding(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    bridge = _bridge(tmp_path, root, store, _Driver())
    try:
        mission = _create(bridge, root)
        binding = tmp_path / "bindings" / f"{mission.id}.binding.json"
        binding.write_text("{}", encoding="utf-8")
        result = bridge.request_global_away_kill()
        assert result["global_kill"] == "incomplete"
        assert result["new_away_actions_blocked"] is True
        assert result["failures"] == [
            {
                "mission_id": mission.id,
                "stage": "binding_validation",
                "error": "Phase11LiveMissionError",
            }
        ]
    finally:
        bridge.close()


def test_global_kill_reports_incomplete_when_mission_kill_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    bridge = _bridge(tmp_path, root, store, _Driver())
    try:
        mission = _create(bridge, root)

        def fail(_mission_id: str) -> bool:
            raise MissionError("append failed")

        monkeypatch.setattr(bridge, "request_kill", fail)
        result = bridge.request_global_away_kill()
        assert result["global_kill"] == "incomplete"
        assert result["missions_killed"] == []
        assert result["failures"] == [
            {
                "mission_id": mission.id,
                "stage": "durable_mission_kill",
                "error": "MissionError",
            }
        ]
    finally:
        bridge.close()


class _GlobalAwareDriver(_Driver):
    def execute(self, **kwargs):
        self.calls += 1
        self.started.set()
        deadline = time.monotonic() + 5
        while not kwargs["cancel"]() and time.monotonic() < deadline:
            time.sleep(0.01)
        return _Driver.execute(self, **kwargs)


def test_active_driver_observes_global_latch_without_per_mission_signal(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    driver = _GlobalAwareDriver()
    bridge = _bridge(tmp_path, root, store, driver)
    mission = _create(bridge, root)
    bridge.approve(mission.id)
    outcome: list[object] = []
    thread = threading.Thread(
        target=lambda: outcome.append(
            worker_once(store, "away-worker", bridge.runner, lease_seconds=5)
        )
    )
    thread.start()
    assert driver.started.wait(5)
    assert bridge.away_mode is not None
    bridge.away_mode.latch_global_kill()
    thread.join(10)
    assert not thread.is_alive()
    assert outcome and outcome[0].state == "waiting"
    assert not any(
        item["event"] == "mission.succeeded" for item in store.events(mission.id)
    )
    bridge.close()


def test_global_kill_does_not_report_complete_until_active_driver_exits(
    tmp_path: Path,
) -> None:
    class StickyDriver(_Driver):
        def stop(self, mission_id: str, *, timeout: float) -> bool:
            return False

    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    driver = StickyDriver(block=True)
    bridge = _bridge(tmp_path, root, store, driver)
    mission = _create(bridge, root)
    bridge.approve(mission.id)
    outcome: list[object] = []
    thread = threading.Thread(
        target=lambda: outcome.append(
            worker_once(store, "away-worker", bridge.runner, lease_seconds=5)
        )
    )
    thread.start()
    assert driver.started.wait(5)
    result = bridge.request_global_away_kill()
    assert result["global_kill"] == "incomplete"
    assert any(
        item["stage"] == "driver_stop_verification"
        for item in result["failures"]
    )
    driver.release.set()
    thread.join(10)
    assert not thread.is_alive()
    assert not any(
        item["event"] == "mission.succeeded" for item in store.events(mission.id)
    )
    bridge.close()


def test_phase11_close_kills_active_away_joins_and_allows_relaunch(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    driver = _Driver(block=True)
    bridge = _bridge(tmp_path, root, store, driver)
    mission = _create(bridge, root)
    bridge.approve(mission.id)
    thread = threading.Thread(
        target=lambda: worker_once(
            store, "away-worker", bridge.runner, lease_seconds=5
        )
    )
    thread.start()
    assert driver.started.wait(5)
    bridge.begin_shutdown()
    thread.join(10)
    assert not thread.is_alive()
    bridge.close(10.0)
    assert bridge.away_mode is not None
    assert bridge.away_mode.active_missions() == ()
    restarted_store = MissionStore(tmp_path / "missions.sqlite3")
    restarted = _bridge(tmp_path, root, restarted_store, _Driver())
    try:
        fresh = _create(restarted, root)
        assert fresh.state == "awaiting_approval"
    finally:
        restarted.close()


def test_worker_authority_observer_finishes_before_phase11_handles_close(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    bridge = _bridge(tmp_path, root, store, _Driver())
    mission = _create(bridge, root)
    bridge.approve(mission.id)
    observer_entered = threading.Event()
    observer_release = threading.Event()
    original_observer = bridge.anchor_current_authority

    def authority_observer(mission_id: str) -> None:
        observer_entered.set()
        assert bridge._read_binding(mission_id) is not None
        assert observer_release.wait(5)
        original_observer(mission_id)

    bridge.anchor_current_authority = authority_observer
    worker = MissionWorker(
        store,
        bridge.runner,
        owner="shutdown-order-worker",
        poll_interval=0.05,
        lease_seconds=5,
    )
    assert worker.start()
    assert observer_entered.wait(5)
    bridge.begin_shutdown()
    failures: list[BaseException] = []
    stages: list[str] = []

    def shutdown() -> None:
        try:
            assert worker.stop(5)
            stages.append("worker_joined")
            bridge.close(5)
            stages.append("phase11_closed")
        except BaseException as exc:
            failures.append(exc)

    shutdown_thread = threading.Thread(target=shutdown)
    shutdown_thread.start()
    time.sleep(0.1)
    assert shutdown_thread.is_alive()
    assert bridge._closing
    assert bridge._read_binding(mission.id) is not None
    observer_release.set()
    shutdown_thread.join(10)
    assert not shutdown_thread.is_alive()
    assert failures == []
    assert stages == ["worker_joined", "phase11_closed"]


def test_busy_away_root_degrades_only_away_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")

    def unavailable_mode(**_kwargs):
        raise GovernedAwayUnavailable("away_storage_transient_busy")

    monkeypatch.setattr(
        "core.phase11_live_mission_v1.GovernedAwayModeV1",
        unavailable_mode,
    )
    bridge = _bridge(tmp_path, root, store, _Driver())
    try:
        assert bridge.enabled is True
        assert bridge.away_mode is None
        assert bridge.away_unavailable_reason == "away_storage_transient_busy"
        with pytest.raises(
            Phase11LiveMissionError,
            match="away_storage_transient_busy",
        ):
            _create(bridge, root)
    finally:
        bridge.close()


def test_outer_binding_resign_cannot_authorize_tampered_inner_envelope(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    bridge = _bridge(tmp_path, root, store, _Driver())
    try:
        mission = _create(bridge, root)
        path = tmp_path / "bindings" / f"{mission.id}.binding.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["away"]["target_domain"] = "attacker.example"
        payload = {
            key: value
            for key, value in document.items()
            if key not in {"binding_digest", "signature"}
        }
        import hashlib
        import hmac

        digest = hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        document["binding_digest"] = digest
        document["signature"] = hmac.new(
            KEY,
            b"ONYX/PHASE11/LIVE-BINDING/V1\0" + digest.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(
            Phase11LiveMissionError,
            match="authority binding detail|Away envelope",
        ):
            bridge.status(mission.id)
    finally:
        bridge.close()
