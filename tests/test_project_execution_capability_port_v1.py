from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from core.capability_composition_v1 import create_capability_composition_v1
from core.capability_ports.project_execution_v1 import (
    BudgetReservationV1,
    OwnedWorkerHandleV1,
    ProjectExecutionCapabilityPortV1,
    ProjectRootStateV1,
    WorkerResultV1,
)
from core.governance_nucleus_v1 import (
    GovernanceIdentityV1,
    GovernanceNucleusV1,
    GovernanceV1Denied,
)
from core.guild_execution_intent_v1 import (
    AutopilotIdentityV1,
    ExecutionIntentV1,
    GuildExecutionIntentSnapshotV1,
)
from core.guild_project_envelope_v1 import (
    DecommissionPolicyV1,
    GuildProjectLedgerSnapshotV1,
    ProjectBudgetV1,
    ProjectEnvelopeV1,
    ProjectKpiV1,
)


class _Vault:
    value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)

    def delete(self) -> bool:
        self.value = None
        return True


class _Store:
    def __init__(self) -> None:
        self.value: bytes | None = None
        self.saves = 0

    def load_bytes(self) -> bytes | None:
        return self.value

    def save_bytes(self, value: bytes) -> None:
        self.value = bytes(value)
        self.saves += 1


class _Root:
    def __init__(self) -> None:
        self.state = ProjectRootStateV1("a" * 64, False, "b" * 64)

    def observe(self) -> ProjectRootStateV1:
        return self.state


class _Budget:
    def __init__(self, quota: int = 100) -> None:
        self.quota = quota
        self.used = 0
        self.reservations: dict[str, int] = {}
        self.reconciliations: list[tuple[str, int, bool]] = []

    def reserve(self, *, key: str, amount_micro: int) -> BudgetReservationV1:
        if self.used + amount_micro > self.quota:
            raise GovernanceV1Denied("fake hard quota exhausted")
        reservation_id = "reservation-" + key
        if reservation_id not in self.reservations:
            self.reservations[reservation_id] = amount_micro
            self.used += amount_micro
        return BudgetReservationV1(reservation_id, self.reservations[reservation_id])

    def reconcile(
        self, *, reservation_id: str, actual_micro: int, uncertain: bool
    ) -> None:
        assert reservation_id in self.reservations
        self.reconciliations.append((reservation_id, actual_micro, uncertain))


class _Worker:
    def __init__(self) -> None:
        self.calls: list[OwnedWorkerHandleV1] = []
        self.cancelled: list[OwnedWorkerHandleV1] = []
        self.started = Event()
        self.release = Event()
        self.block = False
        self.raise_uncertain = False

    def execute(self, *, intent: object, handle: OwnedWorkerHandleV1) -> WorkerResultV1:
        del intent
        self.calls.append(handle)
        self.started.set()
        if self.block:
            assert self.release.wait(timeout=5)
        if self.raise_uncertain:
            raise RuntimeError("provider-free uncertain result")
        return WorkerResultV1("completed", 5, "c" * 64)

    def cancel(self, handle: OwnedWorkerHandleV1) -> bool:
        assert type(handle) is OwnedWorkerHandleV1
        self.cancelled.append(handle)
        self.release.set()
        return True


class _Approvals:
    def __init__(self) -> None:
        self.ids = {"approval-1"}

    def consume(self, *, approval_id: str, action: str, intent_id: str, project_id: str) -> bool:
        assert action == "shell" and intent_id == "intent-1" and project_id == "project-1"
        if approval_id not in self.ids:
            return False
        self.ids.remove(approval_id)
        return True


def _snapshots(action: str = "test", *, qa_limit: int = 2, missions: int = 3):
    intents = GuildExecutionIntentSnapshotV1(
        AutopilotIdentityV1("core/fake.py", "0" * 64, 1, "project_autopilot_v1"),
        (
            ExecutionIntentV1(
                "intent-1", "run-1", "stage-1", "story-1", "dev", action,
                ("core/",), ("pytest",), True,
            ),
        ),
    )
    projects = GuildProjectLedgerSnapshotV1(
        (
            ProjectEnvelopeV1(
                "project-1", "engineering", ("intent-1",),
                ProjectBudgetV1(100, 50, missions),
                (ProjectKpiV1("kpi-1", "tests", 1, "receipt"),),
                DecommissionPolicyV1(
                    qa_limit, "revoke_and_decommission",
                    "revoke_and_decommission", "kill-1",
                ),
            ),
        )
    )
    return intents, projects


def _nucleus(path: Path) -> GovernanceNucleusV1:
    return GovernanceNucleusV1(
        path=path,
        identity=GovernanceIdentityV1("owner", "workspace", "account", "profile"),
        key_vault=_Vault(), head_vault=_Vault(), pending_vault=_Vault(),
        require_windows_boundary=False,
    )


def _harness(
    tmp_path: Path,
    *,
    action: str = "test",
    quota: int = 100,
    store: _Store | None = None,
    worker: _Worker | None = None,
    root: _Root | None = None,
    approvals: _Approvals | None = None,
    qa_limit: int = 2,
    missions: int = 3,
):
    nucleus = _nucleus(tmp_path / "governance.sqlite3")
    session = nucleus.begin_session()
    store = store or _Store()
    worker = worker or _Worker()
    root = root or _Root()
    budget = _Budget(quota)
    snapshots = _snapshots(action, qa_limit=qa_limit, missions=missions)
    composition = create_capability_composition_v1(
        nucleus=nucleus,
        port_factories={
            "project_execution": lambda: ProjectExecutionCapabilityPortV1(
                principal_id=session.principal_id,
                workspace_id=session.workspace_id,
                session_id=session.session_id,
                grant_generation=session.generation,
                root_state=root.state,
                intents=snapshots[0],
                projects=snapshots[1],
                root_observer=root,
                budget=budget,
                worker=worker,
                store=store,
                approvals=approvals,
            )
        },
    )
    return nucleus, session, composition, root, budget, worker, store


def _args(session: object, key: str = "key-1", **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "principal_id": session.principal_id,
        "workspace_id": session.workspace_id,
        "session_id": session.session_id,
        "grant_generation": session.generation,
        "root_digest": "a" * 64,
        "symlink_digest": "b" * 64,
        "idempotency_key": key,
        "project_id": "project-1",
        "intent_id": "intent-1",
        "action": "test",
        "estimated_cost_micro": 10,
        "qa_iteration": 1,
        "approval_id": None,
    }
    values.update(changes)
    return values


@pytest.mark.parametrize(
    ("field", "value"),
    (("workspace_id", "wrong"), ("session_id", "stale"), ("grant_generation", 99)),
)
def test_wrong_scope_and_stale_grant_fail_before_budget_and_worker(
    tmp_path: Path, field: str, value: object
) -> None:
    _, session, composition, _, budget, worker, _ = _harness(tmp_path)
    receipt = composition.dispatch(
        session, "project_execution", "execute", _args(session, **{field: value})
    )
    assert receipt.outcome == "failed"
    assert budget.reservations == {}
    assert worker.calls == []


@pytest.mark.parametrize(
    "state",
    (
        ProjectRootStateV1("d" * 64, False, "b" * 64),
        ProjectRootStateV1("a" * 64, True, "b" * 64),
        ProjectRootStateV1("a" * 64, False, "e" * 64),
    ),
)
def test_root_dirty_and_symlink_toctou_drift_fail_closed(
    tmp_path: Path, state: ProjectRootStateV1
) -> None:
    _, session, composition, root, budget, worker, _ = _harness(tmp_path)
    plan = composition.plan(session, "project_execution", "execute", _args(session))
    root.state = state
    receipt = composition.host.dispatch(plan.binding, _args(session))
    assert receipt.outcome == "failed"
    assert not budget.reservations and not worker.calls


def test_budget_exhaustion_and_bounded_qa_never_reach_worker(tmp_path: Path) -> None:
    _, session, composition, _, _, worker, _ = _harness(tmp_path, quota=5, qa_limit=2)
    exhausted = composition.dispatch(session, "project_execution", "execute", _args(session))
    qa = composition.dispatch(
        session, "project_execution", "execute", _args(session, "key-2", qa_iteration=3)
    )
    assert exhausted.outcome == qa.outcome == "failed"
    assert worker.calls == []


def test_duplicate_is_idempotent_and_mismatch_is_denied(tmp_path: Path) -> None:
    _, session, composition, _, budget, worker, _ = _harness(tmp_path)
    first = composition.dispatch(session, "project_execution", "execute", _args(session))
    duplicate = composition.dispatch(session, "project_execution", "execute", _args(session))
    mismatch = composition.dispatch(
        session, "project_execution", "execute", _args(session, estimated_cost_micro=11)
    )
    assert first.outcome == duplicate.outcome == "completed"
    assert mismatch.outcome == "failed"
    assert len(worker.calls) == len(budget.reservations) == 1


def test_uncertain_result_consumes_and_reconciles_budget(tmp_path: Path) -> None:
    worker = _Worker()
    worker.raise_uncertain = True
    _, session, composition, _, budget, _, _ = _harness(tmp_path, worker=worker)
    receipt = composition.dispatch(session, "project_execution", "execute", _args(session))
    assert receipt.outcome == "completed"  # Adapter uncertainty is content-redacted by host.
    assert budget.reconciliations == [("reservation-key-1", 10, True)]


def test_restart_restores_replay_without_startup_mutation(tmp_path: Path) -> None:
    store = _Store()
    nucleus, session, composition, _, _, worker, _ = _harness(
        tmp_path / "one", store=store
    )
    assert store.saves == 0
    assert composition.dispatch(session, "project_execution", "execute", _args(session)).outcome == "completed"
    saves = store.saves
    # Reuse the exact authority binding while changing only the governance DB location.
    snapshots = _snapshots()
    root = _Root()
    budget = _Budget()
    restarted_worker = _Worker()
    restarted = create_capability_composition_v1(
        nucleus=nucleus,
        port_factories={
            "project_execution": lambda: ProjectExecutionCapabilityPortV1(
                principal_id=session.principal_id,
                workspace_id=session.workspace_id,
                session_id=session.session_id,
                grant_generation=session.generation,
                root_state=root.state,
                intents=snapshots[0],
                projects=snapshots[1],
                root_observer=root,
                budget=budget,
                worker=restarted_worker,
                store=store,
            )
        },
    )
    assert store.saves == saves
    assert restarted.dispatch(
        session, "project_execution", "execute", _args(session)
    ).outcome == "completed"
    assert restarted_worker.calls == []


def test_revoke_during_dispatch_is_uncertain_and_cancels_only_owned_handle(tmp_path: Path) -> None:
    worker = _Worker()
    worker.block = True
    _, session, composition, _, budget, _, _ = _harness(tmp_path, worker=worker)
    arguments = _args(session)
    plan = composition.plan(session, "project_execution", "execute", arguments)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(composition.host.dispatch, plan.binding, arguments)
        assert worker.started.wait(timeout=5)
        composition.terminate("revoke", binding_id=plan.binding.binding_id)
        receipt = future.result(timeout=5)
    assert receipt.outcome == "uncertain"
    assert worker.cancelled == worker.calls
    assert budget.reconciliations[-1][-1] is True


def test_always_explicit_action_needs_separate_one_use_approval(tmp_path: Path) -> None:
    approvals = _Approvals()
    _, session, composition, _, _, worker, _ = _harness(
        tmp_path, action="shell", approvals=approvals
    )
    denied = composition.dispatch(
        session, "project_execution", "execute", _args(session, action="shell")
    )
    allowed = composition.dispatch(
        session, "project_execution", "execute",
        _args(session, "key-2", action="shell", approval_id="approval-1"),
    )
    replay_approval = composition.dispatch(
        session, "project_execution", "execute",
        _args(session, "key-3", action="shell", approval_id="approval-1"),
    )
    assert denied.outcome == replay_approval.outcome == "failed"
    assert allowed.outcome == "completed"
    assert len(worker.calls) == 1


def test_kill_is_durable_and_does_not_accept_pid_or_process_handles(tmp_path: Path) -> None:
    store = _Store()
    _, session, composition, _, _, worker, _ = _harness(tmp_path, store=store)
    assert composition.kill() is composition.kill()
    with pytest.raises(GovernanceV1Denied):
        composition.plan(session, "project_execution", "execute", _args(session))
    assert worker.cancelled == []
    assert b'"killed":true' in (store.value or b"")
    assert "pid" not in ProjectExecutionCapabilityPortV1.kill.__annotations__


def test_intent_project_and_action_receipt_mismatches_are_denied(tmp_path: Path) -> None:
    _, session, composition, _, budget, worker, _ = _harness(tmp_path)
    wrong_project = composition.dispatch(
        session, "project_execution", "execute", _args(session, project_id="other")
    )
    wrong_action = composition.dispatch(
        session, "project_execution", "execute", _args(session, "key-2", action="edit")
    )
    assert wrong_project.outcome == wrong_action.outcome == "failed"
    assert not budget.reservations and not worker.calls
