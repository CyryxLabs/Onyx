"""Versioned mission-context service over the schema-v4 successor.

The service observes :class:`core.missions.MissionStore` only through its
atomic ``authority_snapshot`` API.  It cannot claim, lease, execute,
authorize, or transition a mission.  Same-process Python is not a security
boundary; production construction remains unavailable.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from core.control_plane_v4 import (
    ControlPlaneV4Conflict,
    ControlPlaneV4Store,
    V4MissionMutation,
    V4OwnerCapability,
)
from core.mission_context_contracts import (
    CONTEXT_CONTRACT,
    INITIAL_PHASE_FOR_STATE,
    MissionContextContractError,
    PHASES,
    PHASE_STATES,
    PHASE_TRANSITIONS_V1,
    TERMINAL_FOR_STATE,
    TERMINAL_PHASES,
    validate_context_payload,
    validate_phase_for_state,
)
from core.missions import MissionAuthoritySnapshot, MissionStore
from memory.store import contains_secret


PHASE_EVENT_CONTRACT = "MissionPhaseEvent.v1"
LEGACY_WORKSPACE_ID = "legacy-default"
_DATA_CLASSES = frozenset({"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"})
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}")
_EMPTY_EVENT_HASH = hashlib.sha256(b"ONYX-MISSION-EVENT-EMPTY\0").hexdigest()


class MissionContextError(RuntimeError):
    pass


class MissionContextDisabled(MissionContextError):
    pass


class MissionContextNotFound(MissionContextError):
    pass


class MissionContextIsolationError(MissionContextError):
    pass


class MissionContextInvalid(MissionContextError):
    pass


class MissionAuthorityDrift(MissionContextError):
    pass


class MissionPhaseConflict(MissionContextError):
    pass


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, name: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise MissionContextInvalid(f"{name} must be text")
    result = " ".join(value.split())
    if (not result and not empty) or result != value or len(result) > maximum:
        raise MissionContextInvalid(f"{name} is invalid")
    if contains_secret(result):
        raise MissionContextInvalid(f"{name} contains restricted material")
    return result


def _strings(value: object, name: str, maximum: int = 100) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise MissionContextInvalid(f"{name} must be a bounded list")
    output = tuple(_text(item, name, 1000) for item in value)
    if len(set(output)) != len(output):
        raise MissionContextInvalid(f"{name} contains duplicates")
    return output


def _budgets(value: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, Mapping) or len(value) > 32:
        raise MissionContextInvalid("budget_dimensions must be a bounded object")
    output = []
    for key, raw in value.items():
        name = _text(key, "budget dimension", 64)
        if not _SAFE_ID.fullmatch(name):
            raise MissionContextInvalid("budget dimension name is invalid")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0 or raw > 1e15:
            raise MissionContextInvalid("budget dimension value is invalid")
        output.append((name, float(raw)))
    output.sort()
    return tuple(output)


@dataclass(frozen=True, slots=True)
class MissionContextSpec:
    objective: str
    definition_of_done: tuple[str, ...]
    scope: tuple[str, ...]
    exclusions: tuple[str, ...]
    data_classification: str
    allowed_targets: tuple[str, ...]
    budget_dimensions: tuple[tuple[str, float], ...]
    autonomy_mode: str
    autonomy_expires_at: str | None
    checkpoint: str
    rollback_plan: str
    recovery_status: str

    @classmethod
    def build(
        cls,
        *,
        objective: object,
        definition_of_done: object,
        scope: object = (),
        exclusions: object = (),
        data_classification: object = "INTERNAL",
        allowed_targets: object = (),
        budget_dimensions: object = None,
        autonomy_mode: object = "C",
        autonomy_expires_at: object = None,
        checkpoint: object = "not_started",
        rollback_plan: object = "Disable the v4 extension; MissionStore remains authoritative.",
        recovery_status: object = "clean",
    ) -> "MissionContextSpec":
        data_class = _text(data_classification, "data_classification", 32).upper()
        if data_class not in _DATA_CLASSES:
            raise MissionContextInvalid("data_classification is invalid")
        mode = _text(autonomy_mode, "autonomy_mode", 64)
        if not _SAFE_ID.fullmatch(mode):
            raise MissionContextInvalid("autonomy_mode is invalid")
        expiry = None
        if autonomy_expires_at is not None:
            expiry = _text(autonomy_expires_at, "autonomy_expires_at", 40)
            try:
                datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            except ValueError as exc:
                raise MissionContextInvalid("autonomy_expires_at is invalid") from exc
        return cls(
            _text(objective, "objective", 4000),
            _strings(definition_of_done, "definition_of_done"),
            _strings(scope, "scope"),
            _strings(exclusions, "exclusions"),
            data_class,
            _strings(allowed_targets, "allowed_targets"),
            _budgets({} if budget_dimensions is None else budget_dimensions),
            mode,
            expiry,
            _text(checkpoint, "checkpoint", 1000),
            _text(rollback_plan, "rollback_plan", 4000),
            _text(recovery_status, "recovery_status", 1000),
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "contract": CONTEXT_CONTRACT,
            "objective": self.objective,
            "definition_of_done": list(self.definition_of_done),
            "scope": list(self.scope),
            "exclusions": list(self.exclusions),
            "data_classification": self.data_classification,
            "allowed_targets": list(self.allowed_targets),
            "budget_dimensions": dict(self.budget_dimensions),
            "autonomy_mode": self.autonomy_mode,
            "autonomy_expires_at": self.autonomy_expires_at,
            "checkpoint": self.checkpoint,
            "rollback_plan": self.rollback_plan,
            "recovery_status": self.recovery_status,
        }

    def with_updates(self, updates: Mapping[str, object] | None) -> "MissionContextSpec":
        if not updates:
            return self
        allowed = {"checkpoint", "rollback_plan", "recovery_status", "autonomy_expires_at"}
        if set(updates) - allowed:
            raise MissionContextInvalid("context update contains immutable or unknown fields")
        values = self.as_payload()
        values.update(updates)
        values.pop("contract")
        return MissionContextSpec.build(**values)


@dataclass(frozen=True, slots=True)
class MissionContextRecord:
    mission_id: str
    workspace_id: str
    revision: int
    correlation_id: str
    operational_phase: str
    spec: MissionContextSpec
    mission_snapshot_sha256: str
    mission_event_seq: int
    mission_event_sha256: str
    revision_sha256: str
    created_at: str


@dataclass(frozen=True, slots=True)
class MissionPhaseEvent:
    event_id: str
    mission_id: str
    revision: int
    workspace_id: str
    event_type: str
    from_phase: str | None
    to_phase: str
    mission_snapshot_sha256: str
    mission_event_seq: int
    mission_event_sha256: str
    event_sha256: str
    occurred_at: str


def _authority_snapshot(store: MissionStore, mission_id: str) -> MissionAuthoritySnapshot:
    snapshot = store.authority_snapshot(mission_id)
    if not isinstance(snapshot, MissionAuthoritySnapshot):
        raise MissionAuthorityDrift("mission authority snapshot contract is invalid")
    return snapshot


def _spec_from_payload(payload: Mapping[str, object]) -> MissionContextSpec:
    try:
        validate_context_payload(payload)
    except MissionContextContractError as exc:
        raise MissionContextInvalid(str(exc)) from None
    return MissionContextSpec.build(
        objective=payload.get("objective"),
        definition_of_done=payload.get("definition_of_done"),
        scope=payload.get("scope"),
        exclusions=payload.get("exclusions"),
        data_classification=payload.get("data_classification"),
        allowed_targets=payload.get("allowed_targets"),
        budget_dimensions=payload.get("budget_dimensions"),
        autonomy_mode=payload.get("autonomy_mode"),
        autonomy_expires_at=payload.get("autonomy_expires_at"),
        checkpoint=payload.get("checkpoint"),
        rollback_plan=payload.get("rollback_plan"),
        recovery_status=payload.get("recovery_status"),
    )


class MissionContextStore:
    def __init__(
        self,
        control_plane: ControlPlaneV4Store,
        owner: V4OwnerCapability,
        missions: MissionStore,
        *,
        enabled: bool,
        _legacy_access_token: object | None = None,
    ):
        if type(enabled) is not bool:
            raise TypeError("mission context flag must be bool")
        self._control_plane = control_plane
        self._owner = owner
        self._missions = missions
        self.enabled = enabled
        self._allow_legacy = _legacy_access_token is _LEGACY_ADAPTER_SEAL

    def _assert_enabled(self) -> None:
        if not self.enabled:
            raise MissionContextDisabled("mission context v4 is disabled")
        self._control_plane.assert_operational_owner(self._owner)

    def _assert_workspace_access(self, workspace_id: object) -> str:
        workspace = self._id(workspace_id, "workspace_id")
        if workspace == LEGACY_WORKSPACE_ID and not self._allow_legacy:
            raise MissionContextIsolationError("legacy-default requires explicit legacy adapter")
        return workspace

    @staticmethod
    def _id(value: object, name: str) -> str:
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise MissionContextInvalid(f"{name} is invalid")
        return value

    @staticmethod
    def _record(row: Mapping[str, object]) -> MissionContextRecord:
        payload = json.loads(row["context_json"])
        return MissionContextRecord(
            row["mission_id"],
            row["workspace_id"],
            int(row["revision"]),
            row["correlation_id"],
            row["operational_phase"],
            _spec_from_payload(payload),
            row["mission_snapshot_sha256"],
            int(row["mission_event_seq"]),
            row["mission_event_sha256"],
            row["revision_sha256"],
            row["created_at"],
        )

    @staticmethod
    def _validate_phase(phase: object, state: str) -> str:
        try:
            return validate_phase_for_state(phase, state)
        except MissionContextContractError as exc:
            if isinstance(phase, str) and phase in PHASES:
                raise MissionPhaseConflict(str(exc)) from None
            raise MissionContextInvalid(str(exc)) from None

    def initialize_context(
        self,
        workspace_id: object,
        mission_id: object,
        spec: MissionContextSpec,
        *,
        operational_phase: object,
        mutation_id: object,
        correlation_id: object | None = None,
        _legacy_reviewed_source_sha256: str | None = None,
        _authority_baseline: MissionAuthoritySnapshot | None = None,
    ) -> MissionContextRecord:
        self._assert_enabled()
        if not isinstance(spec, MissionContextSpec):
            raise TypeError("spec must be MissionContextSpec")
        mission = self._id(mission_id, "mission_id")
        mutation = self._id(mutation_id, "mutation_id")
        correlation = self._id(correlation_id or f"mission-{mission}", "correlation_id")
        workspace = self._assert_workspace_access(workspace_id)
        authority = (
            _authority_snapshot(self._missions, mission)
            if _authority_baseline is None else _authority_baseline
        )
        if not isinstance(authority, MissionAuthoritySnapshot) or authority.mission_id != mission:
            raise MissionAuthorityDrift("mission authority baseline is invalid")
        phase = self._validate_phase(operational_phase, authority.state)
        request_hash = _sha(
            ["initialize", workspace, mission, spec.as_payload(), phase, correlation, authority.snapshot_hash]
        )
        try:
            bundle = self._control_plane.apply_mission_mutation(
                self._owner,
                V4MissionMutation(
                    "initialize", mutation, request_hash, mission,
                    workspace, correlation, phase,
                    _canonical(spec.as_payload()), authority.snapshot_hash,
                    authority.event_seq, authority.event_hash, -1, _utc_now(),
                    _legacy_reviewed_source_sha256,
                ),
            )
        except ControlPlaneV4Conflict as exc:
            if "workspace" in str(exc) or "legacy" in str(exc):
                raise MissionContextIsolationError(str(exc)) from None
            raise MissionPhaseConflict(str(exc)) from None
        after = _authority_snapshot(self._missions, mission)
        if after != authority:
            raise MissionAuthorityDrift("mission authority changed during context mutation")
        record = self._record(bundle[0])
        self._validate_phase(record.operational_phase, after.state)
        return record

    def get_context(self, workspace_id: object, mission_id: object) -> MissionContextRecord:
        self._assert_enabled()
        mission = self._id(mission_id, "mission_id")
        workspace = self._assert_workspace_access(workspace_id)
        before = _authority_snapshot(self._missions, mission)
        try:
            bundle = self._control_plane.read_context_bundle(
                self._owner, workspace, mission
            )
        except ControlPlaneV4Conflict as exc:
            raise MissionContextIsolationError(str(exc)) from None
        authority = _authority_snapshot(self._missions, mission)
        if authority != before:
            raise MissionAuthorityDrift("mission authority changed during context read")
        record = self._record(bundle[0])
        if (
            record.mission_snapshot_sha256 != authority.snapshot_hash
            or record.mission_event_seq != authority.event_seq
            or record.mission_event_sha256 != authority.event_hash
        ):
            raise MissionAuthorityDrift("mission context is stale and requires a phase transition or terminal reconcile")
        self._validate_phase(record.operational_phase, authority.state)
        return record

    def list_events(self, workspace_id: object, mission_id: object) -> tuple[MissionPhaseEvent, ...]:
        self._assert_enabled()
        mission = self._id(mission_id, "mission_id")
        workspace = self._assert_workspace_access(workspace_id)
        rows = self._control_plane.read_mission_events(
            self._owner, workspace, mission
        )
        return tuple(MissionPhaseEvent(
            row["event_id"], row["mission_id"], int(row["revision"]), row["workspace_id"],
            row["event_type"], row["from_phase"], row["to_phase"],
            row["mission_snapshot_sha256"], int(row["mission_event_seq"]),
            row["mission_event_sha256"], row["event_sha256"], row["occurred_at"],
        ) for row in rows)

    def transition(
        self,
        workspace_id: object,
        mission_id: object,
        target_phase: object,
        *,
        expected_revision: int,
        mutation_id: object,
        updates: Mapping[str, object] | None = None,
    ) -> MissionContextRecord:
        return self._advance(
            workspace_id,
            mission_id,
            target_phase,
            expected_revision=expected_revision,
            mutation_id=mutation_id,
            updates=updates,
            reconcile=False,
        )

    def reconcile_terminal(
        self,
        workspace_id: object,
        mission_id: object,
        *,
        expected_revision: int,
        mutation_id: object,
        updates: Mapping[str, object] | None = None,
    ) -> MissionContextRecord:
        self._assert_enabled()
        workspace = self._assert_workspace_access(workspace_id)
        mission = self._id(mission_id, "mission_id")
        authority = _authority_snapshot(self._missions, mission)
        target = TERMINAL_FOR_STATE.get(authority.state)
        if target is None:
            raise MissionPhaseConflict("mission is not terminal")
        return self._advance(
            workspace,
            mission,
            target,
            expected_revision=expected_revision,
            mutation_id=mutation_id,
            updates=updates,
            reconcile=True,
            _authority_baseline=authority,
        )

    def _advance(
        self,
        workspace_id: object,
        mission_id: object,
        target_phase: object,
        *,
        expected_revision: int,
        mutation_id: object,
        updates: Mapping[str, object] | None,
        reconcile: bool,
        _authority_baseline: MissionAuthoritySnapshot | None = None,
    ) -> MissionContextRecord:
        self._assert_enabled()
        if type(expected_revision) is not int or expected_revision < 0:
            raise MissionContextInvalid("expected_revision is invalid")
        mission = self._id(mission_id, "mission_id")
        workspace = self._assert_workspace_access(workspace_id)
        mutation = self._id(mutation_id, "mutation_id")
        authority = (
            _authority_snapshot(self._missions, mission)
            if _authority_baseline is None else _authority_baseline
        )
        if not isinstance(authority, MissionAuthoritySnapshot) or authority.mission_id != mission:
            raise MissionAuthorityDrift("mission authority baseline is invalid")
        target = self._validate_phase(target_phase, authority.state)
        operation = "reconcile" if reconcile else "transition"
        request_hash = _sha([operation, workspace, mission, target, expected_revision, updates or {}, authority.snapshot_hash])
        try:
            replay = self._control_plane.read_mutation_replay(
                self._owner,
                workspace_id=workspace,
                mission_id=mission,
                mutation_id=mutation,
                operation=operation,
                request_sha256=request_hash,
            )
        except ControlPlaneV4Conflict as exc:
            raise MissionPhaseConflict(str(exc)) from None
        if replay is not None:
            after = _authority_snapshot(self._missions, mission)
            if after != authority:
                raise MissionAuthorityDrift("mission authority changed during mutation replay")
            return self._record(replay[0])
        try:
            prior_bundle = self._control_plane.read_context_bundle(
                self._owner, workspace, mission
            )
            prior = self._record(prior_bundle[0])
        except ControlPlaneV4Conflict as exc:
            raise MissionContextNotFound(str(exc)) from None
        if prior.revision != expected_revision:
            raise MissionPhaseConflict("mission context revision changed")
        required_terminal = TERMINAL_FOR_STATE.get(authority.state)
        if required_terminal is not None and target != required_terminal:
            raise MissionPhaseConflict("terminal mission state can only reconcile to its matching phase")
        if required_terminal is None and target in TERMINAL_PHASES:
            raise MissionPhaseConflict("mission state is not terminal")
        if not reconcile and target not in PHASE_TRANSITIONS_V1[prior.operational_phase]:
            raise MissionPhaseConflict(f"phase transition {prior.operational_phase} -> {target} is not allowed")
        if reconcile and required_terminal != target:
            raise MissionPhaseConflict("terminal reconciliation does not match mission authority")
        spec = prior.spec.with_updates(updates)
        try:
            bundle = self._control_plane.apply_mission_mutation(
                self._owner,
                V4MissionMutation(
                    operation, mutation, request_hash, mission,
                    workspace, prior.correlation_id, target,
                    _canonical(spec.as_payload()), authority.snapshot_hash,
                    authority.event_seq, authority.event_hash, expected_revision, _utc_now(),
                ),
            )
        except ControlPlaneV4Conflict as exc:
            raise MissionPhaseConflict(str(exc)) from None
        after = _authority_snapshot(self._missions, mission)
        if after != authority:
            raise MissionAuthorityDrift("mission authority changed during phase mutation")
        return self._record(bundle[0])


class LegacyMissionContextAdapter:
    """Explicit host-created compatibility adapter; never a generic fallback."""

    def __init__(self, store: MissionContextStore):
        if not isinstance(store, MissionContextStore):
            raise TypeError("store must be MissionContextStore")
        self._store = MissionContextStore(
            store._control_plane,
            store._owner,
            store._missions,
            enabled=store.enabled,
            _legacy_access_token=_LEGACY_ADAPTER_SEAL,
        )

    def initialize_context(
        self,
        mission_id: object,
        spec: MissionContextSpec,
        *,
        operational_phase: object,
        mutation_id: object,
        correlation_id: object | None = None,
    ) -> MissionContextRecord:
        return self._store.initialize_context(
            LEGACY_WORKSPACE_ID,
            mission_id,
            spec,
            operational_phase=operational_phase,
            mutation_id=mutation_id,
            correlation_id=correlation_id,
        )

    def get_context(self, mission_id: object) -> MissionContextRecord:
        return self._store.get_context(LEGACY_WORKSPACE_ID, mission_id)

    def list_events(self, mission_id: object) -> tuple[MissionPhaseEvent, ...]:
        return self._store.list_events(LEGACY_WORKSPACE_ID, mission_id)

    def transition(
        self,
        mission_id: object,
        target_phase: object,
        *,
        expected_revision: int,
        mutation_id: object,
        updates: Mapping[str, object] | None = None,
    ) -> MissionContextRecord:
        return self._store.transition(
            LEGACY_WORKSPACE_ID,
            mission_id,
            target_phase,
            expected_revision=expected_revision,
            mutation_id=mutation_id,
            updates=updates,
        )

    def reconcile_terminal(
        self,
        mission_id: object,
        *,
        expected_revision: int,
        mutation_id: object,
        updates: Mapping[str, object] | None = None,
    ) -> MissionContextRecord:
        return self._store.reconcile_terminal(
            LEGACY_WORKSPACE_ID,
            mission_id,
            expected_revision=expected_revision,
            mutation_id=mutation_id,
            updates=updates,
        )

    def adopt_legacy_context(
        self,
        mission_id: object,
        spec: MissionContextSpec,
        *,
        mutation_id: object,
        reviewed_source_sha256: str,
        correlation_id: object | None = None,
    ) -> MissionContextRecord:
        """Explicitly adopt one reviewed v3 legacy provenance record.

        The adapter never fabricates objective/scope/definition-of-done from the
        sparse v3 backfill row: the trusted caller must provide a validated
        ``MissionContextSpec``.  Only the initial phase is mapped from the live
        public MissionStore state using the documented compatibility table.
        """

        self._store._assert_enabled()
        mission = self._store._id(mission_id, "mission_id")
        row = self._store._control_plane.read_legacy_provenance(
            self._store._owner, mission
        )
        if row is None:
            raise MissionContextNotFound("legacy mission context provenance is unavailable")
        if row["workspace_id"] != LEGACY_WORKSPACE_ID:
            raise MissionContextIsolationError("legacy context provenance is not legacy-default")
        if row["disposition"] != "eligible" or reviewed_source_sha256 != row["source_row_sha256"]:
            raise MissionContextIsolationError("legacy context provenance requires review")
        authority = _authority_snapshot(self._store._missions, mission)
        phase = INITIAL_PHASE_FOR_STATE.get(authority.state)
        if phase is None:
            raise MissionPhaseConflict("legacy mission state cannot be mapped")
        return self._store.initialize_context(
            LEGACY_WORKSPACE_ID, mission, spec, operational_phase=phase,
            mutation_id=mutation_id, correlation_id=correlation_id,
            _legacy_reviewed_source_sha256=reviewed_source_sha256,
            _authority_baseline=authority,
        )


_LEGACY_ADAPTER_SEAL = object()


__all__ = [
    "CONTEXT_CONTRACT",
    "PHASES",
    "PHASE_STATES",
    "PHASE_TRANSITIONS_V1",
    "INITIAL_PHASE_FOR_STATE",
    "LegacyMissionContextAdapter",
    "MissionAuthorityDrift",
    "MissionContextDisabled",
    "MissionContextError",
    "MissionContextInvalid",
    "MissionContextIsolationError",
    "MissionContextNotFound",
    "MissionContextRecord",
    "MissionContextSpec",
    "MissionContextStore",
    "MissionPhaseConflict",
    "MissionPhaseEvent",
]
