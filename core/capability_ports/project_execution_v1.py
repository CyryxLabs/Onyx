"""Provider-free governed execution adapter for accepted Guild A9.4/A9.5 data.

The accepted Guild ledgers remain inert.  This port adapts their immutable
records to the governed host and delegates only to injected, provider-free
boundaries.  Construction reads injected state but never writes it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1
from core.guild_execution_intent_v1 import GuildExecutionIntentSnapshotV1
from core.guild_project_envelope_v1 import GuildProjectLedgerSnapshotV1

OPERATIONS = frozenset({"execute", "status"})
SCHEMA = "OnyxProjectExecutionState.v1"
MAX_ID_BYTES = 256
MAX_QA_ITERATIONS = 8
SAFE_ACTIONS = frozenset({"inspect", "edit", "test", "qa"})
ALWAYS_EXPLICIT_ACTIONS = frozenset(
    {"shell", "commit", "push", "pr", "deploy", "publish", "spend"}
)


def _digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GovernanceV1ContractError("project execution value is not canonical") from exc
    return hashlib.sha256(encoded).hexdigest()


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > MAX_ID_BYTES:
        raise GovernanceV1ContractError(f"{field} contract violation")
    return value


@dataclass(frozen=True, slots=True)
class ProjectRootStateV1:
    root_digest: str
    dirty: bool
    symlink_digest: str

    def __post_init__(self) -> None:
        _text(self.root_digest, "root_digest")
        _text(self.symlink_digest, "symlink_digest")
        if type(self.dirty) is not bool:
            raise GovernanceV1ContractError("dirty must be exact bool")


@dataclass(frozen=True, slots=True)
class ProjectExecutionIntentV1:
    intent_id: str
    project_id: str
    story_id: str
    action: str
    patch_scope: tuple[str, ...]
    gate_argv_shape: tuple[str, ...]
    requires_owner_approval: bool


@dataclass(frozen=True, slots=True)
class ProjectExecutionEnvelopeV1:
    project_id: str
    intent_ids: tuple[str, ...]
    cost_cap_micro: int
    max_missions: int
    max_qa_iterations: int
    kill_switch_ref: str


@dataclass(frozen=True, slots=True)
class OwnedWorkerHandleV1:
    handle_id: str
    execution_id: str


@dataclass(frozen=True, slots=True)
class WorkerResultV1:
    outcome: str
    cost_micro: int
    result_digest: str
    uncertain: bool = False
    qa_passed: bool = True


@dataclass(frozen=True, slots=True)
class BudgetReservationV1:
    reservation_id: str
    amount_micro: int


class ProjectExecutionStateStoreV1(Protocol):
    def load_bytes(self) -> bytes | None: ...
    def save_bytes(self, value: bytes) -> None: ...


class ProjectRootObserverV1(Protocol):
    def observe(self) -> ProjectRootStateV1: ...


class ProjectBudgetGatewayV1(Protocol):
    def reserve(self, *, key: str, amount_micro: int) -> BudgetReservationV1: ...
    def reconcile(
        self, *, reservation_id: str, actual_micro: int, uncertain: bool
    ) -> None: ...


class ProjectWorkerV1(Protocol):
    def execute(
        self, *, intent: ProjectExecutionIntentV1, handle: OwnedWorkerHandleV1
    ) -> WorkerResultV1: ...
    def cancel(self, handle: OwnedWorkerHandleV1) -> bool: ...


class ExplicitActionApprovalsV1(Protocol):
    def consume(
        self, *, approval_id: str, action: str, intent_id: str, project_id: str
    ) -> bool: ...


def adapt_execution_intents_v1(
    intents: GuildExecutionIntentSnapshotV1,
    projects: GuildProjectLedgerSnapshotV1,
) -> tuple[ProjectExecutionIntentV1, ...]:
    """Adapt accepted inert records without creating authority."""
    if type(intents) is not GuildExecutionIntentSnapshotV1:
        raise GovernanceV1ContractError("exact A9.4 snapshot is required")
    if type(projects) is not GuildProjectLedgerSnapshotV1:
        raise GovernanceV1ContractError("exact A9.5 snapshot is required")
    source = {item.intent_id: item for item in intents.intents}
    adapted: list[ProjectExecutionIntentV1] = []
    seen: set[str] = set()
    for envelope in projects.envelopes:
        for intent_id in envelope.intent_ids:
            item = source.get(intent_id)
            if item is None or item.requires_owner_approval is not True:
                raise GovernanceV1Denied("project intent is absent or not owner-gated")
            if intent_id in seen:
                raise GovernanceV1Denied("project intent has multiple envelopes")
            seen.add(intent_id)
            adapted.append(
                ProjectExecutionIntentV1(
                    item.intent_id,
                    envelope.project_id,
                    item.story_id,
                    item.required_operation,
                    item.patch_scope,
                    item.gate_argv_shape,
                    True,
                )
            )
    return tuple(adapted)


def adapt_project_envelopes_v1(
    projects: GuildProjectLedgerSnapshotV1,
) -> tuple[ProjectExecutionEnvelopeV1, ...]:
    if type(projects) is not GuildProjectLedgerSnapshotV1:
        raise GovernanceV1ContractError("exact A9.5 snapshot is required")
    return tuple(
        ProjectExecutionEnvelopeV1(
            item.project_id,
            item.intent_ids,
            item.budget.cost_cap_micro,
            item.budget.max_missions,
            min(item.decommission.max_consecutive_gate_failures, MAX_QA_ITERATIONS),
            item.decommission.kill_switch_ref,
        )
        for item in projects.envelopes
    )


class ProjectExecutionCapabilityPortV1(HostBoundCapabilityPortV1):
    """Host-authorized, budgeted, replay-safe dispatch over owned fake workers."""

    def __init__(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        session_id: str,
        grant_generation: int,
        root_state: ProjectRootStateV1,
        intents: GuildExecutionIntentSnapshotV1,
        projects: GuildProjectLedgerSnapshotV1,
        root_observer: ProjectRootObserverV1,
        budget: ProjectBudgetGatewayV1,
        worker: ProjectWorkerV1,
        store: ProjectExecutionStateStoreV1,
        approvals: ExplicitActionApprovalsV1 | None = None,
    ) -> None:
        super().__init__()
        self._principal_id = _text(principal_id, "principal_id")
        self._workspace_id = _text(workspace_id, "workspace_id")
        self._session_id = _text(session_id, "session_id")
        if type(grant_generation) is not int or grant_generation < 1:
            raise GovernanceV1ContractError("grant_generation contract violation")
        if type(root_state) is not ProjectRootStateV1 or root_state.dirty:
            raise GovernanceV1Denied("clean typed project root state is required")
        for dependency, methods in (
            (root_observer, ("observe",)),
            (budget, ("reserve", "reconcile")),
            (worker, ("execute", "cancel")),
            (store, ("load_bytes", "save_bytes")),
        ):
            if any(not callable(getattr(dependency, method, None)) for method in methods):
                raise GovernanceV1ContractError("project execution dependency contract violation")
        if approvals is not None and not callable(getattr(approvals, "consume", None)):
            raise GovernanceV1ContractError("approval fixture contract violation")
        self._grant_generation = grant_generation
        self._root_state = root_state
        self._root_observer = root_observer
        self._budget = budget
        self._worker = worker
        self._store = store
        self._approvals = approvals
        self._intents = {item.intent_id: item for item in adapt_execution_intents_v1(intents, projects)}
        self._projects = {item.project_id: item for item in adapt_project_envelopes_v1(projects)}
        self._lock = RLock()
        self._killed = False
        self._revoked: set[str] = set()
        self._revoke_epoch = 0
        self._active: dict[str, OwnedWorkerHandleV1] = {}
        self._results: dict[str, dict[str, object]] = {}
        self._missions: dict[str, int] = {}
        raw = store.load_bytes()
        if raw is not None:
            self._restore(raw)

    def _restore(self, raw: bytes) -> None:
        try:
            state = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GovernanceV1ContractError("project execution state is malformed") from exc
        if type(state) is not dict or set(state) != {
            "schema", "binding", "killed", "revoked", "revoke_epoch", "results", "missions"
        }:
            raise GovernanceV1ContractError("project execution state contract violation")
        binding = {
            "principal_id": self._principal_id,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "grant_generation": self._grant_generation,
            "root_digest": self._root_state.root_digest,
            "symlink_digest": self._root_state.symlink_digest,
        }
        if state["schema"] != SCHEMA or state["binding"] != binding:
            raise GovernanceV1Denied("persisted project execution binding mismatch")
        if type(state["killed"]) is not bool or type(state["revoked"]) is not list:
            raise GovernanceV1ContractError("project execution lifecycle state is malformed")
        if type(state["results"]) is not dict or type(state["missions"]) is not dict:
            raise GovernanceV1ContractError("project execution ledger is malformed")
        self._killed = state["killed"]
        self._revoked = set(state["revoked"])
        self._revoke_epoch = state["revoke_epoch"]
        self._results = state["results"]
        self._missions = state["missions"]
        if any(type(key) is not str for key in self._revoked):
            raise GovernanceV1ContractError("project execution revocation is malformed")
        if type(self._revoke_epoch) is not int or self._revoke_epoch < 0:
            raise GovernanceV1ContractError("project revoke epoch is malformed")
        if any(type(value) is not int or value < 0 for value in self._missions.values()):
            raise GovernanceV1ContractError("project mission count is malformed")

    def _encoded(self) -> bytes:
        binding = {
            "principal_id": self._principal_id,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "grant_generation": self._grant_generation,
            "root_digest": self._root_state.root_digest,
            "symlink_digest": self._root_state.symlink_digest,
        }
        return json.dumps(
            {
                "schema": SCHEMA,
                "binding": binding,
                "killed": self._killed,
                "revoked": sorted(self._revoked),
                "revoke_epoch": self._revoke_epoch,
                "results": self._results,
                "missions": self._missions,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _save(self) -> None:
        self._store.save_bytes(self._encoded())

    def _scope(self, arguments: Mapping[str, object], operation: str) -> None:
        common = {
            "principal_id", "workspace_id", "session_id", "grant_generation",
            "root_digest", "symlink_digest", "idempotency_key",
        }
        execute = {
            "project_id", "intent_id", "action", "estimated_cost_micro",
            "qa_iteration", "approval_id",
        }
        expected = common | (execute if operation == "execute" else set())
        if type(arguments) is not dict or set(arguments) != expected:
            raise GovernanceV1ContractError("project execution arguments contract violation")
        expected_values = (
            ("principal_id", self._principal_id),
            ("workspace_id", self._workspace_id),
            ("session_id", self._session_id),
            ("grant_generation", self._grant_generation),
            ("root_digest", self._root_state.root_digest),
            ("symlink_digest", self._root_state.symlink_digest),
        )
        if any(arguments[key] != value for key, value in expected_values):
            raise GovernanceV1Denied("project execution scope binding mismatch")
        _text(arguments["idempotency_key"], "idempotency_key")

    def _assert_root(self) -> None:
        observed = self._root_observer.observe()
        if type(observed) is not ProjectRootStateV1:
            raise GovernanceV1Denied("project root observation is not typed")
        if observed.dirty or observed != self._root_state:
            raise GovernanceV1Denied("project root, dirty state, or symlink graph drifted")

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        self._scope(arguments, operation)
        self._assert_root()
        key = str(arguments["idempotency_key"])
        fingerprint = _digest({"operation": operation, "arguments": arguments})
        with self._lock:
            if self._killed:
                raise GovernanceV1Denied("project execution kill is latched")
            prior = self._results.get(key)
            if prior is not None:
                if prior["fingerprint"] != fingerprint:
                    raise GovernanceV1Denied("project execution replay mismatch")
                return dict(prior["receipt"])
            if operation == "status":
                receipt = {
                    "status": "ready", "killed": False,
                    "active_count": len(self._active), "redacted": True,
                }
                self._results[key] = {"fingerprint": fingerprint, "receipt": receipt}
                self._save()
                return receipt
        return self._execute(arguments, key, fingerprint)

    def _execute(
        self, arguments: Mapping[str, object], key: str, fingerprint: str
    ) -> dict[str, object]:
        project_id = _text(arguments["project_id"], "project_id")
        intent_id = _text(arguments["intent_id"], "intent_id")
        action = _text(arguments["action"], "action")
        intent = self._intents.get(intent_id)
        envelope = self._projects.get(project_id)
        if intent is None or envelope is None or intent.project_id != project_id:
            raise GovernanceV1Denied("intent and project correlation mismatch")
        if action != intent.action:
            raise GovernanceV1Denied("requested action does not match sealed intent")
        if action not in SAFE_ACTIONS | ALWAYS_EXPLICIT_ACTIONS:
            raise GovernanceV1Denied("project action is outside the closed vocabulary")
        approval_id = arguments["approval_id"]
        if action in ALWAYS_EXPLICIT_ACTIONS:
            if (
                type(approval_id) is not str
                or not approval_id
                or self._approvals is None
                or self._approvals.consume(
                    approval_id=approval_id,
                    action=action,
                    intent_id=intent_id,
                    project_id=project_id,
                )
                is not True
            ):
                raise GovernanceV1Denied("explicit action requires a one-use approval fixture")
        elif approval_id is not None:
            raise GovernanceV1ContractError("safe action approval_id must be null")
        amount = arguments["estimated_cost_micro"]
        qa_iteration = arguments["qa_iteration"]
        if type(amount) is not int or isinstance(amount, bool) or amount < 1:
            raise GovernanceV1ContractError("estimated cost must be positive micro-units")
        if type(qa_iteration) is not int or not 1 <= qa_iteration <= envelope.max_qa_iterations:
            raise GovernanceV1Denied("bounded QA iteration exceeded")
        with self._lock:
            if self._killed or intent_id in self._revoked:
                raise GovernanceV1Denied("project intent is killed or revoked")
            if self._missions.get(project_id, 0) >= envelope.max_missions:
                raise GovernanceV1Denied("project mission budget exhausted")
        reservation = self._budget.reserve(key=key, amount_micro=amount)
        if type(reservation) is not BudgetReservationV1 or reservation.amount_micro != amount:
            raise GovernanceV1Denied("budget reservation correlation mismatch")
        execution_id = "execution-" + _digest(
            {"key": key, "intent_id": intent_id, "project_id": project_id}
        )[:32]
        handle = OwnedWorkerHandleV1("worker-" + _digest(execution_id)[:32], execution_id)
        with self._lock:
            if self._killed or intent_id in self._revoked:
                self._budget.reconcile(
                    reservation_id=reservation.reservation_id,
                    actual_micro=amount,
                    uncertain=True,
                )
                raise GovernanceV1Denied("project execution revoked after reservation")
            self._active[execution_id] = handle
            self._missions[project_id] = self._missions.get(project_id, 0) + 1
            dispatch_revoke_epoch = self._revoke_epoch
            self._save()
        result: WorkerResultV1 | None = None
        uncertain = False
        try:
            result = self._worker.execute(intent=intent, handle=handle)
            if type(result) is not WorkerResultV1:
                raise GovernanceV1Denied("worker result is not typed")
            if result.outcome not in {"completed", "failed"}:
                raise GovernanceV1Denied("worker outcome is outside the closed vocabulary")
            if type(result.cost_micro) is not int or not 0 <= result.cost_micro <= amount:
                raise GovernanceV1Denied("worker cost and reservation mismatch")
            _text(result.result_digest, "result_digest")
            uncertain = result.uncertain
        except Exception:
            uncertain = True
        finally:
            with self._lock:
                revoked = (
                    self._killed
                    or intent_id in self._revoked
                    or self._revoke_epoch != dispatch_revoke_epoch
                )
                self._active.pop(execution_id, None)
            uncertain = uncertain or revoked
            actual = amount if result is None else result.cost_micro
            self._budget.reconcile(
                reservation_id=reservation.reservation_id,
                actual_micro=actual,
                uncertain=uncertain,
            )
        outcome = "uncertain" if uncertain else result.outcome
        receipt = {
            "execution_id": execution_id,
            "project_id_digest": _digest(project_id),
            "intent_id_digest": _digest(intent_id),
            "reservation_id_digest": _digest(reservation.reservation_id),
            "outcome": outcome,
            "result_digest": "" if result is None else result.result_digest,
            "uncertain": uncertain,
            "redacted": True,
        }
        self._results[key] = {"fingerprint": fingerprint, "receipt": receipt}
        self._save()
        return receipt

    def revoke(self, binding_id: str) -> None:
        """Durably observe host revoke and cancel owned workers only."""
        with self._lock:
            self._revoked.add(binding_id)
            self._revoke_epoch += 1
            handles = tuple(self._active.values())
            self._save()
        for handle in handles:
            self._worker.cancel(handle)

    def kill(self) -> bool:
        with self._lock:
            if self._killed:
                return True
            self._killed = True
            handles = tuple(self._active.values())
            self._save()
        confirmed = True
        for handle in handles:
            confirmed = self._worker.cancel(handle) is True and confirmed
        return confirmed


__all__ = [
    "ALWAYS_EXPLICIT_ACTIONS",
    "MAX_QA_ITERATIONS",
    "OPERATIONS",
    "SAFE_ACTIONS",
    "BudgetReservationV1",
    "ExplicitActionApprovalsV1",
    "OwnedWorkerHandleV1",
    "ProjectBudgetGatewayV1",
    "ProjectExecutionCapabilityPortV1",
    "ProjectExecutionEnvelopeV1",
    "ProjectExecutionIntentV1",
    "ProjectExecutionStateStoreV1",
    "ProjectRootObserverV1",
    "ProjectRootStateV1",
    "ProjectWorkerV1",
    "WorkerResultV1",
    "adapt_execution_intents_v1",
    "adapt_project_envelopes_v1",
]
