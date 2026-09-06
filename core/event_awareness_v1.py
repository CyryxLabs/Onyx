"""Metadata-first, event-driven awareness with zero idle polling.

The service consumes native or connector events supplied by the host.  It does
not capture screens, read clipboards, enumerate processes, start timers, call a
provider, or execute tools.  Its output is a bounded read-only context and
attention projection that other governed services may choose to use.
"""

from __future__ import annotations

import math
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from core.context_graph_v1 import ContextGraphStoreV1
from core.operational_goals_v1 import OperationalGoalStoreV1


_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_KEY = re.compile(r"[a-z][a-z0-9_.-]{2,95}")
_SENSITIVE = frozenset(
    {
        "body",
        "clipboard",
        "content",
        "cookie",
        "credential",
        "image",
        "message",
        "password",
        "screenshot",
        "secret",
        "text",
        "token",
        "transcript",
    }
)


class AwarenessError(RuntimeError):
    pass


class AwarenessContractError(ValueError):
    pass


class AwarenessDenied(PermissionError):
    pass


class AwarenessQueueFull(AwarenessError):
    pass


class SignalKindV1(str, Enum):
    FOREGROUND_CHANGED = "foreground.changed"
    WORKSPACE_CHANGED = "workspace.changed"
    CALENDAR_ATTENTION = "calendar.attention"
    MAIL_ATTENTION = "mail.attention"
    MISSION_STATE = "mission.state"
    CONNECTIVITY_CHANGED = "connectivity.changed"
    OWNER_ACTIVITY = "owner.activity"


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise AwarenessContractError(f"{label} is invalid")
    return value


def _metadata(value: Mapping[str, object] | None) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if type(value) is not dict or len(value) > 20:
        raise AwarenessContractError("metadata must be a bounded plain mapping")
    output: list[tuple[str, str]] = []
    for key, raw in sorted(value.items()):
        if type(key) is not str or _KEY.fullmatch(key) is None:
            raise AwarenessContractError("metadata key is invalid")
        parts = set(key.replace("-", ".").replace("_", ".").split("."))
        if parts & _SENSITIVE:
            raise AwarenessDenied("awareness metadata may not contain captured content")
        if type(raw) not in {str, int, float, bool}:
            raise AwarenessContractError("metadata values must be scalar")
        if isinstance(raw, float) and not math.isfinite(raw):
            raise AwarenessContractError("metadata number is not finite")
        rendered = str(raw).lower() if type(raw) is bool else str(raw)
        if not rendered or len(rendered) > 192 or "\x00" in rendered:
            raise AwarenessContractError("metadata value is invalid")
        output.append((key, rendered))
    return tuple(output)


@dataclass(frozen=True)
class AwarenessSignalV1:
    signal_id: str
    kind: SignalKindV1
    source_id: str
    owner_profile_id: str
    workspace_id: str
    occurred_at: float
    metadata: tuple[tuple[str, str], ...]
    coalesce_key: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.signal_id, "signal_id")
        if type(self.kind) is not SignalKindV1:
            raise AwarenessContractError("kind must be an exact SignalKindV1")
        _identifier(self.source_id, "source_id")
        _identifier(self.owner_profile_id, "owner_profile_id")
        _identifier(self.workspace_id, "workspace_id")
        if (
            isinstance(self.occurred_at, bool)
            or not isinstance(self.occurred_at, (int, float))
            or not math.isfinite(self.occurred_at)
            or self.occurred_at <= 0
        ):
            raise AwarenessContractError("occurred_at is invalid")
        if type(self.metadata) is not tuple or self.metadata != _metadata(dict(self.metadata)):
            raise AwarenessContractError("metadata is not canonical")
        if self.coalesce_key is not None:
            _identifier(self.coalesce_key, "coalesce_key")

    @classmethod
    def create(
        cls,
        *,
        kind: SignalKindV1,
        source_id: str,
        owner_profile_id: str,
        workspace_id: str,
        metadata: Mapping[str, object] | None = None,
        coalesce_key: str | None = None,
        occurred_at: float | None = None,
    ) -> "AwarenessSignalV1":
        return cls(
            "sig_" + uuid.uuid4().hex,
            kind,
            _identifier(source_id, "source_id"),
            _identifier(owner_profile_id, "owner_profile_id"),
            _identifier(workspace_id, "workspace_id"),
            time.time() if occurred_at is None else float(occurred_at),
            _metadata(metadata),
            _identifier(coalesce_key, "coalesce_key")
            if coalesce_key is not None
            else None,
        )


@dataclass(frozen=True)
class AwarenessPolicyV1:
    allowed_sources: tuple[str, ...]
    max_queue: int = 256
    max_history: int = 2_048
    max_events_per_minute: int = 120
    max_clock_skew_seconds: float = 300.0
    retention_seconds: float = 14_400.0
    context_switch_threshold: int = 12

    def __post_init__(self) -> None:
        if type(self.allowed_sources) is not tuple or not self.allowed_sources:
            raise AwarenessContractError("allowed_sources is invalid")
        normalized = tuple(_identifier(item, "allowed source") for item in self.allowed_sources)
        if normalized != self.allowed_sources or len(set(normalized)) != len(normalized):
            raise AwarenessContractError("allowed_sources is not canonical")
        for value, label, low, high in (
            (self.max_queue, "max_queue", 1, 4_096),
            (self.max_history, "max_history", 1, 50_000),
            (self.max_events_per_minute, "max_events_per_minute", 1, 10_000),
            (self.context_switch_threshold, "context_switch_threshold", 2, 1_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise AwarenessContractError(f"{label} is invalid")
        for value, label, low, high in (
            (self.max_clock_skew_seconds, "max_clock_skew_seconds", 0.0, 3_600.0),
            (self.retention_seconds, "retention_seconds", 1.0, 604_800.0),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise AwarenessContractError(f"{label} is invalid")


@dataclass(frozen=True)
class AwarenessProjectionV1:
    owner_profile_id: str
    workspace_id: str
    active_application_id: str | None
    active_project_id: str | None
    recent_signal_count: int
    context_switches: int
    attention: tuple[str, ...]
    generated_at: float


class EventDrivenAwarenessV1:
    """Explicit publish/drain awareness; no background work exists."""

    def __init__(
        self,
        policy: AwarenessPolicyV1,
        *,
        goal_store: OperationalGoalStoreV1 | None = None,
        context_graph: ContextGraphStoreV1 | None = None,
    ) -> None:
        if type(policy) is not AwarenessPolicyV1:
            raise AwarenessContractError("exact AwarenessPolicyV1 is required")
        if goal_store is not None and type(goal_store) is not OperationalGoalStoreV1:
            raise AwarenessContractError("goal_store type is invalid")
        if context_graph is not None and type(context_graph) is not ContextGraphStoreV1:
            raise AwarenessContractError("context_graph type is invalid")
        self._policy = policy
        self._goals = goal_store
        self._context_graph = context_graph
        self._queue: deque[AwarenessSignalV1] = deque()
        self._history: deque[AwarenessSignalV1] = deque(maxlen=policy.max_history)
        self._queued_coalesce: dict[tuple[str, str, str], int] = {}
        self._recent_ids: deque[str] = deque(maxlen=policy.max_history)
        self._recent_id_set: set[str] = set()
        self._admission_times: deque[float] = deque()
        self._lock = threading.RLock()

    @property
    def queued(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def background_workers(self) -> int:
        return 0

    @property
    def polling_interval(self) -> None:
        return None

    def _forget_old_admissions(self, now: float) -> None:
        cutoff = now - 60.0
        while self._admission_times and self._admission_times[0] < cutoff:
            self._admission_times.popleft()

    def publish(self, signal: AwarenessSignalV1, *, now: float | None = None) -> bool:
        if type(signal) is not AwarenessSignalV1:
            raise AwarenessContractError("exact AwarenessSignalV1 is required")
        current = time.time() if now is None else float(now)
        if signal.source_id not in self._policy.allowed_sources:
            raise AwarenessDenied("awareness source is not host-allowlisted")
        if abs(signal.occurred_at - current) > self._policy.max_clock_skew_seconds:
            raise AwarenessDenied("awareness signal is outside the replay window")
        with self._lock:
            if signal.signal_id in self._recent_id_set:
                return False
            self._forget_old_admissions(current)
            if len(self._admission_times) >= self._policy.max_events_per_minute:
                raise AwarenessDenied("awareness event-rate budget is exhausted")
            key = (
                signal.owner_profile_id,
                signal.workspace_id,
                signal.coalesce_key,
            ) if signal.coalesce_key is not None else None
            if key is not None and key in self._queued_coalesce:
                index = self._queued_coalesce[key]
                self._queue[index] = signal
                self._remember_id(signal.signal_id)
                self._admission_times.append(current)
                return False
            if len(self._queue) >= self._policy.max_queue:
                raise AwarenessQueueFull("awareness queue is full")
            self._queue.append(signal)
            if key is not None:
                self._queued_coalesce[key] = len(self._queue) - 1
            self._remember_id(signal.signal_id)
            self._admission_times.append(current)
            return True

    def _remember_id(self, signal_id: str) -> None:
        if len(self._recent_ids) == self._recent_ids.maxlen and self._recent_ids:
            self._recent_id_set.discard(self._recent_ids[0])
        self._recent_ids.append(signal_id)
        self._recent_id_set.add(signal_id)

    def drain(self, *, maximum: int = 64, now: float | None = None) -> int:
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 4_096:
            raise AwarenessContractError("maximum is invalid")
        current = time.time() if now is None else float(now)
        moved = 0
        admitted: list[AwarenessSignalV1] = []
        with self._lock:
            while self._queue and moved < maximum:
                signal = self._queue.popleft()
                if current - signal.occurred_at <= self._policy.retention_seconds:
                    self._history.append(signal)
                    admitted.append(signal)
                moved += 1
            self._reindex_coalesce()
            self._trim_history(current)
        if self._context_graph is not None:
            for signal in admitted:
                self._context_graph.observe(
                    signal_kind=signal.kind.value,
                    owner_profile_id=signal.owner_profile_id,
                    workspace_id=signal.workspace_id,
                    occurred_at=signal.occurred_at,
                    metadata=dict(signal.metadata),
                )
        return moved

    def _reindex_coalesce(self) -> None:
        self._queued_coalesce.clear()
        for index, signal in enumerate(self._queue):
            if signal.coalesce_key is not None:
                self._queued_coalesce[
                    (
                        signal.owner_profile_id,
                        signal.workspace_id,
                        signal.coalesce_key,
                    )
                ] = index

    def _trim_history(self, now: float) -> None:
        cutoff = now - self._policy.retention_seconds
        while self._history and self._history[0].occurred_at < cutoff:
            self._history.popleft()

    def projection(
        self,
        *,
        owner_profile_id: str,
        workspace_id: str,
        now: float | None = None,
    ) -> AwarenessProjectionV1:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        current = time.time() if now is None else float(now)
        with self._lock:
            self._trim_history(current)
            signals = tuple(
                item
                for item in self._history
                if item.owner_profile_id == owner and item.workspace_id == workspace
            )
        active_application: str | None = None
        active_project: str | None = None
        foreground_sequence: list[str] = []
        attention: list[str] = []
        for signal in signals:
            metadata = dict(signal.metadata)
            if signal.kind is SignalKindV1.FOREGROUND_CHANGED:
                application = metadata.get("application_id")
                if application is not None:
                    active_application = application
                    if not foreground_sequence or foreground_sequence[-1] != application:
                        foreground_sequence.append(application)
            if signal.kind is SignalKindV1.WORKSPACE_CHANGED:
                project = metadata.get("project_id")
                if project is not None:
                    active_project = project
            if signal.kind is SignalKindV1.CALENDAR_ATTENTION:
                attention.append("calendar_attention")
            if signal.kind is SignalKindV1.MAIL_ATTENTION:
                attention.append("mail_attention")
            if signal.kind is SignalKindV1.CONNECTIVITY_CHANGED and metadata.get("state") == "offline":
                attention.append("connectivity_offline")
        switches = max(0, len(foreground_sequence) - 1)
        if switches >= self._policy.context_switch_threshold:
            attention.append("high_context_switching")
        if self._goals is not None:
            goals = self._goals.attention_queue(
                owner_profile_id=owner, workspace_id=workspace, now=current
            )
            if any(item.health == "overdue" for item in goals):
                attention.append("overdue_goals")
            if any(item.health == "paused" for item in goals):
                attention.append("paused_goals")
        return AwarenessProjectionV1(
            owner,
            workspace,
            active_application,
            active_project,
            len(signals),
            switches,
            tuple(dict.fromkeys(attention)),
            current,
        )

    def recent_signals(
        self, *, owner_profile_id: str, workspace_id: str
    ) -> tuple[AwarenessSignalV1, ...]:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        with self._lock:
            return tuple(
                item
                for item in self._history
                if item.owner_profile_id == owner and item.workspace_id == workspace
            )
