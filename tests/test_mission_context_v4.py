from __future__ import annotations

import inspect
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import core.control_plane as control_plane
import core.control_plane_v4 as control_plane_v4
from core.mission_context_contracts import MissionContextContractError
from core.control_plane import ControlPlaneStore
from core.control_plane_v3 import _open_for_testing as open_v3
from core.control_plane_v4 import (
    ControlPlaneV4Store,
    ControlPlaneV4Error,
    ControlPlaneV4Disabled,
    ControlPlaneV4Conflict,
    ControlPlaneV4IntegrityError,
    ControlPlaneV4IOError,
    V4MissionMutation,
    _open_for_testing as open_v4,
    control_plane_v4_enabled,
    open_default,
)
from core.mission_context_v4 import (
    PHASES,
    PHASE_STATES,
    LegacyMissionContextAdapter,
    MissionAuthorityDrift,
    MissionContextDisabled,
    MissionContextIsolationError,
    MissionContextSpec,
    MissionContextStore,
    MissionPhaseConflict,
)
from core.missions import Mission, MissionAuthoritySnapshot, MissionStore
from core.permission_broker import set_permission_callback
from core.workspaces import LegacyWorkspaceAdapter, WorkspaceRegistry, _HOST_MARKER


class _MemoryVault:
    def __init__(self):
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, secret: bytes | bytearray) -> None:
        self.value = bytes(secret)

    def delete(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


def _fixture(tmp_path, monkeypatch):
    source_dir = tmp_path / "v3"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(source, enabled=True).initialize()
    registry.register("alpha", display_name="Alpha", workspace_class="cyryx")
    registry.register("beta", display_name="Beta", workspace_class="client")
    registry.register("inactive", display_name="Inactive", workspace_class="client")
    registry.set_active("inactive", False)
    LegacyWorkspaceAdapter(registry, _HOST_MARKER).resolve()
    v3_key, v3_state = _MemoryVault(), _MemoryVault()
    migrator, v3_owner = open_v3(
        source,
        journal_path=tmp_path / "v3.anchor",
        key_vault=v3_key,
        state_vault=v3_state,
        enabled=True,
    )
    migrator.migrate(v3_owner)
    before_v3 = source.path.read_bytes()
    v4_key, v4_state = _MemoryVault(), _MemoryVault()
    successor, v4_owner = open_v4(
        migrator,
        v3_owner,
        path=tmp_path / "v4.sqlite3",
        journal_path=tmp_path / "v4.anchor",
        key_vault=v4_key,
        state_vault=v4_state,
        enabled=True,
    )
    successor.migrate(v4_owner)
    assert source.path.read_bytes() == before_v3
    missions = MissionStore(tmp_path / "missions.sqlite3")
    context = MissionContextStore(successor, v4_owner, missions, enabled=True)
    successor._test_vaults = (v4_key, v4_state)
    return source, migrator, v3_owner, successor, v4_owner, missions, context


def _unmigrated_successor(tmp_path, monkeypatch, target):
    source_dir = tmp_path / "source-v3"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    WorkspaceRegistry(source, enabled=True).initialize().register(
        "alpha", display_name="Alpha", workspace_class="cyryx"
    )
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "source-v3.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    key, state = _MemoryVault(), _MemoryVault()
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=target,
        journal_path=tmp_path / "candidate-v4.anchor",
        key_vault=key,
        state_vault=state,
        enabled=True,
    )
    return successor, owner, key, state


def _spec(name="objective"):
    return MissionContextSpec.build(
        objective=name,
        definition_of_done=("verified outcome",),
        scope=("local",),
        exclusions=("external mutation",),
        data_classification="INTERNAL",
        allowed_targets=("workspace",),
        budget_dimensions={"seconds": 120},
        autonomy_mode="C",
        checkpoint="intake",
        rollback_plan="Disable the v4 extension.",
        recovery_status="clean",
    )


def _mission(store, title):
    return store.create(title, [{"tool": "local_note", "args": {"text": title}}])


def _approve(store, mission_id):
    set_permission_callback(lambda request: request["digest"])
    try:
        return store.approve(mission_id)
    finally:
        set_permission_callback(None)


class _PublicMissionReader:
    """Public get/events-shaped fixture; it exposes no database handle."""

    def __init__(self):
        self.missions = {}
        self.chains = {}

    def add(self, mission_id, state):
        self.missions[mission_id] = Mission(
            mission_id,
            mission_id,
            state,
            1.0,
            1.0,
            25,
            900.0,
            2,
            0.0,
            ["local_note"],
            0,
            None,
        )
        digest = (
            __import__("hashlib").sha256(f"{mission_id}:{state}".encode()).hexdigest()
        )
        self.chains[mission_id] = [
            {"seq": 1, "event": f"mission.{state}", "detail": {}, "event_hash": digest}
        ]

    def get(self, mission_id):
        if mission_id not in self.missions:
            raise KeyError(mission_id)
        return self.missions[mission_id]

    def events(self, mission_id):
        if mission_id not in self.chains:
            raise KeyError(mission_id)
        return [dict(item) for item in self.chains[mission_id]]

    def authority_snapshot(self, mission_id):
        mission = self.get(mission_id)
        event = self.events(mission_id)[-1]
        digest = (
            __import__("hashlib")
            .sha256(f"{mission_id}:{mission.state}:{event['event_hash']}".encode())
            .hexdigest()
        )
        return MissionAuthoritySnapshot(
            mission_id,
            mission.state,
            mission.current_step,
            mission.max_steps,
            mission.max_seconds,
            mission.max_retries,
            mission.provider_cost_limit,
            tuple(mission.tool_allowlist),
            int(event["seq"]),
            str(event["event_hash"]),
            digest,
        )


def test_flag_default_off_and_no_production_or_startup_activation(monkeypatch):
    assert not control_plane_v4_enabled({})
    assert control_plane_v4_enabled({"ONYX_CONTROL_PLANE_V4": "true"})
    monkeypatch.delenv("ONYX_CONTROL_PLANE_V4", raising=False)
    with pytest.raises(ControlPlaneV4Disabled):
        open_default()
    monkeypatch.setenv("ONYX_CONTROL_PLANE_V4", "1")
    with pytest.raises(ControlPlaneV4IOError):
        open_default()
    assert (
        inspect.signature(open_v4).parameters["enabled"].default
        is inspect.Parameter.empty
    )
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "core/missions.py",
        "core/mission_tools.py",
        "core/tool_audit.py",
    ):
        source = (__import__("pathlib").Path(__file__).parents[1] / relative).read_text(
            encoding="utf-8"
        )
        assert "control_plane_v4" not in source
        assert "mission_context_v4" not in source


def test_v3_to_v4_atomic_successor_and_basic_context(tmp_path, monkeypatch):
    source, migrator, v3_owner, successor, owner, missions, contexts = _fixture(
        tmp_path, monkeypatch
    )
    assert migrator.open(v3_owner).schema_version == 3
    assert successor.open(owner).schema_version == 4
    mission = _mission(missions, "Scoped mission")
    before = [
        (item["event"], item["event_hash"]) for item in missions.events(mission.id)
    ]
    record = contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="init-one",
    )
    assert record.revision == 0 and record.operational_phase == "WAITING_FOR_APPROVAL"
    assert contexts.get_context("alpha", mission.id) == record
    assert len(contexts.list_events("alpha", mission.id)) == 1
    assert [
        (item["event"], item["event_hash"]) for item in missions.events(mission.id)
    ] == before
    assert migrator.open(v3_owner).schema_version == 3
    with sqlite3.connect(successor.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert (
            connection.execute(
                "SELECT count(*) FROM mission_context_revisions"
            ).fetchone()[0]
            == 1
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE mission_context_revisions SET operational_phase='PLAN'"
            )


def test_phase_progression_binds_authority_and_terminal_reconcile(
    tmp_path, monkeypatch
):
    *_prefix, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Lifecycle")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="life-0",
    )
    _approve(missions, mission.id)
    with pytest.raises(MissionAuthorityDrift):
        contexts.get_context("alpha", mission.id)
    contexts.transition(
        "alpha", mission.id, "EXECUTE", expected_revision=0, mutation_id="life-1"
    )
    missions.run(
        mission.id,
        lambda _tool, _args, _key: {
            "status": "succeeded",
            "data": {},
            "evidence": [],
            "postconditions": [{"name": "done", "satisfied": True}],
        },
        backoff=lambda _seconds: None,
    )
    terminal = contexts.reconcile_terminal(
        "alpha", mission.id, expected_revision=1, mutation_id="life-2"
    )
    assert terminal.operational_phase == "COMPLETE" and terminal.revision == 2
    with pytest.raises(MissionPhaseConflict):
        contexts.transition(
            "alpha", mission.id, "ADAPT", expected_revision=2, mutation_id="life-3"
        )
    assert [
        event.event_type for event in contexts.list_events("alpha", mission.id)
    ] == ["initialized", "transitioned", "terminal_reconciled"]


def test_mutations_read_authority_once_before_and_once_after_commit(
    tmp_path, monkeypatch
):
    *_prefix, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Authority read budget")
    original = missions.authority_snapshot
    calls = []

    def counted(mission_id):
        calls.append(mission_id)
        return original(mission_id)

    monkeypatch.setattr(missions, "authority_snapshot", counted)
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="authority-budget-init",
    )
    assert calls == [mission.id, mission.id]
    calls.clear()
    _approve(missions, mission.id)
    contexts.transition(
        "alpha",
        mission.id,
        "EXECUTE",
        expected_revision=0,
        mutation_id="authority-budget-transition",
    )
    assert calls == [mission.id, mission.id]
    calls.clear()
    missions.run(
        mission.id,
        lambda _tool, _args, _key: {
            "status": "succeeded",
            "data": {},
            "evidence": [],
            "postconditions": [{"name": "done", "satisfied": True}],
        },
        backoff=lambda _seconds: None,
    )
    contexts.reconcile_terminal(
        "alpha",
        mission.id,
        expected_revision=1,
        mutation_id="authority-budget-reconcile",
    )
    assert calls == [mission.id, mission.id]


def test_mutation_returns_its_exact_revision_when_successor_commits_in_return_gap(
    tmp_path, monkeypatch
):
    *_prefix, successor, _owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Exact concurrent return")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="exact-return-init",
    )
    _approve(missions, mission.id)
    successor_result = []
    fired = False

    def commit_successor(point):
        nonlocal fired
        if point != "after_v4_mutation_commit_before_result_read" or fired:
            return
        fired = True
        successor._fault = lambda _point: None
        successor_result.append(
            contexts.transition(
                "alpha",
                mission.id,
                "VERIFY",
                expected_revision=1,
                mutation_id="exact-return-second",
            )
        )

    successor._fault = commit_successor
    first = contexts.transition(
        "alpha",
        mission.id,
        "EXECUTE",
        expected_revision=0,
        mutation_id="exact-return-first",
    )
    assert fired
    assert first.revision == 1 and first.operational_phase == "EXECUTE"
    assert successor_result[0].revision == 2
    assert contexts.get_context("alpha", mission.id).revision == 2


def test_idempotency_concurrency_isolation_and_extension_off(tmp_path, monkeypatch):
    _source, _migrator, _v3_owner, successor, owner, missions, contexts = _fixture(
        tmp_path, monkeypatch
    )
    one = _mission(missions, "One")
    first = contexts.initialize_context(
        "alpha",
        one.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="same-init",
    )
    replay = contexts.initialize_context(
        "alpha",
        one.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="same-init",
    )
    assert replay == first
    with pytest.raises(MissionPhaseConflict):
        contexts.initialize_context(
            "alpha",
            one.id,
            _spec("different"),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id="same-init",
        )
    with pytest.raises(MissionContextIsolationError):
        contexts.get_context("beta", one.id)
    with pytest.raises(MissionContextIsolationError):
        contexts.initialize_context(
            "legacy-default",
            _mission(missions, "Legacy denied").id,
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id="legacy-denied",
        )
    disabled = MissionContextStore(successor, owner, missions, enabled=False)
    unchanged = missions.get(one.id)
    with pytest.raises(MissionContextDisabled):
        disabled.get_context("alpha", one.id)
    assert missions.get(one.id) == unchanged

    two = _mission(missions, "Two")
    contexts.initialize_context(
        "alpha",
        two.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="two-init",
    )
    _approve(missions, two.id)

    def advance(tag):
        return contexts.transition(
            "alpha", two.id, "EXECUTE", expected_revision=0, mutation_id=tag
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = []
        for future in (pool.submit(advance, "race-a"), pool.submit(advance, "race-b")):
            try:
                outcomes.append(future.result())
            except MissionPhaseConflict:
                outcomes.append(None)
    assert sum(item is not None for item in outcomes) == 1
    assert contexts.get_context("alpha", two.id).revision == 1


def test_corruption_and_unknown_version_fail_closed_without_mission_write(
    tmp_path, monkeypatch
):
    *_prefix, successor, owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Corruption")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="corrupt-init",
    )
    before = missions.get(mission.id), missions.events(mission.id)
    # The anchor rejects even a coherent-looking offline schema-version edit.
    connection = sqlite3.connect(successor.path)
    try:
        triggers = connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='schema_metadata'"
        ).fetchall()
        for name, _sql in triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute(
            "UPDATE schema_metadata SET value='5' WHERE key='schema_version'"
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(Exception):
        contexts.get_context("alpha", mission.id)
    assert (missions.get(mission.id), missions.events(mission.id)) == before


def test_all_exact_phases_accept_only_their_documented_durable_states(
    tmp_path, monkeypatch
):
    *_prefix, successor, owner, _missions, _contexts = _fixture(tmp_path, monkeypatch)
    reader = _PublicMissionReader()
    contexts = MissionContextStore(successor, owner, reader, enabled=True)
    all_states = {state for states in PHASE_STATES.values() for state in states}
    assert set(PHASES) == set(PHASE_STATES)
    for index, phase in enumerate(sorted(PHASES)):
        allowed = sorted(PHASE_STATES[phase])
        mission_id = f"phase-positive-{index}"
        reader.add(mission_id, allowed[0])
        record = contexts.initialize_context(
            "alpha",
            mission_id,
            _spec(phase),
            operational_phase=phase,
            mutation_id=f"phase-positive-{index}",
        )
        assert record.operational_phase == phase
        denied_state = next(
            state for state in sorted(all_states) if state not in PHASE_STATES[phase]
        )
        denied_id = f"phase-negative-{index}"
        reader.add(denied_id, denied_state)
        with pytest.raises(MissionPhaseConflict):
            contexts.initialize_context(
                "alpha",
                denied_id,
                _spec(phase),
                operational_phase=phase,
                mutation_id=f"phase-negative-{index}",
            )


def test_real_create_starts_awaiting_and_does_not_invent_early_phase(
    tmp_path, monkeypatch
):
    *_prefix, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "No invented draft history")
    assert mission.state == "awaiting_approval"
    for phase in ("INTAKE", "CLARIFY_OR_SCOPE", "RESEARCH", "PLAN", "POLICY_CHECK"):
        with pytest.raises(MissionPhaseConflict):
            contexts.initialize_context(
                "alpha",
                mission.id,
                _spec(),
                operational_phase=phase,
                mutation_id=f"deny-{phase.lower()}",
            )
    record = contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="observed-awaiting",
    )
    assert record.revision == 0
    assert [event.to_phase for event in contexts.list_events("alpha", mission.id)] == [
        "WAITING_FOR_APPROVAL"
    ]


def test_reopen_restart_and_exact_replay_have_one_revision_event(tmp_path, monkeypatch):
    *_prefix, successor, owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Restart")
    first = contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="restart-init",
    )
    key_vault, state_vault = successor._test_vaults
    reopened, reopened_owner = open_v4(
        successor.source,
        successor.source_owner,
        path=successor.path,
        journal_path=successor.anchor._journal_path,
        key_vault=key_vault,
        state_vault=state_vault,
        enabled=True,
    )
    assert reopened.open(reopened_owner).state_root == successor.open(owner).state_root
    restarted_contexts = MissionContextStore(
        reopened, reopened_owner, missions, enabled=True
    )
    assert restarted_contexts.get_context("alpha", mission.id) == first
    assert (
        restarted_contexts.initialize_context(
            "alpha",
            mission.id,
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id="restart-init",
        )
        == first
    )
    connection = sqlite3.connect(successor.path)
    try:
        assert (
            connection.execute(
                "SELECT count(*) FROM mission_context_revisions WHERE mission_id=?",
                (mission.id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM mission_phase_events WHERE mission_id=?",
                (mission.id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM mutation_journal WHERE mission_id=?",
                (mission.id,),
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "fault_point",
    (
        "before_anchor_prepare",
        "after_anchor_prepare",
        "after_sqlite_commit",
        "after_anchor_finalize",
    ),
)
def test_writer_crash_seams_recover_without_duplicate_revision(
    tmp_path, monkeypatch, fault_point
):
    *_prefix, successor, _owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, f"Crash {fault_point}")

    class _Crash(BaseException):
        pass

    fired = False

    def fault(point):
        nonlocal fired
        if point == fault_point and not fired:
            fired = True
            raise _Crash()

    successor._fault = fault
    with pytest.raises(_Crash):
        contexts.initialize_context(
            "alpha",
            mission.id,
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id=f"crash-{fault_point}",
        )
    successor._fault = lambda _point: None
    result = contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id=f"crash-{fault_point}",
    )
    assert result.revision == 0
    assert len(contexts.list_events("alpha", mission.id)) == 1


@pytest.mark.parametrize(
    "fault_point", ("before_v4_publish", "after_v4_publish_before_anchor")
)
def test_migration_publication_crash_is_atomic_or_recoverable(
    tmp_path, monkeypatch, fault_point
):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(source, enabled=True).initialize()
    registry.register("alpha", display_name="Alpha", workspace_class="cyryx")
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "source.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    key_vault, state_vault = _MemoryVault(), _MemoryVault()
    target = tmp_path / "successor.sqlite3"
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=target,
        journal_path=tmp_path / "target.anchor",
        key_vault=key_vault,
        state_vault=state_vault,
        enabled=True,
    )

    class _Crash(BaseException):
        pass

    successor._fault = lambda point: (
        (_ for _ in ()).throw(_Crash()) if point == fault_point else None
    )
    with pytest.raises(_Crash):
        successor.migrate(owner)
    assert not target.exists()
    assert key_vault.value is None and state_vault.value is None
    assert not (tmp_path / "target.anchor").exists()
    recovered, recovered_owner = open_v4(
        migrator,
        source_owner,
        path=target,
        journal_path=tmp_path / "target.anchor",
        key_vault=key_vault,
        state_vault=state_vault,
        enabled=True,
    )
    assert recovered.migrate(recovered_owner).schema_version == 4


def test_missing_inactive_unknown_mission_and_explicit_legacy_only(
    tmp_path, monkeypatch
):
    *_prefix, successor, owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Boundaries")
    with pytest.raises(MissionContextIsolationError):
        contexts.initialize_context(
            "missing",
            mission.id,
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id="missing-workspace",
        )
    with pytest.raises(MissionContextIsolationError):
        contexts.initialize_context(
            "inactive",
            mission.id,
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id="inactive-workspace",
        )
    with pytest.raises(KeyError):
        contexts.initialize_context(
            "alpha",
            "unknown-mission",
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id="unknown-mission",
        )
    with pytest.raises(MissionContextIsolationError):
        contexts.initialize_context(
            "legacy-default",
            mission.id,
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id="implicit-legacy",
        )
    legacy_mission = _mission(missions, "Explicit legacy")
    adapter = LegacyMissionContextAdapter(contexts)
    legacy = adapter.initialize_context(
        legacy_mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="explicit-legacy",
    )
    assert legacy.workspace_id == "legacy-default"
    with pytest.raises(TypeError):
        LegacyMissionContextAdapter(object())


def test_stale_revision_and_concurrent_different_missions(tmp_path, monkeypatch):
    *_prefix, missions, contexts = _fixture(tmp_path, monkeypatch)
    first, second = (
        _mission(missions, "Concurrent first"),
        _mission(missions, "Concurrent second"),
    )
    for index, mission in enumerate((first, second)):
        contexts.initialize_context(
            "alpha",
            mission.id,
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id=f"concurrent-init-{index}",
        )
        _approve(missions, mission.id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda item: contexts.transition(
                    "alpha",
                    item[1].id,
                    "EXECUTE",
                    expected_revision=0,
                    mutation_id=f"concurrent-transition-{item[0]}",
                ),
                enumerate((first, second)),
            )
        )
    assert [record.revision for record in results] == [1, 1]
    with pytest.raises(MissionPhaseConflict):
        contexts.transition(
            "alpha",
            first.id,
            "VERIFY",
            expected_revision=0,
            mutation_id="stale-revision",
        )


@pytest.mark.parametrize("tamper", ("update", "delete", "extra"))
def test_revision_event_journal_tamper_fails_anchor_closed(
    tmp_path, monkeypatch, tamper
):
    *_prefix, successor, owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, f"Tamper {tamper}")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id=f"tamper-init-{tamper}",
    )
    connection = sqlite3.connect(successor.path)
    try:
        if tamper == "extra":
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                "INSERT INTO mutation_journal VALUES(?,?,?,?,?,?,?)",
                (
                    "extra-mutation",
                    mission.id,
                    99,
                    "transition",
                    "a" * 64,
                    "b" * 64,
                    "2026-01-01T00:00:00+00:00",
                ),
            )
        else:
            tables = (
                "mission_context_revisions",
                "mission_phase_events",
                "mutation_journal",
            )
            triggers = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name IN (?,?,?)",
                tables,
            ).fetchall()
            for (name,) in triggers:
                connection.execute(f'DROP TRIGGER "{name}"')
            if tamper == "update":
                connection.execute(
                    "UPDATE mission_context_revisions SET revision_sha256=? WHERE mission_id=?",
                    ("f" * 64, mission.id),
                )
            else:
                connection.execute(
                    "DELETE FROM mutation_journal WHERE mission_id=?", (mission.id,)
                )
        connection.commit()
    finally:
        connection.close()
    before = missions.get(mission.id), missions.events(mission.id)
    with pytest.raises(ControlPlaneV4Error):
        if tamper == "extra":
            successor.verify_integrity(owner)
        else:
            contexts.get_context("alpha", mission.id)
    assert (missions.get(mission.id), missions.events(mission.id)) == before


def test_external_anchor_rollback_is_detected(tmp_path, monkeypatch):
    *_prefix, successor, _owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    key_vault, state_vault = successor._test_vaults
    old_state = state_vault.value
    mission = _mission(missions, "Rollback")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="rollback-init",
    )
    assert state_vault.value != old_state
    state_vault.value = old_state
    with pytest.raises(ControlPlaneV4Error):
        contexts.get_context("alpha", mission.id)


def test_mission_database_logical_bytes_unchanged_by_context_only_work(
    tmp_path, monkeypatch
):
    *_prefix, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "No mission write")
    before_main = missions.path.read_bytes()
    wal = __import__("pathlib").Path(str(missions.path) + "-wal")
    before_wal = wal.read_bytes() if wal.exists() else None
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="no-mission-write",
    )
    contexts.get_context("alpha", mission.id)
    contexts.list_events("alpha", mission.id)
    assert missions.path.read_bytes() == before_main
    assert (wal.read_bytes() if wal.exists() else None) == before_wal


def test_v4_target_hardlink_is_rejected_without_source_change(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(source, enabled=True).initialize()
    registry.register("alpha", display_name="Alpha", workspace_class="cyryx")
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "source.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    source_before = source.path.read_bytes()
    innocent = tmp_path / "innocent.sqlite3"
    innocent.write_bytes(b"not a database")
    linked = tmp_path / "linked.sqlite3"
    try:
        os.link(innocent, linked)
    except OSError:
        pytest.skip("hard links unavailable")
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=linked,
        journal_path=tmp_path / "target.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    with pytest.raises(ControlPlaneV4Error):
        successor.migrate(owner)
    assert source.path.read_bytes() == source_before


@pytest.mark.parametrize("suffix", ("-wal", "-shm"))
def test_v4_wal_and_shm_hardlinks_are_rejected(tmp_path, monkeypatch, suffix):
    *_prefix, successor, _owner, _missions, _contexts = _fixture(tmp_path, monkeypatch)
    writer = sqlite3.connect(successor.path, isolation_level=None)
    link = tmp_path / f"linked{suffix}"
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("BEGIN IMMEDIATE")
        sidecar = Path(str(successor.path) + suffix)
        assert sidecar.exists()
        os.link(sidecar, link)
        with pytest.raises(ControlPlaneV4IntegrityError):
            control_plane_v4._connect(successor.path, readonly=True)
    finally:
        if link.exists():
            link.unlink()
        if writer.in_transaction:
            writer.execute("ROLLBACK")
        writer.close()


def test_v4_legitimate_wal_shm_recreation_remains_openable(tmp_path, monkeypatch):
    *_prefix, successor, owner, _missions, _contexts = _fixture(tmp_path, monkeypatch)
    for _index in range(8):
        writer = sqlite3.connect(successor.path, isolation_level=None)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("BEGIN IMMEDIATE")
            assert Path(str(successor.path) + "-wal").exists()
            assert Path(str(successor.path) + "-shm").exists()
            assert successor.open(owner).schema_version == 4
            writer.execute("ROLLBACK")
        finally:
            if writer.in_transaction:
                writer.execute("ROLLBACK")
            writer.close()
        assert successor.open(owner).schema_version == 4


@pytest.mark.parametrize("tamper", ("row", "future_version", "schema_drop"))
def test_v3_source_tamper_future_or_corruption_blocks_successor(
    tmp_path, monkeypatch, tamper
):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(source, enabled=True).initialize()
    registry.register("alpha", display_name="Alpha", workspace_class="cyryx")
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "source.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    connection = sqlite3.connect(source.path)
    try:
        if tamper == "row":
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='workspaces'"
            ).fetchall():
                connection.execute(f'DROP TRIGGER "{name}"')
            connection.execute(
                "UPDATE workspaces SET status='inactive' WHERE workspace_id='alpha'"
            )
        elif tamper == "future_version":
            connection.execute("PRAGMA user_version=99")
        else:
            connection.execute("DROP TABLE operational_mmr_edges")
        connection.commit()
    finally:
        connection.close()
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=tmp_path / "v4.sqlite3",
        journal_path=tmp_path / "target.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    with pytest.raises(ControlPlaneV4Error):
        successor.migrate(owner)
    assert not successor.path.exists()


def test_populated_legacy_provenance_requires_explicit_reviewed_adoption(
    tmp_path, monkeypatch
):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    missions = MissionStore(tmp_path / "missions.sqlite3")
    eligible = _mission(missions, "Eligible legacy")
    pending = _mission(missions, "Pending legacy")
    source = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(source, enabled=True).initialize()
    LegacyWorkspaceAdapter(registry, _HOST_MARKER).resolve()
    now = "2026-07-16T00:00:00+00:00"
    source._require_connection().executemany(
        "INSERT INTO mission_contexts VALUES(?,?,?,?,?,?,?)",
        (
            (eligible.id, "legacy-default", 2, "LEGACY_BACKFILLED", "{}", now, now),
            (pending.id, "legacy-default", 2, "PENDING_REVIEW", "{}", now, now),
        ),
    )
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "source.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=tmp_path / "v4.sqlite3",
        journal_path=tmp_path / "target.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    successor.migrate(owner)
    generic = MissionContextStore(successor, owner, missions, enabled=True)
    with pytest.raises(MissionContextIsolationError):
        generic.initialize_context(
            "legacy-default",
            eligible.id,
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id="generic-denied",
        )
    adapter = LegacyMissionContextAdapter(generic)
    original_authority = missions.authority_snapshot
    authority_calls = []

    def counted_authority(mission_id):
        authority_calls.append(mission_id)
        return original_authority(mission_id)

    monkeypatch.setattr(missions, "authority_snapshot", counted_authority)
    adopted = adapter.adopt_legacy_context(
        eligible.id,
        _spec(),
        mutation_id="legacy-adopted",
        reviewed_source_sha256=successor.read_legacy_provenance(owner, eligible.id)[
            "source_row_sha256"
        ],
    )
    assert authority_calls == [eligible.id, eligible.id]
    assert adopted.workspace_id == "legacy-default"
    assert adopted.operational_phase == "WAITING_FOR_APPROVAL"
    with pytest.raises(MissionContextIsolationError):
        generic.get_context("legacy-default", eligible.id)
    with pytest.raises(MissionContextIsolationError):
        generic.list_events("legacy-default", eligible.id)
    with pytest.raises(MissionContextIsolationError):
        generic.transition(
            "legacy-default",
            eligible.id,
            "EXECUTE",
            expected_revision=0,
            mutation_id="generic-transition-denied",
        )
    with pytest.raises(MissionContextIsolationError):
        generic.reconcile_terminal(
            "legacy-default",
            eligible.id,
            expected_revision=0,
            mutation_id="generic-reconcile-denied",
        )
    _approve(missions, eligible.id)
    transitioned = adapter.transition(
        eligible.id,
        "EXECUTE",
        expected_revision=0,
        mutation_id="legacy-transition-after-adoption",
    )
    assert transitioned.revision == 1 and transitioned.operational_phase == "EXECUTE"
    assert adapter.get_context(eligible.id) == transitioned
    assert len(adapter.list_events(eligible.id)) == 2
    with pytest.raises(MissionContextIsolationError):
        adapter.adopt_legacy_context(
            pending.id,
            _spec(),
            mutation_id="pending-denied",
            reviewed_source_sha256=successor.read_legacy_provenance(owner, pending.id)[
                "source_row_sha256"
            ],
        )
    connection = sqlite3.connect(successor.path)
    try:
        assert (
            connection.execute(
                "SELECT count(*) FROM legacy_context_provenance"
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM mission_context_revisions"
            ).fetchone()[0]
            == 2
        )
    finally:
        connection.close()


def _create_versioned_mission_fixture(path, version):
    connection = sqlite3.connect(path)
    lease = (
        ",lease_owner TEXT,lease_expires REAL,lease_heartbeat REAL"
        if version == 3
        else ""
    )
    event_hashes = (
        ",prev_hash TEXT NOT NULL DEFAULT '',event_hash TEXT NOT NULL DEFAULT ''"
        if version >= 2
        else ""
    )
    connection.executescript(f"""
        CREATE TABLE schema_meta(version INTEGER NOT NULL);
        INSERT INTO schema_meta VALUES({version});
        CREATE TABLE missions(id TEXT PRIMARY KEY,title TEXT NOT NULL,state TEXT NOT NULL,
          created_at REAL NOT NULL,updated_at REAL NOT NULL,max_steps INTEGER NOT NULL,max_seconds REAL NOT NULL,
          max_retries INTEGER NOT NULL,provider_cost_limit REAL NOT NULL,tool_allowlist TEXT NOT NULL,
          current_step INTEGER NOT NULL DEFAULT 0,error TEXT,deadline REAL,approval_digest TEXT{lease});
        CREATE TABLE steps(id TEXT PRIMARY KEY,mission_id TEXT NOT NULL REFERENCES missions(id),
          position INTEGER NOT NULL,tool TEXT NOT NULL,args TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,idempotency_key TEXT NOT NULL UNIQUE,result TEXT,error TEXT,
          wait_reason TEXT,started_at REAL,completed_at REAL,UNIQUE(mission_id,position));
        CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,mission_id TEXT NOT NULL,
          timestamp REAL NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL{event_hashes});
        CREATE INDEX events_mission ON events(mission_id,seq);
    """)
    mission_id = f"fixture-v{version}"
    base = (
        mission_id,
        f"Fixture v{version}",
        "awaiting_approval",
        1.0,
        1.0,
        25,
        900.0,
        2,
        0.0,
        '["local_note"]',
        0,
        None,
        None,
        None,
    )
    if version == 3:
        base += (None, None, None)
    placeholders = ",".join("?" for _ in base)
    connection.execute(f"INSERT INTO missions VALUES({placeholders})", base)
    connection.execute(
        "INSERT INTO steps VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            f"step-v{version}",
            mission_id,
            0,
            "local_note",
            "{}",
            "pending",
            0,
            __import__("hashlib")
            .sha256(f"{mission_id}:0:local_note:{{}}".encode())
            .hexdigest(),
            None,
            None,
            None,
            None,
            None,
        ),
    )
    detail = "{}"
    if version >= 2:
        digest = (
            __import__("hashlib")
            .sha256(f"{mission_id}\0{1.0:.9f}\0mission.created\0{detail}\0".encode())
            .hexdigest()
        )
        connection.execute(
            "INSERT INTO events(mission_id,timestamp,event,detail,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
            (mission_id, 1.0, "mission.created", detail, "", digest),
        )
    else:
        connection.execute(
            "INSERT INTO events(mission_id,timestamp,event,detail) VALUES(?,?,?,?)",
            (mission_id, 1.0, "mission.created", detail),
        )
    if version == 3:
        connection.executescript("""
            CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'mission events are immutable'); END;
            CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'mission events are immutable'); END;
        """)
    connection.commit()
    connection.close()
    return mission_id


def test_public_mission_schema_v1_v2_v3_fixtures_remain_compatible(
    tmp_path, monkeypatch
):
    *_prefix, successor, owner, _missions, _contexts = _fixture(tmp_path, monkeypatch)
    for version in (1, 2, 3):
        path = tmp_path / f"mission-v{version}.sqlite3"
        mission_id = _create_versioned_mission_fixture(path, version)
        store = MissionStore(path)
        before = store.get(mission_id)
        contexts = MissionContextStore(successor, owner, store, enabled=True)
        record = contexts.initialize_context(
            "alpha",
            mission_id,
            _spec(f"schema v{version}"),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id=f"schema-v{version}",
        )
        assert record.mission_id == mission_id
        assert store.get(mission_id) == before
        assert store.events(mission_id)[-1]["event_hash"] == record.mission_event_sha256


def test_same_name_noop_trigger_is_rejected_by_observed_schema(tmp_path, monkeypatch):
    *_prefix, successor, owner, _missions, _contexts = _fixture(tmp_path, monkeypatch)
    connection = sqlite3.connect(successor.path)
    try:
        connection.execute("DROP TRIGGER deny_mission_context_revisions_update")
        connection.execute(
            "CREATE TRIGGER deny_mission_context_revisions_update "
            "BEFORE UPDATE ON mission_context_revisions BEGIN SELECT 1; END"
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ControlPlaneV4IntegrityError) as failure:
        successor.open(owner)
    assert type(failure.value) is ControlPlaneV4IntegrityError
    assert failure.value.__cause__ is None


def test_controlled_post_publish_failure_rolls_back_and_retry_is_clean(
    tmp_path, monkeypatch
):
    source_dir = tmp_path / "source-extra"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    WorkspaceRegistry(source, enabled=True).initialize().register(
        "alpha", display_name="Alpha", workspace_class="cyryx"
    )
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "source-extra.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    key_vault, state_vault = _MemoryVault(), _MemoryVault()
    target = tmp_path / "unanchored-extra.sqlite3"
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=target,
        journal_path=tmp_path / "extra.anchor",
        key_vault=key_vault,
        state_vault=state_vault,
        enabled=True,
    )

    successor._fault = lambda point: (
        (_ for _ in ()).throw(RuntimeError("controlled post-publish failure"))
        if point == "after_v4_publish_before_anchor"
        else None
    )
    with pytest.raises(RuntimeError, match="controlled post-publish failure"):
        successor.migrate(owner)
    assert key_vault.value is None and state_vault.value is None
    assert not target.exists()
    assert not successor.journal_path.exists()
    assert not list(tmp_path.glob(".onyx-v4-*"))

    successor._fault = lambda _point: None
    successor.migrate(owner)
    assert target.is_file()
    assert key_vault.value is not None and state_vault.value is not None
    successor.open(owner)


def test_v3_source_hardlink_is_rejected_before_capture(tmp_path, monkeypatch):
    source_dir = tmp_path / "source-hardlink"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    WorkspaceRegistry(source, enabled=True).initialize().register(
        "alpha", display_name="Alpha", workspace_class="cyryx"
    )
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "source-hardlink.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    extra_link = tmp_path / "source-hardlink-copy.sqlite3"
    try:
        os.link(source.path, extra_link)
    except OSError:
        pytest.skip("hard links unavailable")
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=tmp_path / "hardlink-v4.sqlite3",
        journal_path=tmp_path / "hardlink-v4.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    with pytest.raises(ControlPlaneV4IntegrityError):
        successor.migrate(owner)
    assert not successor.path.exists()


def test_v3_source_reparse_or_symlink_is_rejected_before_capture(tmp_path, monkeypatch):
    source_dir = tmp_path / "source-reparse"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    WorkspaceRegistry(source, enabled=True).initialize().register(
        "alpha", display_name="Alpha", workspace_class="cyryx"
    )
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "source-reparse.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    real = tmp_path / "source-real.sqlite3"
    try:
        os.replace(source.path, real)
        source.path.symlink_to(real)
    except OSError:
        if real.exists() and not source.path.exists():
            os.replace(real, source.path)
        pytest.skip("symlink/reparse creation unavailable")
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=tmp_path / "reparse-v4.sqlite3",
        journal_path=tmp_path / "reparse-v4.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    with pytest.raises(ControlPlaneV4IntegrityError):
        successor.migrate(owner)
    assert not successor.path.exists()


def test_same_size_source_mutation_during_snapshot_capture_is_rejected(
    tmp_path, monkeypatch
):
    source_dir = tmp_path / "source-race"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    WorkspaceRegistry(source, enabled=True).initialize().register(
        "alpha", display_name="Alpha", workspace_class="cyryx"
    )
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "source-race.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    original = source.path.read_bytes()
    changed = bytearray(original)
    changed[-1] ^= 1
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=tmp_path / "race-v4.sqlite3",
        journal_path=tmp_path / "race-v4.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    successor._fault = lambda point: (
        source.path.write_bytes(changed)
        if point == "after_v3_snapshot_before_revalidate"
        else None
    )
    with pytest.raises(ControlPlaneV4IntegrityError):
        successor.migrate(owner)
    assert source.path.stat().st_size == len(original)
    assert not successor.path.exists()


def test_target_swap_between_anchor_verify_and_read_is_rejected(tmp_path, monkeypatch):
    *_prefix, successor, _owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Read swap")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="read-swap-init",
    )
    replacement = tmp_path / "replacement.sqlite3"
    replacement.write_bytes(successor.path.read_bytes())
    _original = tmp_path / "original.sqlite3"

    def swap(point):
        if point == "before_v4_read_open":
            successor._fault = lambda _point: None
            os.replace(successor.path, _original)
            os.replace(replacement, successor.path)

    successor._fault = swap
    with pytest.raises(ControlPlaneV4IntegrityError):
        contexts.get_context("alpha", mission.id)


def test_operational_surface_has_no_sql_cursor_or_connection_escape(
    tmp_path, monkeypatch
):
    *_prefix, successor, owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Typed surface")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="typed-surface-init",
    )
    bundle = successor.read_context_bundle(owner, "alpha", mission.id)
    assert not hasattr(successor, "reader")
    assert not hasattr(successor, "writer")
    assert all(type(row) is dict for row in bundle)
    assert all(
        not hasattr(row, "execute") and not hasattr(row, "connection") for row in bundle
    )
    assert "owner" not in contexts.__dict__ and "control_plane" not in contexts.__dict__
    assert not hasattr(successor, "owner") and not hasattr(successor, "control_plane")
    assert "not a python security boundary" in ControlPlaneV4Store.__doc__.casefold()
    assert "same-process" in inspect.getdoc(control_plane_v4).casefold()


def test_reader_anchor_data_and_proofs_share_one_explicit_transaction(
    tmp_path, monkeypatch
):
    *_prefix, successor, _owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "One snapshot")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="one-snapshot-init",
    )
    statements = []
    original_connect = control_plane_v4._connect
    original_snapshot = control_plane_v4._V4AnchorPort.snapshot
    candidate_checks = []

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    def checked_snapshot(port):
        candidate_checks.append(
            port._candidate is not None and port._candidate.in_transaction
        )
        return original_snapshot(port)

    monkeypatch.setattr(control_plane_v4, "_connect", traced_connect)
    monkeypatch.setattr(control_plane_v4._V4AnchorPort, "snapshot", checked_snapshot)
    assert contexts.get_context("alpha", mission.id).revision == 0
    normalized = [item.strip().upper() for item in statements]
    begin = normalized.index("BEGIN")
    rollback = normalized.index("ROLLBACK")
    selected = [
        index for index, item in enumerate(normalized) if item.startswith("SELECT")
    ]
    assert selected and all(begin < index < rollback for index in selected)
    assert normalized.count("BEGIN") == 1 and normalized.count("ROLLBACK") == 1
    assert candidate_checks and all(candidate_checks)


def test_cold_audit_uses_shared_exact_payload_and_transition_contracts(
    tmp_path, monkeypatch
):
    *_prefix, successor, _owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Cold shared contracts")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="cold-shared-init",
    )
    _approve(missions, mission.id)
    contexts.transition(
        "alpha",
        mission.id,
        "EXECUTE",
        expected_revision=0,
        mutation_id="cold-shared-transition",
    )
    connection = control_plane_v4._connect(successor.path, readonly=True)
    original_parse = control_plane_v4.parse_context_json
    try:
        monkeypatch.setattr(
            control_plane_v4,
            "parse_context_json",
            lambda _value: (_ for _ in ()).throw(
                MissionContextContractError("invalid typed context")
            ),
        )
        with pytest.raises(ControlPlaneV4IntegrityError, match="invalid typed context"):
            control_plane_v4._validate_semantics(connection)
        monkeypatch.setattr(control_plane_v4, "parse_context_json", original_parse)
        monkeypatch.setattr(
            control_plane_v4,
            "validate_storage_transition",
            lambda *_args: (_ for _ in ()).throw(
                MissionContextContractError("invalid typed transition")
            ),
        )
        with pytest.raises(
            ControlPlaneV4IntegrityError, match="invalid typed transition"
        ):
            control_plane_v4._validate_semantics(connection)
    finally:
        connection.close()


def test_reconcile_flag_off_has_no_missionstore_side_effect(tmp_path, monkeypatch):
    *_prefix, successor, owner, _missions, _contexts = _fixture(tmp_path, monkeypatch)

    class _NeverRead:
        calls = 0

        def get(self, _mission_id):
            self.calls += 1
            raise AssertionError("disabled reconcile touched MissionStore")

        def events(self, _mission_id):
            self.calls += 1
            raise AssertionError("disabled reconcile touched MissionStore")

    missions = _NeverRead()
    disabled = MissionContextStore(successor, owner, missions, enabled=False)
    with pytest.raises(MissionContextDisabled):
        disabled.reconcile_terminal(
            "alpha",
            "disabled-mission",
            expected_revision=0,
            mutation_id="disabled-reconcile",
        )
    assert missions.calls == 0


@pytest.mark.parametrize("tamper", ("revision_gap", "event_tail", "result_hash"))
def test_cold_semantic_audit_rejects_gap_tail_and_result_tamper(
    tmp_path, monkeypatch, tamper
):
    *_prefix, successor, _owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, f"Semantic {tamper}")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id=f"semantic-{tamper}-0",
    )
    _approve(missions, mission.id)
    contexts.transition(
        "alpha",
        mission.id,
        "EXECUTE",
        expected_revision=0,
        mutation_id=f"semantic-{tamper}-1",
    )
    connection = sqlite3.connect(successor.path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        targets = {
            "revision_gap": "mission_context_revisions",
            "event_tail": "mission_phase_events",
            "result_hash": "mutation_journal",
        }
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
            (targets[tamper],),
        ).fetchall():
            connection.execute(f'DROP TRIGGER "{name}"')
        if tamper == "revision_gap":
            connection.execute(
                "DELETE FROM mission_context_revisions WHERE mission_id=? AND revision=1",
                (mission.id,),
            )
        elif tamper == "event_tail":
            connection.execute(
                "DELETE FROM mission_phase_events WHERE mission_id=? AND revision=1",
                (mission.id,),
            )
        else:
            connection.execute(
                "UPDATE mutation_journal SET result_sha256=? WHERE mission_id=? AND revision=1",
                ("f" * 64, mission.id),
            )
        connection.commit()
        with pytest.raises(ControlPlaneV4IntegrityError):
            control_plane_v4._validate_semantics(connection)
    finally:
        connection.close()


def test_transition_replay_with_divergent_payload_is_rejected(tmp_path, monkeypatch):
    *_prefix, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Divergent replay")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="divergent-init",
    )
    _approve(missions, mission.id)
    contexts.transition(
        "alpha",
        mission.id,
        "EXECUTE",
        expected_revision=0,
        mutation_id="divergent-transition",
        updates={"checkpoint": "first"},
    )
    with pytest.raises(MissionPhaseConflict):
        contexts.transition(
            "alpha",
            mission.id,
            "EXECUTE",
            expected_revision=0,
            mutation_id="divergent-transition",
            updates={"checkpoint": "different"},
        )


def test_transition_replay_after_later_revision_returns_original_proven_result(
    tmp_path, monkeypatch
):
    *_prefix, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Historical replay")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="historical-replay-init",
    )
    _approve(missions, mission.id)
    original = contexts.transition(
        "alpha",
        mission.id,
        "EXECUTE",
        expected_revision=0,
        mutation_id="historical-replay-transition",
        updates={"checkpoint": "execute"},
    )
    current = contexts.transition(
        "alpha",
        mission.id,
        "VERIFY",
        expected_revision=1,
        mutation_id="historical-replay-later",
        updates={"checkpoint": "verify"},
    )
    replay = contexts.transition(
        "alpha",
        mission.id,
        "EXECUTE",
        expected_revision=0,
        mutation_id="historical-replay-transition",
        updates={"checkpoint": "execute"},
    )
    assert current.revision == 2 and current.operational_phase == "VERIFY"
    assert replay == original
    assert replay.revision == 1 and replay.operational_phase == "EXECUTE"
    assert contexts.get_context("alpha", mission.id) == current
    assert len(contexts.list_events("alpha", mission.id)) == 3


def test_hot_reader_does_not_call_cold_table_scan(tmp_path, monkeypatch):
    *_prefix, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Bounded read")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="bounded-init",
    )
    monkeypatch.setattr(
        control_plane_v4,
        "_table_rows",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cold table scan reached hot reader")
        ),
    )
    for name in ("_validate_exact", "_validate_semantics", "_schema_contract"):
        monkeypatch.setattr(
            control_plane_v4,
            name,
            lambda *_args, _name=name, **_kwargs: (_ for _ in ()).throw(
                AssertionError(f"cold helper {_name} reached hot reader")
            ),
        )
    statements = []
    original_connect = control_plane_v4._connect

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(control_plane_v4, "_connect", traced_connect)
    assert contexts.get_context("alpha", mission.id).revision == 0
    normalized = "\n".join(statements).upper()
    assert "INTEGRITY_CHECK" not in normalized
    assert "FOREIGN_KEY_CHECK" not in normalized
    assert "TABLE_XINFO" not in normalized


def test_same_count_coherent_bundle_and_head_rewrite_fails_hot_witness(
    tmp_path, monkeypatch
):
    *_prefix, successor, _owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Coherent rewrite")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="coherent-rewrite-init",
    )
    connection = sqlite3.connect(successor.path)
    connection.row_factory = sqlite3.Row
    try:
        for table in (
            "mission_context_revisions",
            "mission_phase_events",
            "mutation_journal",
            "mission_head_history",
        ):
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
                (table,),
            ):
                connection.execute(f'DROP TRIGGER "{name}"')
        revision = connection.execute(
            "SELECT * FROM mission_context_revisions WHERE mission_id=?", (mission.id,)
        ).fetchone()
        payload = json.loads(revision["context_json"])
        payload["checkpoint"] = "forged-but-canonical"
        context_json = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        revision_values = [
            revision["mission_id"],
            revision["revision"],
            revision["workspace_id"],
            revision["schema_version"],
            revision["correlation_id"],
            revision["operational_phase"],
            context_json,
            revision["mission_snapshot_sha256"],
            revision["mission_event_seq"],
            revision["mission_event_sha256"],
            revision["previous_revision_sha256"],
            revision["created_at"],
        ]
        revision_hash = control_plane_v4._digest(
            ["MissionContextRevision.v1", *revision_values]
        )
        event = connection.execute(
            "SELECT * FROM mission_phase_events WHERE mission_id=?", (mission.id,)
        ).fetchone()
        occurred_at = str(event["occurred_at"]) + "+forged"
        event_values = [
            event["mission_id"],
            event["revision"],
            event["workspace_id"],
            event["schema_version"],
            event["event_type"],
            event["from_phase"],
            event["to_phase"],
            event["mission_snapshot_sha256"],
            event["mission_event_seq"],
            event["mission_event_sha256"],
            event["previous_event_sha256"],
            occurred_at,
        ]
        event_hash = control_plane_v4._digest(["MissionPhaseEvent.v1", *event_values])
        event_id = hashlib.sha256(f"{mission.id}\0{event_hash}".encode()).hexdigest()
        connection.execute(
            "UPDATE mission_context_revisions SET context_json=?,revision_sha256=? WHERE mission_id=?",
            (context_json, revision_hash, mission.id),
        )
        connection.execute(
            "UPDATE mission_phase_events SET event_id=?,event_sha256=?,occurred_at=? WHERE mission_id=?",
            (event_id, event_hash, occurred_at, mission.id),
        )
        connection.execute(
            "UPDATE mutation_journal SET result_sha256=? WHERE mission_id=?",
            (revision_hash, mission.id),
        )
        head = connection.execute(
            "SELECT * FROM mission_head_history WHERE mission_id=?", (mission.id,)
        ).fetchone()
        head_values = [
            head["mission_id"],
            head["revision"],
            head["commit_sequence"],
            head["commit_id"],
            revision_hash,
            event_hash,
            head["mutation_id"],
        ]
        connection.execute(
            "UPDATE mission_head_history SET revision_sha256=?,event_sha256=?,head_sha256=? "
            "WHERE mission_id=?",
            (
                revision_hash,
                event_hash,
                control_plane_v4._typed_record_digest("V4MissionHead.v1", head_values),
                mission.id,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ControlPlaneV4IntegrityError):
        contexts.get_context("alpha", mission.id)


def test_forged_self_hashed_mission_head_cannot_select_older_anchored_revision(
    tmp_path, monkeypatch
):
    *_prefix, successor, _owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Head forge")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="head-forge-init",
    )
    connection = sqlite3.connect(successor.path)
    connection.row_factory = sqlite3.Row
    try:
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='mission_head_history'"
        ):
            connection.execute(f'DROP TRIGGER "{name}"')
        row = connection.execute(
            "SELECT * FROM mission_head_history WHERE mission_id=?", (mission.id,)
        ).fetchone()
        forged_values = [
            row["mission_id"],
            row["revision"],
            row["commit_sequence"],
            row["commit_id"],
            "f" * 64,
            row["event_sha256"],
            row["mutation_id"],
        ]
        connection.execute(
            "UPDATE mission_head_history SET revision_sha256=?,head_sha256=? WHERE mission_id=?",
            (
                "f" * 64,
                control_plane_v4._typed_record_digest(
                    "V4MissionHead.v1", forged_values
                ),
                mission.id,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ControlPlaneV4IntegrityError):
        contexts.get_context("alpha", mission.id)


def test_current_head_map_rejects_deleted_latest_physical_head_hot(
    tmp_path, monkeypatch
):
    *_prefix, successor, _owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Deleted current head")
    contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="deleted-current-init",
    )
    _approve(missions, mission.id)
    contexts.transition(
        "alpha",
        mission.id,
        "EXECUTE",
        expected_revision=0,
        mutation_id="deleted-current-transition",
    )
    connection = sqlite3.connect(successor.path)
    try:
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='mission_head_history'"
        ).fetchall():
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute(
            "DELETE FROM mission_head_history WHERE mission_id=? AND revision=1",
            (mission.id,),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ControlPlaneV4IntegrityError):
        contexts.get_context("alpha", mission.id)


@pytest.mark.parametrize("tamper", ("unrelated_insert", "unrelated_delete"))
def test_authenticated_physical_cardinality_blocks_all_hot_paths_and_writer(
    tmp_path, monkeypatch, tamper
):
    source, migrator, source_owner, successor, owner, missions, contexts = _fixture(
        tmp_path, monkeypatch
    )
    mission = _mission(missions, f"Physical cardinality {tamper}")
    original = contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id=f"cardinality-{tamper}-init",
    )
    successor.anchor.verify(successor.anchor_owner)
    key_vault, state_vault = successor._test_vaults
    external_before = (
        bytes(key_vault.value),
        bytes(state_vault.value),
        successor.journal_path.read_bytes(),
    )
    connection = sqlite3.connect(successor.path)
    try:
        if tamper == "unrelated_insert":
            connection.execute(
                "INSERT INTO workspace_provenance VALUES(?,?,?,?,?,?)",
                (
                    "unrelated-rogue",
                    3,
                    "active",
                    "a" * 64,
                    "b" * 64,
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            affected = "workspace_provenance"
        else:
            # Keep the authenticated count trigger active while removing only
            # the immutable-delete guard in this offline corruption fixture.
            connection.execute("DROP TRIGGER deny_workspace_provenance_delete")
            connection.execute(
                "DELETE FROM workspace_provenance WHERE workspace_id='beta'"
            )
            affected = "workspace_provenance"
        connection.commit()
        counter = connection.execute(
            "SELECT row_count FROM authenticated_row_counts WHERE table_name=?",
            (affected,),
        ).fetchone()[0]
        anchored_count = json.loads(
            connection.execute(
                "SELECT counts_json FROM state_commits ORDER BY sequence DESC LIMIT 1"
            ).fetchone()[0]
        )[affected]
        assert counter != anchored_count
    finally:
        connection.close()

    application_connection = control_plane_v4._connect(successor.path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            application_connection.execute(
                "UPDATE authenticated_row_counts SET row_count=row_count "
                "WHERE table_name='workspace_provenance'"
            )
    finally:
        application_connection.close()

    with pytest.raises(ControlPlaneV4IntegrityError):
        contexts.get_context("alpha", mission.id)
    with pytest.raises(ControlPlaneV4IntegrityError):
        contexts.list_events("alpha", mission.id)
    with pytest.raises(ControlPlaneV4IntegrityError):
        successor.read_revision_bundle(owner, "alpha", mission.id, original.revision)
    with pytest.raises(ControlPlaneV4IntegrityError):
        contexts.initialize_context(
            "alpha",
            mission.id,
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id=f"cardinality-{tamper}-init",
        )
    assert (
        bytes(key_vault.value),
        bytes(state_vault.value),
        successor.journal_path.read_bytes(),
    ) == external_before
    with pytest.raises(Exception):
        successor.anchor.verify(successor.anchor_owner)
    with pytest.raises(ControlPlaneV4IntegrityError):
        successor.open(owner)

    restarted, restarted_owner = open_v4(
        migrator,
        source_owner,
        path=successor.path,
        journal_path=successor.journal_path,
        key_vault=key_vault,
        state_vault=state_vault,
        enabled=True,
    )
    with pytest.raises(ControlPlaneV4IntegrityError):
        restarted.open(restarted_owner)


def test_v4_witness_primitives_match_reviewed_v3_fixed_vectors():
    entries = (
        ("a", "[1]", "0" * 64),
        ("b", "[2]", "1" * 64),
        ("c", "[3]", "2" * 64),
    )
    delta = control_plane_v4._operational_delta_digest(entries)
    merkle_root, _leaves, _nodes = control_plane_v4._entry_merkle_tree(entries)
    leaf = control_plane_v4._mmr_leaf("3" * 64, 7, "4" * 64)
    parent = control_plane_v4._mmr_parent(1, leaf, "5" * 64)
    bag = control_plane_v4._mmr_bag([(1, parent), (0, "6" * 64)])
    assert delta == "f7ac414bd2e0dde67c8f84aa90a6b929cfc1f14b60a5198a407c94b795c879b9"
    assert (
        merkle_root
        == "e9f8e96bb3d8410f8fa9ccc1fbfa821ec00ca527ba1a43e409ade5a5ea773221"
    )
    assert leaf == "f78a7b6b306f436ff2870d3c41d6160e1002673d6b2da93f7972f2f2a318bfea"
    assert parent == "2b2de898ee947fda8d6b0e0d87ce1d59f438dab758f824dc8112a5e2e39e0e39"
    assert bag == "879fa2c3bb4648764c7d7343dae7ca631be15307cde00b0a47a1765bc269cdb4"


def test_head_map_matches_independent_fixed_vectors():
    def typed(kind, values):
        encoded = json.dumps(
            [kind, *values], ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(b"ONYX-V3-TYPED-RECORD\0" + encoded).hexdigest()

    empty = [""] * 257
    empty[256] = typed("V4HeadMapEmpty.v1", [256])
    for depth in range(255, -1, -1):
        empty[depth] = typed(
            "V4HeadMapNode.v1", [depth, empty[depth + 1], empty[depth + 1]]
        )

    def leaf(mission_id, revision, sequence, revision_hash, event_hash, mutation_id):
        key_hash = hashlib.sha256(mission_id.encode("utf-8")).hexdigest()
        leaf_hash = typed(
            "V4HeadMapLeaf.v1",
            [
                key_hash,
                mission_id,
                revision,
                sequence,
                revision_hash,
                event_hash,
                mutation_id,
            ],
        )
        return f"{int(key_hash, 16):0256b}", leaf_hash

    def root(items):
        def walk(depth, prefix):
            matches = [
                (bits, value) for bits, value in items if bits.startswith(prefix)
            ]
            if not matches:
                return empty[depth]
            if depth == 256:
                assert len(matches) == 1
                return matches[0][1]
            return typed(
                "V4HeadMapNode.v1",
                [depth, walk(depth + 1, prefix + "0"), walk(depth + 1, prefix + "1")],
            )

        return walk(0, "")

    first = leaf("mission-a", 0, 1, "1" * 64, "2" * 64, "mut-a-0")
    update = leaf("mission-a", 1, 2, "3" * 64, "4" * 64, "mut-a-1")
    second = leaf("mission-b", 0, 3, "5" * 64, "6" * 64, "mut-b-0")
    roots = (empty[0], root([first]), root([update]), root([update, second]))
    assert roots == (
        "00f7ca1d16b8beeed0e24c669c84c64198e2bbb2bc1c88a7677b239e09a0b6ef",
        "e845e6188a9373ed26330f30e85fa40e11e8eb37f1560cb9cc199a3667cf63a3",
        "40a4492644a710b0d587a266b66997e04101f157651c891aeef1a1372b0948c6",
        "bd722134876edf99d59791a27924271c3658a96e69d9bb7aa4f27d4103e70e52",
    )
    assert roots[0] == control_plane_v4._SMT_EMPTY[0]


def test_mmr_edge_child_lookup_uses_authenticated_index(tmp_path, monkeypatch):
    *_prefix, successor, _owner, _missions, _contexts = _fixture(tmp_path, monkeypatch)
    with sqlite3.connect(successor.path) as connection:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT parent_hash,side FROM mmr_edges WHERE child_hash=?",
            ("0" * 64,),
        ).fetchall()
        detail = " ".join(str(row[3]).upper() for row in plan)
    assert "SEARCH" in detail and "SCAN" not in detail
    assert "IDX_V4_MMR_EDGES_CHILD" in detail


def test_invalid_typed_payload_and_transition_fail_before_anchor_prepare(
    tmp_path, monkeypatch
):
    *_prefix, successor, owner, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Pre-prepare validation")
    faults = []
    successor._fault = faults.append
    invalid_payload = V4MissionMutation(
        "initialize",
        "invalid-payload",
        "a" * 64,
        mission.id,
        "alpha",
        "invalid-payload-correlation",
        "WAITING_FOR_APPROVAL",
        "{}",
        "b" * 64,
        1,
        "c" * 64,
        -1,
        "2026-07-16T00:00:00+00:00",
    )
    with pytest.raises(ControlPlaneV4Conflict):
        successor.apply_mission_mutation(owner, invalid_payload)
    assert faults == []
    record = contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="valid-before-invalid-transition",
    )
    faults.clear()
    invalid_transition = V4MissionMutation(
        "transition",
        "invalid-transition",
        "d" * 64,
        mission.id,
        "alpha",
        record.correlation_id,
        "RESEARCH",
        control_plane_v4._canonical(record.spec.as_payload()),
        record.mission_snapshot_sha256,
        record.mission_event_seq,
        record.mission_event_sha256,
        0,
        "2026-07-16T00:00:01+00:00",
    )
    with pytest.raises(ControlPlaneV4Conflict):
        successor.apply_mission_mutation(owner, invalid_transition)
    assert "after_anchor_prepare" not in faults


def test_authority_drift_after_commit_replays_exact_mutation_without_duplicate(
    tmp_path, monkeypatch
):
    *_prefix, missions, contexts = _fixture(tmp_path, monkeypatch)
    mission = _mission(missions, "Authority replay")
    original = missions.authority_snapshot
    calls = 0

    def drifting(mission_id):
        nonlocal calls
        calls += 1
        snapshot = original(mission_id)
        return replace(snapshot, snapshot_hash="f" * 64) if calls == 2 else snapshot

    monkeypatch.setattr(missions, "authority_snapshot", drifting)
    with pytest.raises(MissionAuthorityDrift):
        contexts.initialize_context(
            "alpha",
            mission.id,
            _spec(),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id="authority-replay-init",
        )
    monkeypatch.setattr(missions, "authority_snapshot", original)
    record = contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="authority-replay-init",
    )
    assert record.revision == 0
    assert len(contexts.list_events("alpha", mission.id)) == 1


def test_publish_target_swap_after_validation_is_rejected_before_bootstrap(
    tmp_path, monkeypatch
):
    source_dir = tmp_path / "source-publish-swap"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    WorkspaceRegistry(source, enabled=True).initialize().register(
        "alpha", display_name="Alpha", workspace_class="cyryx"
    )
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "publish-source.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    key_vault, state_vault = _MemoryVault(), _MemoryVault()
    publication = tmp_path / "publish-parent"
    publication.mkdir()
    moved = tmp_path / "publish-parent-moved"
    target = publication / "publish-target.sqlite3"
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=target,
        journal_path=tmp_path / "publish-target.anchor",
        key_vault=key_vault,
        state_vault=state_vault,
        enabled=True,
    )

    observed = {"moved": False, "blocked": False}

    def swap(point):
        if point == "after_v4_publish_before_anchor":
            successor._fault = lambda _point: None
            try:
                os.replace(publication, moved)
                observed["moved"] = True
                publication.mkdir()
            except OSError:
                observed["blocked"] = True
                raise RuntimeError("publication parent swap blocked")

    successor._fault = swap
    with pytest.raises((ControlPlaneV4IntegrityError, RuntimeError)):
        successor.migrate(owner)
    assert observed["moved"] or observed["blocked"]
    assert key_vault.value is None and state_vault.value is None
    assert not (tmp_path / "publish-target.anchor").exists()
    assert not target.exists()
    if moved.exists():
        assert not (moved / target.name).exists()
    assert not list(publication.glob(".onyx-v4-*"))


def _append_synthetic_witness_commits(path, count):
    connection = control_plane_v4._connect(path)
    first_mission = ""
    try:
        connection.execute("BEGIN IMMEDIATE")
        context_json = control_plane_v4._canonical(_spec("query budget").as_payload())
        for index in range(count):
            mission_id = f"budget-mission-{index:04d}"
            mutation_id = f"budget-mutation-{index:04d}"
            if not first_mission:
                first_mission = mission_id
            created_at = f"2026-07-16T00:00:00+00:00#{index:04d}"
            snapshot_hash = hashlib.sha256(
                f"snapshot:{mission_id}".encode()
            ).hexdigest()
            authority_hash = hashlib.sha256(
                f"authority:{mission_id}".encode()
            ).hexdigest()
            revision_values = [
                mission_id,
                0,
                "alpha",
                4,
                f"budget-correlation-{index:04d}",
                "WAITING_FOR_APPROVAL",
                context_json,
                snapshot_hash,
                1,
                authority_hash,
                "",
                created_at,
            ]
            revision_hash = control_plane_v4._digest(
                ["MissionContextRevision.v1", *revision_values]
            )
            connection.execute(
                "INSERT INTO mission_context_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*revision_values[:-1], revision_hash, revision_values[-1]),
            )
            event_values = [
                mission_id,
                0,
                "alpha",
                1,
                "initialized",
                None,
                "WAITING_FOR_APPROVAL",
                snapshot_hash,
                1,
                authority_hash,
                "",
                created_at,
            ]
            event_hash = control_plane_v4._digest(
                ["MissionPhaseEvent.v1", *event_values]
            )
            event_id = hashlib.sha256(
                f"{mission_id}\0{event_hash}".encode()
            ).hexdigest()
            connection.execute(
                "INSERT INTO mission_phase_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, *event_values[:-1], event_hash, event_values[-1]),
            )
            connection.execute(
                "INSERT INTO mutation_journal VALUES(?,?,?,?,?,?,?)",
                (
                    mutation_id,
                    mission_id,
                    0,
                    "initialize",
                    "a" * 64,
                    revision_hash,
                    created_at,
                ),
            )
            control_plane_v4._append_state_commit(
                connection, mutation_id=mutation_id, created_at=created_at
            )
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    return first_mission


def _append_synthetic_event_history(path, count):
    connection = control_plane_v4._connect(path)
    mission_id = "budget-event-history"
    try:
        connection.execute("BEGIN IMMEDIATE")
        context_json = control_plane_v4._canonical(
            _spec("event query budget").as_payload()
        )
        phases = ("EXECUTE", "VERIFY", "CONFIRM", "MONITOR", "ADAPT")
        previous_revision_hash = ""
        previous_event_hash = ""
        previous_phase = None
        for index in range(count):
            phase = (
                "WAITING_FOR_APPROVAL"
                if index == 0
                else phases[(index - 1) % len(phases)]
            )
            mutation_id = f"budget-event-mutation-{index:04d}"
            created_at = f"2026-07-16T01:00:00+00:00#{index:04d}"
            snapshot_hash = hashlib.sha256(
                f"snapshot:{mission_id}:{index}".encode()
            ).hexdigest()
            authority_hash = hashlib.sha256(
                f"authority:{mission_id}:{index}".encode()
            ).hexdigest()
            revision_values = [
                mission_id,
                index,
                "alpha",
                4,
                "budget-event-correlation",
                phase,
                context_json,
                snapshot_hash,
                index + 1,
                authority_hash,
                previous_revision_hash,
                created_at,
            ]
            revision_hash = control_plane_v4._digest(
                ["MissionContextRevision.v1", *revision_values]
            )
            connection.execute(
                "INSERT INTO mission_context_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*revision_values[:-1], revision_hash, revision_values[-1]),
            )
            event_values = [
                mission_id,
                index,
                "alpha",
                1,
                "initialized" if index == 0 else "transitioned",
                previous_phase,
                phase,
                snapshot_hash,
                index + 1,
                authority_hash,
                previous_event_hash,
                created_at,
            ]
            event_hash = control_plane_v4._digest(
                ["MissionPhaseEvent.v1", *event_values]
            )
            event_id = hashlib.sha256(
                f"{mission_id}\0{event_hash}".encode()
            ).hexdigest()
            connection.execute(
                "INSERT INTO mission_phase_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, *event_values[:-1], event_hash, event_values[-1]),
            )
            connection.execute(
                "INSERT INTO mutation_journal VALUES(?,?,?,?,?,?,?)",
                (
                    mutation_id,
                    mission_id,
                    index,
                    "initialize" if index == 0 else "transition",
                    hashlib.sha256(
                        f"request:{mission_id}:{index}".encode()
                    ).hexdigest(),
                    revision_hash,
                    created_at,
                ),
            )
            control_plane_v4._append_state_commit(
                connection, mutation_id=mutation_id, created_at=created_at
            )
            previous_revision_hash = revision_hash
            previous_event_hash = event_hash
            previous_phase = phase
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    return mission_id


@pytest.mark.parametrize("commit_count", (1, 32, 1024))
def test_hot_query_budget_is_logarithmic_after_many_commits(
    tmp_path, monkeypatch, commit_count
):
    root = tmp_path / f"commits-{commit_count}"
    root.mkdir()
    _source, migrator, source_owner, successor, _owner, _missions, _contexts = _fixture(
        root, monkeypatch
    )
    mission_id = _append_synthetic_witness_commits(successor.path, commit_count)
    fresh, fresh_owner = open_v4(
        migrator,
        source_owner,
        path=successor.path,
        journal_path=root / "fresh.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    fresh.anchor.bootstrap(fresh.anchor_owner)
    statements = []
    original_connect = control_plane_v4._connect

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(control_plane_v4, "_connect", traced_connect)
    started = time.perf_counter()
    bundle = fresh.read_context_bundle(fresh_owner, "alpha", mission_id)
    elapsed = time.perf_counter() - started
    assert bundle[0]["mission_id"] == mission_id
    proof_statements = [
        item
        for item in statements
        if item.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    tags = {
        "anchor": "v4:anchor-logical",
        "bundle": "v4:bundle-fetch",
        "smt": "v4:smt-current",
        "merkle_entries": "v4:merkle-entries",
        "merkle_paths": "v4:merkle-paths",
        "commit": "v4:commit-proof",
        "mmr_paths": "v4:mmr-paths",
        "mmr_peaks": "v4:mmr-peaks",
        "physical_counts": "v4:physical-counts",
    }
    breakdown = {
        name: sum(tag in statement for statement in proof_statements)
        for name, tag in tags.items()
    }
    print(
        f"hot-query-budget commits={commit_count} statements={len(proof_statements)} "
        f"additional={len(proof_statements) - breakdown['anchor']} "
        f"elapsed={elapsed:.3f}s breakdown={breakdown}"
    )
    assert breakdown == {
        "anchor": 8,
        "bundle": 7,
        "smt": 1,
        "merkle_entries": 1,
        "merkle_paths": 1,
        "commit": 2,
        "mmr_paths": 1,
        "mmr_peaks": 1,
        "physical_counts": 2,
    }
    assert len(proof_statements) == sum(breakdown.values())
    assert len(proof_statements) - breakdown["anchor"] <= 20
    assert elapsed < 30
    assert not any("INTEGRITY_CHECK" in item.upper() for item in statements)


def test_real_writer_query_and_time_budget_is_history_independent(
    tmp_path, monkeypatch
):
    raw_connect = control_plane_v4._connect
    measurements = []
    for commit_count in (1, 64, 1024):
        root = tmp_path / f"writer-{commit_count}"
        root.mkdir()
        (_source, migrator, source_owner, successor, _owner, missions, _contexts) = (
            _fixture(root, monkeypatch)
        )
        _append_synthetic_witness_commits(successor.path, commit_count)
        fresh, fresh_owner = open_v4(
            migrator,
            source_owner,
            path=successor.path,
            journal_path=root / "fresh.anchor",
            key_vault=_MemoryVault(),
            state_vault=_MemoryVault(),
            enabled=True,
        )
        fresh.anchor.bootstrap(fresh.anchor_owner)
        contexts = MissionContextStore(fresh, fresh_owner, missions, enabled=True)
        mission = _mission(missions, f"Writer budget {commit_count}")
        statements = []
        reads = []

        def traced_connect(*args, **kwargs):
            connection = raw_connect(*args, **kwargs)
            connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
            connection.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 1000)

            def authorizer(action, first, second, _database, _trigger):
                if action == sqlite3.SQLITE_READ:
                    reads.append((first, second))
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorizer)
            connection.set_trace_callback(statements.append)
            return connection

        monkeypatch.setattr(control_plane_v4, "_connect", traced_connect)
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        record = contexts.initialize_context(
            "alpha",
            mission.id,
            _spec(f"writer budget {commit_count}"),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id=f"writer-budget-{commit_count}",
        )
        cpu_elapsed = time.process_time() - cpu_started
        wall_elapsed = time.perf_counter() - wall_started
        monkeypatch.setattr(control_plane_v4, "_connect", raw_connect)
        assert record.revision == 0
        selects = [
            item
            for item in statements
            if item.lstrip().upper().startswith(("SELECT", "WITH"))
        ]
        tags = {
            "anchor": "v4:anchor-logical",
            "writer": "v4:writer-hot",
            "bundle": "v4:bundle-fetch",
            "smt": "v4:smt-current",
            "merkle_entries": "v4:merkle-entries",
            "merkle_paths": "v4:merkle-paths",
            "commit": "v4:commit-proof",
            "mmr_paths": "v4:mmr-paths",
            "mmr_peaks": "v4:mmr-peaks",
        }
        breakdown = {
            name: sum(tag in statement for statement in selects)
            for name, tag in tags.items()
        }
        history_tables = (
            "mission_context_revisions",
            "mission_phase_events",
            "mutation_journal",
            "mission_head_history",
        )
        history_reads = {
            table: sum(
                f"FROM {table}" in statement or f"JOIN {table}" in statement
                for statement in selects
            )
            for table in history_tables
        }
        unbounded = [
            item
            for item in selects
            if " FROM " in item.upper()
            and " WHERE " not in item.upper()
            and " LIMIT " not in item.upper()
        ]
        print(
            f"writer-budget commits={commit_count} selects={len(selects)} "
            f"reads={len(reads)} cpu={cpu_elapsed:.3f}s wall={wall_elapsed:.3f}s "
            f"breakdown={breakdown} history_reads={history_reads} "
            f"unbounded={unbounded}"
        )
        normalized = "\n".join(statements).upper()
        assert "INTEGRITY_CHECK" not in normalized
        assert "QUICK_CHECK" not in normalized
        count_statements = [item for item in selects if "COUNT(" in item.upper()]
        assert all(" WHERE " in item.upper() for item in count_statements)
        assert all(item.upper().count(" OR ") <= 15 for item in selects)
        assert selects and reads
        assert len(selects) <= 128
        assert cpu_elapsed < 30
        assert wall_elapsed < 30
        measurements.append((len(selects), breakdown, history_reads, unbounded))
    assert len({count for count, *_rest in measurements}) == 1
    assert (
        len(
            {
                tuple(sorted(breakdown.items()))
                for _count, breakdown, *_rest in measurements
            }
        )
        == 1
    )
    assert (
        len(
            {
                tuple(sorted(history.items()))
                for _count, _breakdown, history, _rest in measurements
            }
        )
        == 1
    )
    assert not any(
        unbounded for _count, _breakdown, _history, unbounded in measurements
    )


def test_real_writer_remains_bounded_across_sequential_public_mutations(
    tmp_path, monkeypatch
):
    root = tmp_path / "sequential-writer"
    root.mkdir()
    *_prefix, successor, owner, missions, contexts = _fixture(root, monkeypatch)
    raw_connect = control_plane_v4._connect
    query_counts = []
    for index in range(32):
        mission = _mission(missions, f"Sequential writer {index}")
        statements = []

        def traced_connect(*args, **kwargs):
            connection = raw_connect(*args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection

        monkeypatch.setattr(control_plane_v4, "_connect", traced_connect)
        record = contexts.initialize_context(
            "alpha",
            mission.id,
            _spec(f"sequential writer {index}"),
            operational_phase="WAITING_FOR_APPROVAL",
            mutation_id=f"sequential-writer-{index:02d}",
        )
        monkeypatch.setattr(control_plane_v4, "_connect", raw_connect)
        assert record.revision == 0
        selects = [
            item
            for item in statements
            if item.lstrip().upper().startswith(("SELECT", "WITH"))
        ]
        assert "INTEGRITY_CHECK" not in "\n".join(statements).upper()
        query_counts.append(len(selects))
    assert len(set(query_counts)) == 1
    print(
        f"sequential-writer mutations={len(query_counts)} "
        f"selects_per_mutation={query_counts[0]}"
    )
    successor.verify_integrity(owner)


@pytest.mark.parametrize("event_count", (1, 64))
def test_list_events_query_budget_scales_with_returned_history_only(
    tmp_path, monkeypatch, event_count
):
    root = tmp_path / f"events-{event_count}"
    root.mkdir()
    _source, migrator, source_owner, successor, _owner, _missions, _contexts = _fixture(
        root, monkeypatch
    )
    mission_id = _append_synthetic_event_history(successor.path, event_count)
    fresh, fresh_owner = open_v4(
        migrator,
        source_owner,
        path=successor.path,
        journal_path=root / "fresh.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    fresh.anchor.bootstrap(fresh.anchor_owner)
    statements = []
    original_connect = control_plane_v4._connect

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(control_plane_v4, "_connect", traced_connect)
    started = time.perf_counter()
    events = fresh.read_mission_events(fresh_owner, "alpha", mission_id)
    elapsed = time.perf_counter() - started
    assert len(events) == event_count
    assert [int(event["revision"]) for event in events] == list(range(event_count))
    proof_statements = [
        item
        for item in statements
        if item.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    tags = {
        "anchor": "v4:anchor-logical",
        "bundle": "v4:bundle-fetch",
        "smt": "v4:smt-current",
        "merkle_entries": "v4:merkle-entries",
        "merkle_paths": "v4:merkle-paths",
        "commit": "v4:commit-proof",
        "mmr_paths": "v4:mmr-paths",
        "mmr_peaks": "v4:mmr-peaks",
        "history_ranges": "v4:history-range",
        "history_entry_ranges": "v4:history-entry-range",
        "history_tail": "v4:history-tail",
        "physical_counts": "v4:physical-counts",
    }
    breakdown = {
        name: sum(tag in statement for statement in proof_statements)
        for name, tag in tags.items()
    }
    print(
        f"list-events-budget events={event_count} statements={len(proof_statements)} "
        f"additional={len(proof_statements) - breakdown['anchor']} "
        f"elapsed={elapsed:.3f}s breakdown={breakdown}"
    )
    assert breakdown == {
        "anchor": 8,
        "bundle": 9,
        "smt": 1,
        "merkle_entries": 1,
        "merkle_paths": 2,
        "commit": 4,
        "mmr_paths": 2,
        "mmr_peaks": 2,
        "history_ranges": 4,
        "history_entry_ranges": 1,
        "history_tail": 4,
        "physical_counts": 2,
    }
    assert len(proof_statements) == sum(breakdown.values())
    assert len(proof_statements) - breakdown["anchor"] <= 32
    event_fetches = [
        statement
        for statement in proof_statements
        if "FROM mission_phase_events" in statement
    ]
    assert len(event_fetches) == 3
    assert all("WHERE mission_id=" in statement for statement in event_fetches)
    assert not any("INTEGRITY_CHECK" in item.upper() for item in statements)
    assert elapsed < 30


def test_list_events_over_one_thousand_uses_fixed_authenticated_batches(
    tmp_path, monkeypatch
):
    root = tmp_path / "events-1025"
    root.mkdir()
    _source, migrator, source_owner, successor, _owner, _missions, _contexts = _fixture(
        root, monkeypatch
    )
    mission_id = _append_synthetic_event_history(successor.path, 1025)
    fresh, fresh_owner = open_v4(
        migrator,
        source_owner,
        path=successor.path,
        journal_path=root / "fresh.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    fresh.anchor.bootstrap(fresh.anchor_owner)
    statements = []
    original_connect = control_plane_v4._connect

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
        connection.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 1000)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(control_plane_v4, "_connect", traced_connect)
    started = time.perf_counter()
    events = fresh.read_mission_events(fresh_owner, "alpha", mission_id)
    elapsed = time.perf_counter() - started
    assert len(events) == 1025
    assert [int(event["revision"]) for event in events] == list(range(1025))
    history_ranges = [item for item in statements if "v4:history-range" in item]
    entry_ranges = [item for item in statements if "v4:history-entry-range" in item]
    assert len(history_ranges) == 4 * 9
    assert len(entry_ranges) == 9
    assert all(" BETWEEN " in item.upper() for item in (*history_ranges, *entry_ranges))
    assert not any(" OR " in item.upper() for item in (*history_ranges, *entry_ranges))
    assert elapsed < 120


@pytest.mark.parametrize(
    "table",
    (
        "mission_context_revisions",
        "mission_phase_events",
        "mutation_journal",
        "mission_head_history",
    ),
)
def test_list_events_rejects_intermediate_authenticated_history_deletion(
    tmp_path, monkeypatch, table
):
    root = tmp_path / table
    root.mkdir()
    _source, migrator, source_owner, successor, _owner, _missions, _contexts = _fixture(
        root, monkeypatch
    )
    mission_id = _append_synthetic_event_history(successor.path, 130)
    fresh, fresh_owner = open_v4(
        migrator,
        source_owner,
        path=successor.path,
        journal_path=root / "fresh.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    fresh.anchor.bootstrap(fresh.anchor_owner)
    tamper = sqlite3.connect(successor.path)
    try:
        tamper.execute("PRAGMA foreign_keys=OFF")
        tamper.execute(f"DROP TRIGGER deny_{table}_delete")
        tamper.execute(
            f"DELETE FROM {table} WHERE mission_id=? AND revision=?",
            (mission_id, 64),
        )
        tamper.commit()
    finally:
        tamper.close()
    with pytest.raises(ControlPlaneV4IntegrityError):
        fresh.read_mission_events(fresh_owner, "alpha", mission_id)


def test_trusted_directory_native_temp_blocks_swap_and_publishes_same_identity(
    tmp_path,
):
    parent = tmp_path / "trusted"
    parent.mkdir()
    capability = control_plane_v4._TrustedDirectory(parent)
    name, descriptor = capability.create_temp(
        prefix=".native-", suffix=".sqlite3", native_only=True
    )
    original = capability.descriptor_identity(descriptor)
    capability.write_all(descriptor, b"authenticated-bytes")
    attacker = parent / "attacker.sqlite3"
    attacker.write_bytes(b"attacker")
    if os.name == "nt":
        with pytest.raises(OSError):
            os.replace(attacker, parent / name)
    else:
        os.replace(attacker, parent / name)
        with pytest.raises(ControlPlaneV4IntegrityError):
            capability.publish(
                name,
                "published.sqlite3",
                descriptor=descriptor,
                expected_identity=original,
            )
        capability.close_temp(descriptor)
        capability.close()
        assert not (parent / "published.sqlite3").exists()
        return
    capability.publish(
        name,
        "published.sqlite3",
        descriptor=descriptor,
        expected_identity=original,
    )
    assert capability.descriptor_identity(descriptor) == original
    capability.close_temp(descriptor)
    assert capability.file_identity("published.sqlite3") == original
    capability.close()
    assert (parent / "published.sqlite3").read_bytes() == b"authenticated-bytes"
    assert attacker.read_bytes() == b"attacker"


def test_trusted_directory_post_create_failure_removes_empty_temp(
    tmp_path, monkeypatch
):
    parent = tmp_path / "post-create-cleanup"
    parent.mkdir()
    capability = control_plane_v4._TrustedDirectory(parent)
    original = capability._assert_pinned
    calls = 0

    def fail_after_create():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ControlPlaneV4IntegrityError("post-create seam")
        return original()

    monkeypatch.setattr(capability, "_assert_pinned", fail_after_create)
    with pytest.raises(ControlPlaneV4IntegrityError, match="post-create seam"):
        capability.create_temp(prefix=".cleanup-", suffix=".tmp", native_only=True)
    monkeypatch.setattr(capability, "_assert_pinned", original)
    assert not list(parent.glob(".cleanup-*"))
    name, descriptor = capability.create_temp(
        prefix=".usable-", suffix=".tmp", native_only=True
    )
    capability.discard_temp(descriptor, name)
    capability.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows CRT handle conversion")
def test_windows_temp_crt_conversion_failure_closes_handle_and_unlinks(
    tmp_path, monkeypatch
):
    import msvcrt

    parent = tmp_path / "crt-cleanup"
    parent.mkdir()
    capability = control_plane_v4._TrustedDirectory(parent)
    monkeypatch.setattr(
        msvcrt,
        "open_osfhandle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("crt seam")),
    )
    with pytest.raises(OSError, match="crt seam"):
        capability.create_temp(prefix=".crt-", suffix=".tmp", native_only=True)
    assert not list(parent.glob(".crt-*"))
    capability.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows final-path handle proof")
def test_windows_final_directory_redirection_simulation_fails_before_bytes(
    tmp_path, monkeypatch
):
    parent = tmp_path / "redirect" / "nested"
    original = control_plane_v4._TrustedDirectory._win_exact_final_path
    calls = 0

    def redirected(handle, expected):
        nonlocal calls
        calls += 1
        return False if calls >= 2 else original(handle, expected)

    monkeypatch.setattr(
        control_plane_v4._TrustedDirectory,
        "_win_exact_final_path",
        staticmethod(redirected),
    )
    with pytest.raises(ControlPlaneV4IntegrityError, match="resolved elsewhere"):
        control_plane_v4._TrustedDirectory(parent)
    assert not list(tmp_path.rglob("*.sqlite3"))


@pytest.mark.skipif(os.name != "nt", reason="Windows per-user temp traversal")
def test_windows_normal_user_temp_and_missing_nested_parent_are_handle_relative(
    tmp_path, monkeypatch
):
    temporary = tempfile.TemporaryDirectory(prefix="onyx-v4-native-")
    normal_temp = Path(temporary.name)
    assert normal_temp.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    target = normal_temp / "absent" / "nested" / "publication" / "v4.sqlite3"
    assert not target.parent.exists()
    successor, owner, key, state = _unmigrated_successor(
        normal_temp, monkeypatch, target
    )
    status = successor.migrate(owner)
    assert status.schema_version == 4
    assert target.is_file()
    assert key.value is not None and state.value is not None
    assert not list(target.parent.glob(".onyx-v4-*"))
    temporary.cleanup()


def test_v4_migrated_size_cap_fails_before_serialize_temp_publish_or_anchor(
    tmp_path, monkeypatch
):
    source_dir = tmp_path / "v3-expanded-source"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    WorkspaceRegistry(source, enabled=True).initialize().register(
        "alpha", display_name="Alpha", workspace_class="cyryx"
    )
    created = "2026-07-17T00:00:00+00:00"
    source._require_connection().executemany(
        "INSERT INTO mission_contexts VALUES(?,?,?,?,?,?,?)",
        (
            (
                f"cap-mission-{index:05d}",
                "alpha",
                2,
                "PENDING_REVIEW",
                json.dumps({"objective": f"cap-{index:05d}"}, separators=(",", ":")),
                created,
                created,
            )
            for index in range(2048)
        ),
    )
    source._require_connection().commit()
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "v3-expanded.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    compact = sqlite3.connect(migrator.port.path)
    try:
        compact.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        compact.execute("VACUUM")
    finally:
        compact.close()
    source_measure = sqlite3.connect(migrator.port.path)
    try:
        source_pages = int(source_measure.execute("PRAGMA page_count").fetchone()[0])
        source_page_size = int(source_measure.execute("PRAGMA page_size").fetchone()[0])
    finally:
        source_measure.close()
    source_bound = max(
        migrator.port.path.stat().st_size,
        source_pages * source_page_size,
    )
    probe, probe_owner = open_v4(
        migrator,
        source_owner,
        path=tmp_path / "v4-cap-probe.sqlite3",
        journal_path=tmp_path / "v4-cap-probe.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    probe.migrate(probe_owner)
    probe_measure = sqlite3.connect(probe.path)
    try:
        v4_bytes = int(probe_measure.execute("PRAGMA page_count").fetchone()[0]) * int(
            probe_measure.execute("PRAGMA page_size").fetchone()[0]
        )
    finally:
        probe_measure.close()
    assert source_bound < v4_bytes
    cap = source_bound + (v4_bytes - source_bound) // 2
    monkeypatch.setattr(control_plane_v4, "_MAX_V3_CAPTURE_BYTES", cap)
    target = tmp_path / "v4-expanded-cap.sqlite3"
    key, state = _MemoryVault(), _MemoryVault()
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=target,
        journal_path=tmp_path / "candidate-v4.anchor",
        key_vault=key,
        state_vault=state,
        enabled=True,
    )
    observed = []
    successor._fault = observed.append
    with pytest.raises(ControlPlaneV4IOError, match="v4 migration publication"):
        successor.migrate(owner)
    assert "before_v4_serialize" not in observed
    assert "before_v4_publication_temp" not in observed
    assert "before_v4_publish" not in observed
    assert key.value is None and state.value is None
    assert not target.exists()
    assert not (tmp_path / "candidate-v4.anchor").exists()
    assert not list(tmp_path.glob(".onyx-v4-*"))


def test_trusted_directory_parent_swap_and_preexisting_target_fail_closed(tmp_path):
    parent = tmp_path / "trusted-parent"
    parent.mkdir()
    moved = tmp_path / "trusted-moved"
    capability = control_plane_v4._TrustedDirectory(parent)
    name, descriptor = capability.create_temp(
        prefix=".parent-", suffix=".sqlite3", native_only=True
    )
    identity = capability.descriptor_identity(descriptor)
    capability.write_all(descriptor, b"source")
    if os.name == "nt":
        with pytest.raises(OSError):
            os.replace(parent, moved)
        (parent / "published.sqlite3").write_bytes(b"preexisting")
        with pytest.raises(ControlPlaneV4IntegrityError):
            capability.publish(
                name,
                "published.sqlite3",
                descriptor=descriptor,
                expected_identity=identity,
            )
        capability.discard_temp(descriptor, name)
        capability.close()
        assert (parent / "published.sqlite3").read_bytes() == b"preexisting"
        assert not moved.exists()
    else:
        os.replace(parent, moved)
        parent.mkdir()
        with pytest.raises(ControlPlaneV4IntegrityError):
            capability.publish(
                name,
                "published.sqlite3",
                descriptor=descriptor,
                expected_identity=identity,
            )
        capability.discard_temp(descriptor, name)
        capability.close()
        assert not (moved / "published.sqlite3").exists()
        assert not (parent / "published.sqlite3").exists()


def test_posix_parent_swap_branch_contract_is_fail_closed():
    if os.name != "nt":
        pytest.skip("POSIX branch is executed by the behavioral test above")
    source = inspect.getsource(
        test_trusted_directory_parent_swap_and_preexisting_target_fail_closed
    )
    posix_branch = source.split("else:", 1)[1]
    assert "with pytest.raises(ControlPlaneV4IntegrityError)" in posix_branch
    assert 'assert not (moved / "published.sqlite3").exists()' in posix_branch


def test_v3_capture_limit_fails_before_temp_publication_or_anchor(
    tmp_path, monkeypatch
):
    source_dir = tmp_path / "v3-cap"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    WorkspaceRegistry(source, enabled=True).initialize().register(
        "alpha", display_name="Alpha", workspace_class="cyryx"
    )
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "v3-cap.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    key, state = _MemoryVault(), _MemoryVault()
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=tmp_path / "v4-cap.sqlite3",
        journal_path=tmp_path / "v4-cap.anchor",
        key_vault=key,
        state_vault=state,
        enabled=True,
    )
    monkeypatch.setattr(control_plane_v4, "_MAX_V3_CAPTURE_BYTES", 1)
    with pytest.raises(ControlPlaneV4IOError):
        successor.migrate(owner)
    assert key.value is None and state.value is None
    assert not successor.path.exists()
    assert not (tmp_path / "v4-cap.anchor").exists()
    assert not list(tmp_path.glob(".onyx-v3-capture-*"))
    assert not list(tmp_path.glob(".onyx-v4-*"))


@pytest.mark.parametrize("fault_point", ("before_v3_capture_temp", "before_v4_publish"))
def test_publication_parent_swap_fault_seams_leave_no_bytes_or_anchor(
    tmp_path, monkeypatch, fault_point
):
    publication = tmp_path / "publication"
    publication.mkdir()
    moved = tmp_path / "publication-moved"
    successor, owner, key, state = _unmigrated_successor(
        tmp_path, monkeypatch, publication / "v4.sqlite3"
    )
    observed = {"blocked": False, "moved": False}

    def fault(point):
        if point != fault_point:
            return
        try:
            os.replace(publication, moved)
            observed["moved"] = True
            publication.mkdir()
        except OSError:
            observed["blocked"] = True
        raise RuntimeError(f"fault:{point}")

    successor._fault = fault
    with pytest.raises(RuntimeError, match=fault_point):
        successor.migrate(owner)
    assert observed["blocked"] or observed["moved"]
    assert key.value is None and state.value is None
    assert not (tmp_path / "candidate-v4.anchor").exists()
    assert not successor.path.exists()
    for directory in (publication, moved):
        if directory.exists():
            assert not list(directory.glob(".onyx-v3-capture-*"))
            assert not list(directory.glob(".onyx-v4-*"))
            assert not (directory / "v4.sqlite3").exists()


def test_parent_swap_inside_main_bootstrap_rolls_back_publication_and_anchor(
    tmp_path, monkeypatch
):
    publication = tmp_path / "bootstrap-main"
    publication.mkdir()
    moved = tmp_path / "bootstrap-main-moved"
    successor, owner, key, state = _unmigrated_successor(
        tmp_path, monkeypatch, publication / "v4.sqlite3"
    )
    swapped = False
    swap_failure = None
    original_parent_identity = (
        os.stat(publication).st_dev,
        os.stat(publication).st_ino,
    )

    def fault(point):
        nonlocal swapped, swap_failure
        if point != "after_bootstrap_pending":
            return
        try:
            os.replace(publication, moved)
            publication.mkdir()
            swapped = True
        except OSError as exc:
            swap_failure = exc
        raise RuntimeError("inside bootstrap")

    successor.anchor._fault = fault
    with pytest.raises(RuntimeError, match="inside bootstrap"):
        successor.migrate(owner)
    assert key.value is None and state.value is None
    assert not (tmp_path / "candidate-v4.anchor").exists()
    for directory in (publication, moved):
        if directory.exists():
            assert not (directory / "v4.sqlite3").exists()
            assert not list(directory.glob(".onyx-v4-*"))
    if not swapped:
        assert os.name == "nt" and isinstance(swap_failure, OSError)
        assert getattr(swap_failure, "winerror", None) in {5, 32}
        assert (
            os.stat(publication).st_dev,
            os.stat(publication).st_ino,
        ) == original_parent_identity


def test_parent_swap_inside_adoption_bootstrap_preserves_candidate_but_rolls_back_anchor(
    tmp_path, monkeypatch
):
    publication = tmp_path / "bootstrap-adopt"
    publication.mkdir()
    moved = tmp_path / "bootstrap-adopt-moved"
    target = publication / "v4.sqlite3"
    successor, owner, key, state = _unmigrated_successor(tmp_path, monkeypatch, target)
    successor.migrate(owner)
    original = target.read_bytes()
    key.delete()
    state.delete()
    successor.journal_path.unlink()
    adopter, adopter_owner = open_v4(
        successor.source,
        successor.source_owner,
        path=target,
        journal_path=successor.journal_path,
        key_vault=key,
        state_vault=state,
        enabled=True,
    )
    swapped = False
    swap_failure = None
    original_parent_identity = (
        os.stat(publication).st_dev,
        os.stat(publication).st_ino,
    )

    def fault(point):
        nonlocal swapped, swap_failure
        if point != "after_bootstrap_pending":
            return
        try:
            os.replace(publication, moved)
            publication.mkdir()
            swapped = True
        except OSError as exc:
            swap_failure = exc
        raise RuntimeError("inside adoption bootstrap")

    adopter.anchor._fault = fault
    with pytest.raises(RuntimeError, match="inside adoption bootstrap"):
        adopter.migrate(adopter_owner)
    assert key.value is None and state.value is None
    assert not adopter.journal_path.exists()
    preserved = (moved if swapped else publication) / "v4.sqlite3"
    assert preserved.read_bytes() == original
    assert not list(publication.glob(".onyx-v4-*"))
    if not swapped:
        assert os.name == "nt" and isinstance(swap_failure, OSError)
        assert getattr(swap_failure, "winerror", None) in {5, 32}
        assert (
            os.stat(publication).st_dev,
            os.stat(publication).st_ino,
        ) == original_parent_identity


def test_separate_journal_parent_swap_main_bootstrap_uses_original_capability(
    tmp_path, monkeypatch
):
    target = tmp_path / "separate-main" / "v4.sqlite3"
    seed, _seed_owner, _seed_key, _seed_state = _unmigrated_successor(
        tmp_path, monkeypatch, target
    )
    journal_parent = tmp_path / "journal-main"
    journal_parent.mkdir()
    moved = tmp_path / "journal-main-moved"
    key, state = _MemoryVault(), _MemoryVault()
    successor, owner = open_v4(
        seed.source,
        seed.source_owner,
        path=target,
        journal_path=journal_parent / "v4.anchor",
        key_vault=key,
        state_vault=state,
        enabled=True,
    )
    observed = {"attempted": False, "swapped": False, "failure": None}
    replacement = journal_parent / "v4.anchor"

    def fault(point):
        if point != "after_capability_journal_create_before_binding":
            return
        observed["attempted"] = True
        assert replacement.is_file()
        try:
            os.replace(journal_parent, moved)
            journal_parent.mkdir()
            replacement.write_bytes(b"replacement-journal")
            observed["swapped"] = True
        except OSError as exc:
            observed["failure"] = exc
        raise RuntimeError("separate main journal swap")

    successor.anchor._fault = fault
    with pytest.raises(RuntimeError, match="separate main journal swap"):
        successor.migrate(owner)
    assert observed["attempted"]
    assert key.value is None and state.value is None
    assert not target.exists()
    if observed["swapped"]:
        assert not (moved / "v4.anchor").exists()
        assert replacement.read_bytes() == b"replacement-journal"
        released = tmp_path / "journal-main-released"
        os.replace(moved, released)
        (released / "v4.anchor.lock").unlink(missing_ok=True)
        released.rmdir()
    else:
        assert os.name == "nt"
        assert isinstance(observed["failure"], OSError)
        assert getattr(observed["failure"], "winerror", None) in {5, 32}
        assert not replacement.exists()


def test_separate_journal_parent_swap_adoption_uses_original_capability(
    tmp_path, monkeypatch
):
    target = tmp_path / "separate-adopt" / "v4.sqlite3"
    creator, creator_owner, creator_key, creator_state = _unmigrated_successor(
        tmp_path, monkeypatch, target
    )
    creator.migrate(creator_owner)
    original = target.read_bytes()
    creator_key.delete()
    creator_state.delete()
    creator.journal_path.unlink()

    journal_parent = tmp_path / "journal-adopt"
    journal_parent.mkdir()
    moved = tmp_path / "journal-adopt-moved"
    key, state = _MemoryVault(), _MemoryVault()
    adopter, owner = open_v4(
        creator.source,
        creator.source_owner,
        path=target,
        journal_path=journal_parent / "v4.anchor",
        key_vault=key,
        state_vault=state,
        enabled=True,
    )
    observed = {"attempted": False, "swapped": False, "failure": None}
    replacement = journal_parent / "v4.anchor"

    def fault(point):
        if point != "after_capability_journal_create_before_binding":
            return
        observed["attempted"] = True
        assert replacement.is_file()
        try:
            os.replace(journal_parent, moved)
            journal_parent.mkdir()
            replacement.write_bytes(b"replacement-adoption-journal")
            observed["swapped"] = True
        except OSError as exc:
            observed["failure"] = exc
        raise RuntimeError("separate adoption journal swap")

    adopter.anchor._fault = fault
    with pytest.raises(RuntimeError, match="separate adoption journal swap"):
        adopter.migrate(owner)
    assert observed["attempted"]
    assert key.value is None and state.value is None
    assert target.read_bytes() == original
    if observed["swapped"]:
        assert not (moved / "v4.anchor").exists()
        assert replacement.read_bytes() == b"replacement-adoption-journal"
        released = tmp_path / "journal-adopt-released"
        os.replace(moved, released)
        (released / "v4.anchor.lock").unlink(missing_ok=True)
        released.rmdir()
    else:
        assert os.name == "nt"
        assert isinstance(observed["failure"], OSError)
        assert getattr(observed["failure"], "winerror", None) in {5, 32}
        assert not replacement.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX rename contract")
def test_posix_prebootstrap_journal_parent_replacement_fails_before_create_main(
    tmp_path, monkeypatch
):
    target = tmp_path / "prebootstrap-main" / "v4.sqlite3"
    seed, _seed_owner, _seed_key, _seed_state = _unmigrated_successor(
        tmp_path, monkeypatch, target
    )
    journal_parent = tmp_path / "prebootstrap-main-journal"
    journal_parent.mkdir()
    moved = tmp_path / "prebootstrap-main-journal-moved"
    key, state = _MemoryVault(), _MemoryVault()
    successor, owner = open_v4(
        seed.source,
        seed.source_owner,
        path=target,
        journal_path=journal_parent / "v4.anchor",
        key_vault=key,
        state_vault=state,
        enabled=True,
    )

    def fault(point):
        if point == "after_v4_publish_before_anchor":
            os.replace(journal_parent, moved)
            journal_parent.mkdir()

    successor._fault = fault
    with pytest.raises(ControlPlaneV4IntegrityError, match="binding changed"):
        successor.migrate(owner)
    assert key.value is None and state.value is None
    assert not target.exists()
    assert not (journal_parent / "v4.anchor").exists()
    assert not (moved / "v4.anchor").exists()
    assert not list(target.parent.glob(".onyx-v4-*"))
    os.replace(moved, tmp_path / "prebootstrap-main-journal-released")


@pytest.mark.skipif(os.name == "nt", reason="POSIX rename contract")
def test_posix_prebootstrap_journal_parent_replacement_fails_before_create_adoption(
    tmp_path, monkeypatch
):
    target = tmp_path / "prebootstrap-adopt" / "v4.sqlite3"
    creator, creator_owner, creator_key, creator_state = _unmigrated_successor(
        tmp_path, monkeypatch, target
    )
    creator.migrate(creator_owner)
    original = target.read_bytes()
    creator_key.delete()
    creator_state.delete()
    creator.journal_path.unlink()
    journal_parent = tmp_path / "prebootstrap-adopt-journal"
    journal_parent.mkdir()
    moved = tmp_path / "prebootstrap-adopt-journal-moved"
    key, state = _MemoryVault(), _MemoryVault()
    adopter, owner = open_v4(
        creator.source,
        creator.source_owner,
        path=target,
        journal_path=journal_parent / "v4.anchor",
        key_vault=key,
        state_vault=state,
        enabled=True,
    )

    def fault(point):
        if point == "after_v4_adoption_validate_before_anchor":
            os.replace(journal_parent, moved)
            journal_parent.mkdir()

    adopter._fault = fault
    with pytest.raises(ControlPlaneV4IntegrityError, match="binding changed"):
        adopter.migrate(owner)
    assert target.read_bytes() == original
    assert key.value is None and state.value is None
    assert not (journal_parent / "v4.anchor").exists()
    assert not (moved / "v4.anchor").exists()
    os.replace(moved, tmp_path / "prebootstrap-adopt-journal-released")


@pytest.mark.skipif(os.name != "nt", reason="Windows native parent binding")
@pytest.mark.parametrize("adoption", [False, True])
def test_windows_prebootstrap_journal_parent_rename_is_natively_blocked(
    tmp_path, monkeypatch, adoption
):
    target = tmp_path / ("win-pre-adopt" if adoption else "win-pre-main") / "v4.sqlite3"
    creator, creator_owner, creator_key, creator_state = _unmigrated_successor(
        tmp_path, monkeypatch, target
    )
    if adoption:
        creator.migrate(creator_owner)
        original = target.read_bytes()
        creator_key.delete()
        creator_state.delete()
        creator.journal_path.unlink()
    else:
        original = None
    journal_parent = tmp_path / (
        "win-journal-adopt" if adoption else "win-journal-main"
    )
    journal_parent.mkdir()
    moved = journal_parent.with_name(journal_parent.name + "-moved")
    key, state = _MemoryVault(), _MemoryVault()
    successor, owner = open_v4(
        creator.source,
        creator.source_owner,
        path=target,
        journal_path=journal_parent / "v4.anchor",
        key_vault=key,
        state_vault=state,
        enabled=True,
    )
    observed = {"attempted": False, "failure": None}
    seam = (
        "after_v4_adoption_validate_before_anchor"
        if adoption
        else "after_v4_publish_before_anchor"
    )

    def fault(point):
        if point != seam:
            return
        observed["attempted"] = True
        try:
            os.replace(journal_parent, moved)
        except OSError as exc:
            observed["failure"] = exc
            raise RuntimeError("Windows prebootstrap rename blocked") from exc

    successor._fault = fault
    with pytest.raises(RuntimeError, match="prebootstrap rename blocked"):
        successor.migrate(owner)
    assert observed["attempted"] and isinstance(observed["failure"], OSError)
    assert getattr(observed["failure"], "winerror", None) in {5, 32}
    assert key.value is None and state.value is None
    assert not (journal_parent / "v4.anchor").exists()
    if adoption:
        assert target.read_bytes() == original
    else:
        assert not target.exists()
    # The outer journal capability must be closed even when the primary seam
    # aborts, so the parent can be renamed immediately after return.
    os.replace(journal_parent, moved)
    assert moved.is_dir()


def test_migration_cleanup_failure_still_closes_capability_and_removes_temp(
    tmp_path, monkeypatch
):
    successor, owner, key, state = _unmigrated_successor(
        tmp_path, monkeypatch, tmp_path / "cleanup-v4.sqlite3"
    )
    original_discard = control_plane_v4._TrustedDirectory.discard_temp

    def discard_then_fail(self, descriptor, name):
        original_discard(self, descriptor, name)
        if name.startswith(".onyx-v4-"):
            raise OSError("discard cleanup seam")

    monkeypatch.setattr(
        control_plane_v4._TrustedDirectory, "discard_temp", discard_then_fail
    )
    successor._fault = lambda point: (
        (_ for _ in ()).throw(RuntimeError("primary migration seam"))
        if point == "before_v4_publish"
        else None
    )
    with pytest.raises(RuntimeError, match="primary migration seam") as raised:
        successor.migrate(owner)
    assert any(
        "v4 migration cleanup failures" in note for note in raised.value.__notes__
    )
    assert any("discard cleanup seam" in note for note in raised.value.__notes__)
    assert key.value is None and state.value is None
    assert not successor.path.exists()
    assert not list(tmp_path.glob(".onyx-v4-*"))
    probe = tmp_path / "capability-probe"
    probe.mkdir()
    capability = control_plane_v4._TrustedDirectory(probe)
    capability.close()
    probe.rmdir()


def test_rollback_and_close_failures_do_not_skip_anchor_or_capability_cleanup(
    tmp_path, monkeypatch
):
    target = tmp_path / "cleanup-faults" / "v4.sqlite3"
    seed, _seed_owner, _seed_key, _seed_state = _unmigrated_successor(
        tmp_path, monkeypatch, target
    )
    journal_parent = tmp_path / "cleanup-fault-journal"
    journal_parent.mkdir()

    class CountingVault(_MemoryVault):
        def __init__(self):
            super().__init__()
            self.delete_calls = 0

        def delete(self):
            self.delete_calls += 1
            return super().delete()

    key, state = CountingVault(), CountingVault()
    successor, owner = open_v4(
        seed.source,
        seed.source_owner,
        path=target,
        journal_path=journal_parent / "v4.anchor",
        key_vault=key,
        state_vault=state,
        enabled=True,
    )
    observed = {"memory": 0, "rollback": 0, "close": 0}
    original_connect = control_plane_v4.sqlite3.connect

    class FaultingCleanupConnection:
        def __init__(self, wrapped):
            object.__setattr__(self, "wrapped", wrapped)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def __setattr__(self, name, value):
            setattr(self.wrapped, name, value)

        def execute(self, statement, *args, **kwargs):
            if str(statement).strip().upper() == "ROLLBACK":
                observed["rollback"] += 1
                raise sqlite3.OperationalError("rollback cleanup seam")
            return self.wrapped.execute(statement, *args, **kwargs)

        def close(self):
            observed["close"] += 1
            self.wrapped.close()
            raise OSError("close cleanup seam")

    def connect(database, *args, **kwargs):
        connection = original_connect(database, *args, **kwargs)
        if database == ":memory:" and kwargs.get("isolation_level", "missing") is None:
            observed["memory"] += 1
            return FaultingCleanupConnection(connection)
        return connection

    monkeypatch.setattr(control_plane_v4.sqlite3, "connect", connect)
    successor.anchor._fault = lambda point: (
        (_ for _ in ()).throw(RuntimeError("primary bootstrap cleanup seam"))
        if point == "after_bootstrap_pending"
        else None
    )
    with pytest.raises(RuntimeError, match="primary bootstrap cleanup seam") as raised:
        successor.migrate(owner)
    assert observed["rollback"] >= 1 and observed["close"] >= 1
    assert key.delete_calls >= 1 and state.delete_calls >= 1
    assert key.value is None and state.value is None
    assert not (journal_parent / "v4.anchor").exists()
    assert not target.exists()
    notes = "\n".join(raised.value.__notes__)
    assert "rollback cleanup seam" in notes and "close cleanup seam" in notes
    released = tmp_path / "cleanup-fault-journal-released"
    os.replace(journal_parent, released)
    assert released.is_dir()
    leftovers = list(released.iterdir())
    assert [item.name for item in leftovers] == ["v4.anchor.lock"]
    lock_status = leftovers[0].stat(follow_symlinks=False)
    assert leftovers[0].is_file() and lock_status.st_nlink == 1
    assert not leftovers[0].is_symlink()


def test_bootstrap_journal_identity_mismatch_rolls_back_vaults_without_unlink(
    tmp_path, monkeypatch
):
    target = tmp_path / "identity-v4.sqlite3"
    successor, owner, key, state = _unmigrated_successor(tmp_path, monkeypatch, target)

    def fault(point):
        if point != "after_bootstrap_pending":
            return
        successor._bootstrap_journal_identity = ("mismatched",)
        raise RuntimeError("primary bootstrap seam")

    successor.anchor._fault = fault
    with pytest.raises(RuntimeError, match="primary bootstrap seam") as raised:
        successor.migrate(owner)
    assert any("journal identity changed" in note for note in raised.value.__notes__)
    assert key.value is None and state.value is None
    assert successor.journal_path.is_file()
    assert not target.exists()
    successor.journal_path.unlink()


def test_preexisting_linked_publication_parent_fails_before_any_bytes(
    tmp_path, monkeypatch
):
    real = tmp_path / "real-publication"
    real.mkdir()
    linked = tmp_path / "linked-publication"
    try:
        os.symlink(real, linked, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"host cannot create a real directory link: {exc}")
    successor, owner, key, state = _unmigrated_successor(
        tmp_path, monkeypatch, linked / "v4.sqlite3"
    )
    with pytest.raises(ControlPlaneV4IntegrityError):
        successor.migrate(owner)
    assert key.value is None and state.value is None
    assert not (tmp_path / "candidate-v4.anchor").exists()
    assert not list(real.iterdir())


def test_fixture_opener_needs_no_importable_security_marker(tmp_path, monkeypatch):
    source_dir = tmp_path / "source-no-host"
    source_dir.mkdir()
    monkeypatch.setattr(
        control_plane, "private_control_plane_runtime_dir", lambda: source_dir
    )
    source = ControlPlaneStore(enabled=True).initialize()
    WorkspaceRegistry(source, enabled=True).initialize().register(
        "alpha", display_name="Alpha", workspace_class="cyryx"
    )
    migrator, source_owner = open_v3(
        source,
        journal_path=tmp_path / "source-no-host.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    migrator.migrate(source_owner)
    successor, owner = open_v4(
        migrator,
        source_owner,
        path=tmp_path / "no-host-v4.sqlite3",
        journal_path=tmp_path / "no-host-v4.anchor",
        key_vault=_MemoryVault(),
        state_vault=_MemoryVault(),
        enabled=True,
    )
    successor.migrate(owner)
    missions = MissionStore(tmp_path / "no-host-missions.sqlite3")
    mission = _mission(missions, "No host owner")
    contexts = MissionContextStore(successor, owner, missions, enabled=True)
    record = contexts.initialize_context(
        "alpha",
        mission.id,
        _spec(),
        operational_phase="WAITING_FOR_APPROVAL",
        mutation_id="no-host-init",
    )
    assert record.mission_id == mission.id
    assert not hasattr(control_plane_v4, "_host_owner_claim_for_testing")
