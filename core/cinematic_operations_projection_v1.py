"""Typed, bounded UI projection for the optional Cinematic Operations HUD V1.

The projection is deliberately a presentation boundary.  It accepts complete
snapshots from a trusted host, exposes only allowlisted display fields to QML,
and turns UI intent into validated proposal/selection/navigation signals.  It
does not import or call an executor, provider, network client, file API, or the
live Onyx shell.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from PySide6.QtCore import QObject

from core.qt_compat import pyqtProperty, pyqtSignal, pyqtSlot


_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{1,95}")
_PAGES = frozenset({"goals", "workflow", "devices", "sites", "agents", "analytics"})
_NODE_KINDS = frozenset({"trigger", "condition", "transform", "plan", "output"})
_STATUSES = frozenset(
    {
        "ready",
        "active",
        "attention",
        "blocked",
        "complete",
        "draft",
        "offline",
        "online",
        "paused",
        "pending",
        "review",
        "running",
        "stable",
    }
)
_CALLBACKS = frozenset({"navigate", "proposal", "selection"})
_LIMITS = {
    "goals": 24,
    "workflow_nodes": 32,
    "workflow_edges": 64,
    "devices": 24,
    "sites": 16,
    "site_files": 96,
    "agents": 32,
    "inbox": 32,
    "events": 100,
}


class CinematicOperationsProjectionError(ValueError):
    """Raised when presentation data or intent is outside the HUD contract."""


def _mapping(
    value: object, *, fields: frozenset[str], label: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CinematicOperationsProjectionError(f"{label} shape is invalid")
    return value


def _text(value: object, *, label: str, maximum: int, empty: bool = False) -> str:
    if type(value) is not str:
        raise CinematicOperationsProjectionError(f"{label} is invalid")
    result = " ".join(value.split())
    if (not empty and not result) or len(result) > maximum:
        raise CinematicOperationsProjectionError(f"{label} is invalid")
    if any(ord(char) < 32 for char in result):
        raise CinematicOperationsProjectionError(f"{label} is invalid")
    return result


def _identifier(value: object, *, label: str) -> str:
    text = _text(value, label=label, maximum=96)
    if _IDENTIFIER.fullmatch(text) is None:
        raise CinematicOperationsProjectionError(f"{label} is invalid")
    return text


def _status(value: object) -> str:
    result = _text(value, label="status", maximum=16).lower()
    if result not in _STATUSES:
        raise CinematicOperationsProjectionError("status is invalid")
    return result


def _progress(value: object) -> float:
    if type(value) not in {int, float}:
        raise CinematicOperationsProjectionError("progress is invalid")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise CinematicOperationsProjectionError("progress is invalid")
    return result


def _records(
    value: object, *, label: str, limit: int
) -> Sequence[Mapping[str, object]]:
    if type(value) not in {tuple, list} or len(value) > limit:
        raise CinematicOperationsProjectionError(f"{label} collection is invalid")
    if any(not isinstance(item, Mapping) for item in value):
        raise CinematicOperationsProjectionError(f"{label} collection is invalid")
    return value


@dataclass(frozen=True, slots=True)
class _Record:
    fields: ClassVar[frozenset[str]]

    def qml(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.fields}


@dataclass(frozen=True, slots=True)
class GoalProjectionV1(_Record):
    fields: ClassVar[frozenset[str]] = frozenset(
        {"goal_id", "title", "detail", "status", "priority", "due_label", "progress"}
    )
    goal_id: str
    title: str
    detail: str
    status: str
    priority: str
    due_label: str
    progress: float

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> "GoalProjectionV1":
        item = _mapping(value, fields=cls.fields, label="goal")
        priority = _text(item["priority"], label="priority", maximum=12).lower()
        if priority not in {"critical", "high", "normal", "low"}:
            raise CinematicOperationsProjectionError("priority is invalid")
        return cls(
            _identifier(item["goal_id"], label="goal_id"),
            _text(item["title"], label="goal title", maximum=120),
            _text(item["detail"], label="goal detail", maximum=240, empty=True),
            _status(item["status"]),
            priority,
            _text(item["due_label"], label="due label", maximum=48, empty=True),
            _progress(item["progress"]),
        )


@dataclass(frozen=True, slots=True)
class WorkflowNodeProjectionV1(_Record):
    fields: ClassVar[frozenset[str]] = frozenset(
        {"node_id", "workflow_id", "label", "kind", "status"}
    )
    node_id: str
    workflow_id: str
    label: str
    kind: str
    status: str

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> "WorkflowNodeProjectionV1":
        item = _mapping(value, fields=cls.fields, label="workflow node")
        kind = _text(item["kind"], label="workflow kind", maximum=16).lower()
        if kind not in _NODE_KINDS:
            raise CinematicOperationsProjectionError("workflow kind is invalid")
        return cls(
            _identifier(item["node_id"], label="node_id"),
            _identifier(item["workflow_id"], label="workflow_id"),
            _text(item["label"], label="workflow label", maximum=96),
            kind,
            _status(item["status"]),
        )


@dataclass(frozen=True, slots=True)
class WorkflowEdgeProjectionV1(_Record):
    fields: ClassVar[frozenset[str]] = frozenset(
        {"edge_id", "workflow_id", "source", "target", "route"}
    )
    edge_id: str
    workflow_id: str
    source: str
    target: str
    route: str

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> "WorkflowEdgeProjectionV1":
        item = _mapping(value, fields=cls.fields, label="workflow edge")
        route = _text(item["route"], label="workflow route", maximum=8).lower()
        if route not in {"next", "true", "false"}:
            raise CinematicOperationsProjectionError("workflow route is invalid")
        return cls(
            _identifier(item["edge_id"], label="edge_id"),
            _identifier(item["workflow_id"], label="workflow_id"),
            _identifier(item["source"], label="source"),
            _identifier(item["target"], label="target"),
            route,
        )


@dataclass(frozen=True, slots=True)
class DeviceProjectionV1(_Record):
    fields: ClassVar[frozenset[str]] = frozenset(
        {"device_id", "name", "platform", "status", "trust", "last_seen"}
    )
    device_id: str
    name: str
    platform: str
    status: str
    trust: str
    last_seen: str

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> "DeviceProjectionV1":
        item = _mapping(value, fields=cls.fields, label="device")
        trust = _text(item["trust"], label="device trust", maximum=16).lower()
        if trust not in {"bound", "pending", "revoked", "unknown"}:
            raise CinematicOperationsProjectionError("device trust is invalid")
        return cls(
            _identifier(item["device_id"], label="device_id"),
            _text(item["name"], label="device name", maximum=80),
            _text(item["platform"], label="device platform", maximum=24),
            _status(item["status"]),
            trust,
            _text(item["last_seen"], label="last seen", maximum=48),
        )


@dataclass(frozen=True, slots=True)
class SiteProjectionV1(_Record):
    fields: ClassVar[frozenset[str]] = frozenset(
        {"site_id", "name", "branch", "status", "preview_state", "updated_label"}
    )
    site_id: str
    name: str
    branch: str
    status: str
    preview_state: str
    updated_label: str

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> "SiteProjectionV1":
        item = _mapping(value, fields=cls.fields, label="site")
        return cls(
            _identifier(item["site_id"], label="site_id"),
            _text(item["name"], label="site name", maximum=80),
            _text(item["branch"], label="site branch", maximum=80),
            _status(item["status"]),
            _text(item["preview_state"], label="preview state", maximum=32),
            _text(item["updated_label"], label="updated label", maximum=48),
        )


@dataclass(frozen=True, slots=True)
class SiteFileProjectionV1(_Record):
    fields: ClassVar[frozenset[str]] = frozenset(
        {"file_id", "site_id", "name", "kind", "state", "depth"}
    )
    file_id: str
    site_id: str
    name: str
    kind: str
    state: str
    depth: int

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> "SiteFileProjectionV1":
        item = _mapping(value, fields=cls.fields, label="site file")
        kind = _text(item["kind"], label="site file kind", maximum=8).lower()
        if kind not in {"file", "folder"}:
            raise CinematicOperationsProjectionError("site file kind is invalid")
        state = _text(item["state"], label="site file state", maximum=12).lower()
        if state not in {"added", "clean", "modified", "removed", "untracked"}:
            raise CinematicOperationsProjectionError("site file state is invalid")
        depth = item["depth"]
        if type(depth) is not int or not 0 <= depth <= 8:
            raise CinematicOperationsProjectionError("site file depth is invalid")
        name = _text(item["name"], label="site file name", maximum=96)
        if name in {".", ".."} or any(
            separator in name for separator in ("/", "\\", ":")
        ):
            raise CinematicOperationsProjectionError("site file name is invalid")
        return cls(
            _identifier(item["file_id"], label="file_id"),
            _identifier(item["site_id"], label="site_id"),
            name,
            kind,
            state,
            depth,
        )


@dataclass(frozen=True, slots=True)
class AgentProjectionV1(_Record):
    fields: ClassVar[frozenset[str]] = frozenset(
        {"agent_id", "name", "role", "status", "task", "load_label"}
    )
    agent_id: str
    name: str
    role: str
    status: str
    task: str
    load_label: str

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> "AgentProjectionV1":
        item = _mapping(value, fields=cls.fields, label="agent")
        return cls(
            _identifier(item["agent_id"], label="agent_id"),
            _text(item["name"], label="agent name", maximum=64),
            _text(item["role"], label="agent role", maximum=64),
            _status(item["status"]),
            _text(item["task"], label="agent task", maximum=160, empty=True),
            _text(item["load_label"], label="load label", maximum=32),
        )


@dataclass(frozen=True, slots=True)
class InboxProjectionV1(_Record):
    fields: ClassVar[frozenset[str]] = frozenset(
        {"inbox_id", "title", "source", "status", "age_label"}
    )
    inbox_id: str
    title: str
    source: str
    status: str
    age_label: str

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> "InboxProjectionV1":
        item = _mapping(value, fields=cls.fields, label="inbox item")
        return cls(
            _identifier(item["inbox_id"], label="inbox_id"),
            _text(item["title"], label="inbox title", maximum=120),
            _text(item["source"], label="inbox source", maximum=48),
            _status(item["status"]),
            _text(item["age_label"], label="inbox age", maximum=32),
        )


@dataclass(frozen=True, slots=True)
class EventProjectionV1(_Record):
    fields: ClassVar[frozenset[str]] = frozenset(
        {"event_id", "title", "detail", "category", "status", "time_label"}
    )
    event_id: str
    title: str
    detail: str
    category: str
    status: str
    time_label: str

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> "EventProjectionV1":
        item = _mapping(value, fields=cls.fields, label="event")
        category = _text(item["category"], label="event category", maximum=24).lower()
        if category not in {"agent", "device", "goal", "site", "system", "workflow"}:
            raise CinematicOperationsProjectionError("event category is invalid")
        return cls(
            _identifier(item["event_id"], label="event_id"),
            _text(item["title"], label="event title", maximum=120),
            _text(item["detail"], label="event detail", maximum=240, empty=True),
            category,
            _status(item["status"]),
            _text(item["time_label"], label="event time", maximum=48),
        )


_SNAPSHOT_FIELDS = frozenset(
    {
        "status_label",
        "goals",
        "workflow_nodes",
        "workflow_edges",
        "devices",
        "sites",
        "site_files",
        "agents",
        "inbox",
        "events",
    }
)


@dataclass(frozen=True, slots=True)
class CinematicOperationsSnapshotV1:
    status_label: str
    goals: tuple[GoalProjectionV1, ...]
    workflow_nodes: tuple[WorkflowNodeProjectionV1, ...]
    workflow_edges: tuple[WorkflowEdgeProjectionV1, ...]
    devices: tuple[DeviceProjectionV1, ...]
    sites: tuple[SiteProjectionV1, ...]
    site_files: tuple[SiteFileProjectionV1, ...]
    agents: tuple[AgentProjectionV1, ...]
    inbox: tuple[InboxProjectionV1, ...]
    events: tuple[EventProjectionV1, ...]

    @classmethod
    def empty(cls) -> "CinematicOperationsSnapshotV1":
        return cls("STANDBY", (), (), (), (), (), (), (), (), ())

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> "CinematicOperationsSnapshotV1":
        item = _mapping(value, fields=_SNAPSHOT_FIELDS, label="operations snapshot")

        def parsed(name: str, record_type: type[_Record]) -> tuple[_Record, ...]:
            values = _records(item[name], label=name, limit=_LIMITS[name])
            return tuple(record_type.parse(record) for record in values)  # type: ignore[attr-defined]

        return cls(
            _text(item["status_label"], label="status label", maximum=32),
            parsed("goals", GoalProjectionV1),  # type: ignore[arg-type]
            parsed("workflow_nodes", WorkflowNodeProjectionV1),  # type: ignore[arg-type]
            parsed("workflow_edges", WorkflowEdgeProjectionV1),  # type: ignore[arg-type]
            parsed("devices", DeviceProjectionV1),  # type: ignore[arg-type]
            parsed("sites", SiteProjectionV1),  # type: ignore[arg-type]
            parsed("site_files", SiteFileProjectionV1),  # type: ignore[arg-type]
            parsed("agents", AgentProjectionV1),  # type: ignore[arg-type]
            parsed("inbox", InboxProjectionV1),  # type: ignore[arg-type]
            parsed("events", EventProjectionV1),  # type: ignore[arg-type]
        )


class CinematicOperationsProjectionV1(QObject):
    """Default-off, read-mostly QML projection with proposal-only intent."""

    dataChanged = pyqtSignal()
    policyChanged = pyqtSignal()
    navigationChanged = pyqtSignal()
    callbackErrorChanged = pyqtSignal()
    navigationRequested = pyqtSignal(str)
    selectionRequested = pyqtSignal(str, str)
    proposalRequested = pyqtSignal(str, "QVariantMap")

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        enabled: bool = False,
        reduced_motion: bool = False,
        callbacks: Mapping[str, Callable[..., object]] | None = None,
        snapshot: CinematicOperationsSnapshotV1 | None = None,
    ) -> None:
        super().__init__(parent)
        supplied = dict(callbacks or {})
        unknown = supplied.keys() - _CALLBACKS
        if unknown:
            raise CinematicOperationsProjectionError(
                f"unknown HUD callback(s): {', '.join(sorted(unknown))}"
            )
        if any(not callable(callback) for callback in supplied.values()):
            raise CinematicOperationsProjectionError("HUD callbacks must be callable")
        self._callbacks = supplied
        self._enabled = bool(enabled)
        self._reduced_motion = bool(reduced_motion)
        self._active_page = "goals"
        self._callback_error = ""
        self._snapshot = snapshot or CinematicOperationsSnapshotV1.empty()

    @pyqtProperty(bool, notify=policyChanged)
    def enabled(self) -> bool:
        return self._enabled

    @pyqtProperty(bool, notify=policyChanged)
    def reducedMotion(self) -> bool:  # noqa: N802
        return self._reduced_motion

    @pyqtProperty(str, notify=navigationChanged)
    def activePage(self) -> str:  # noqa: N802
        return self._active_page

    @pyqtProperty(str, notify=dataChanged)
    def statusLabel(self) -> str:  # noqa: N802
        return self._snapshot.status_label

    @pyqtProperty("QVariantList", notify=dataChanged)
    def goals(self) -> list[dict[str, object]]:
        return [item.qml() for item in self._snapshot.goals]

    @pyqtProperty("QVariantList", notify=dataChanged)
    def workflowNodes(self) -> list[dict[str, object]]:  # noqa: N802
        return [item.qml() for item in self._snapshot.workflow_nodes]

    @pyqtProperty("QVariantList", notify=dataChanged)
    def workflowEdges(self) -> list[dict[str, object]]:  # noqa: N802
        return [item.qml() for item in self._snapshot.workflow_edges]

    @pyqtProperty("QVariantList", notify=dataChanged)
    def devices(self) -> list[dict[str, object]]:
        return [item.qml() for item in self._snapshot.devices]

    @pyqtProperty("QVariantList", notify=dataChanged)
    def sites(self) -> list[dict[str, object]]:
        return [item.qml() for item in self._snapshot.sites]

    @pyqtProperty("QVariantList", notify=dataChanged)
    def siteFiles(self) -> list[dict[str, object]]:  # noqa: N802
        return [item.qml() for item in self._snapshot.site_files]

    @pyqtProperty("QVariantList", notify=dataChanged)
    def agents(self) -> list[dict[str, object]]:
        return [item.qml() for item in self._snapshot.agents]

    @pyqtProperty("QVariantList", notify=dataChanged)
    def inbox(self) -> list[dict[str, object]]:
        return [item.qml() for item in self._snapshot.inbox]

    @pyqtProperty("QVariantList", notify=dataChanged)
    def events(self) -> list[dict[str, object]]:
        return [item.qml() for item in self._snapshot.events]

    @pyqtProperty("QVariantList", constant=True)
    def safeNodeCatalog(self) -> list[dict[str, str]]:  # noqa: N802
        labels = {
            "trigger": "TRIGGER",
            "condition": "CONDITION",
            "transform": "SAFE TRANSFORM",
            "plan": "GOVERNED PLAN",
            "output": "VERIFIED OUTPUT",
        }
        return [{"kind": kind, "label": labels[kind]} for kind in sorted(_NODE_KINDS)]

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def metrics(self) -> dict[str, int]:
        return {
            "active_goals": sum(
                item.status == "active" for item in self._snapshot.goals
            ),
            "workflows": len(
                {item.workflow_id for item in self._snapshot.workflow_nodes}
            ),
            "online_devices": sum(
                item.status == "online" for item in self._snapshot.devices
            ),
            "active_agents": sum(
                item.status in {"active", "running"} for item in self._snapshot.agents
            ),
            "events_today": len(self._snapshot.events),
        }

    @pyqtProperty(str, notify=callbackErrorChanged)
    def lastCallbackError(self) -> str:  # noqa: N802
        return self._callback_error

    def set_snapshot(
        self, snapshot: Mapping[str, object] | CinematicOperationsSnapshotV1
    ) -> None:
        candidate = (
            snapshot
            if isinstance(snapshot, CinematicOperationsSnapshotV1)
            else CinematicOperationsSnapshotV1.parse(snapshot)
        )
        if candidate != self._snapshot:
            self._snapshot = candidate
            self.dataChanged.emit()

    @pyqtSlot("QVariantMap", result=bool)
    def setSnapshot(self, snapshot: Mapping[str, object]) -> bool:  # noqa: N802
        try:
            self.set_snapshot(snapshot)
        except CinematicOperationsProjectionError:
            return False
        return True

    def set_enabled(self, enabled: bool) -> None:
        value = bool(enabled)
        if value != self._enabled:
            self._enabled = value
            self.policyChanged.emit()

    def set_reduced_motion(self, reduced: bool) -> None:
        value = bool(reduced)
        if value != self._reduced_motion:
            self._reduced_motion = value
            self.policyChanged.emit()

    @pyqtSlot(bool)
    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        self.set_enabled(enabled)

    @pyqtSlot(bool)
    def setReducedMotion(self, reduced: bool) -> None:  # noqa: N802
        self.set_reduced_motion(reduced)

    def _callback(self, name: str, *args: object) -> None:
        callback = self._callbacks.get(name)
        if callback is None:
            return
        try:
            callback(*args)
        except Exception as exc:
            error = f"{name}: {type(exc).__name__}"
            if error != self._callback_error:
                self._callback_error = error
                self.callbackErrorChanged.emit()

    @pyqtSlot(str, result=bool)
    def requestNavigation(self, page: str) -> bool:  # noqa: N802
        if not self._enabled or page not in _PAGES:
            return False
        if page != self._active_page:
            self._active_page = page
            self.navigationChanged.emit()
        self.navigationRequested.emit(page)
        self._callback("navigate", page)
        return True

    @pyqtSlot(str, str, result=bool)
    def requestSelection(self, surface: str, item_id: str) -> bool:  # noqa: N802
        if not self._enabled or surface not in _PAGES:
            return False
        try:
            identifier = _identifier(item_id, label="selection ID")
        except CinematicOperationsProjectionError:
            return False
        self.selectionRequested.emit(surface, identifier)
        self._callback("selection", surface, identifier)
        return True

    @staticmethod
    def _proposal(kind: object, value: object) -> tuple[str, dict[str, str]]:
        proposal_kind = _text(kind, label="proposal kind", maximum=32)
        if not isinstance(value, Mapping):
            raise CinematicOperationsProjectionError("proposal payload is invalid")
        single_id = {
            "goal_focus": "goal_id",
            "device_inspect": "device_id",
            "site_preview": "site_id",
            "inbox_open": "inbox_id",
        }
        if proposal_kind in single_id:
            key = single_id[proposal_kind]
            payload = _mapping(value, fields=frozenset({key}), label="proposal")
            return proposal_kind, {key: _identifier(payload[key], label=key)}
        if proposal_kind == "workflow_node_add":
            payload = _mapping(
                value,
                fields=frozenset({"workflow_id", "kind", "label"}),
                label="workflow node proposal",
            )
            node_kind = _text(payload["kind"], label="workflow kind", maximum=16)
            if node_kind not in _NODE_KINDS:
                raise CinematicOperationsProjectionError("workflow kind is invalid")
            return proposal_kind, {
                "workflow_id": _identifier(payload["workflow_id"], label="workflow_id"),
                "kind": node_kind,
                "label": _text(payload["label"], label="workflow label", maximum=96),
            }
        if proposal_kind == "workflow_connect":
            payload = _mapping(
                value,
                fields=frozenset({"workflow_id", "source", "target", "route"}),
                label="workflow connection proposal",
            )
            route = _text(payload["route"], label="workflow route", maximum=8)
            if route not in {"next", "true", "false"}:
                raise CinematicOperationsProjectionError("workflow route is invalid")
            source = _identifier(payload["source"], label="source")
            target = _identifier(payload["target"], label="target")
            if source == target:
                raise CinematicOperationsProjectionError(
                    "workflow endpoints are invalid"
                )
            return proposal_kind, {
                "workflow_id": _identifier(payload["workflow_id"], label="workflow_id"),
                "source": source,
                "target": target,
                "route": route,
            }
        if proposal_kind == "agent_delegate":
            payload = _mapping(
                value,
                fields=frozenset({"agent_id", "inbox_id"}),
                label="delegation proposal",
            )
            return proposal_kind, {
                "agent_id": _identifier(payload["agent_id"], label="agent_id"),
                "inbox_id": _identifier(payload["inbox_id"], label="inbox_id"),
            }
        if proposal_kind == "analytics_filter":
            payload = _mapping(
                value, fields=frozenset({"category"}), label="filter proposal"
            )
            category = _text(payload["category"], label="category", maximum=24)
            if category not in {
                "all",
                "agent",
                "device",
                "goal",
                "site",
                "system",
                "workflow",
            }:
                raise CinematicOperationsProjectionError("category is invalid")
            return proposal_kind, {"category": category}
        raise CinematicOperationsProjectionError("proposal kind is invalid")

    @pyqtSlot(str, "QVariantMap", result=bool)
    def requestProposal(self, kind: str, payload: Mapping[str, object]) -> bool:  # noqa: N802
        if not self._enabled:
            return False
        try:
            proposal_kind, safe_payload = self._proposal(kind, payload)
        except CinematicOperationsProjectionError:
            return False
        self.proposalRequested.emit(proposal_kind, safe_payload)
        self._callback("proposal", proposal_kind, dict(safe_payload))
        return True


__all__ = [
    "AgentProjectionV1",
    "CinematicOperationsProjectionError",
    "CinematicOperationsProjectionV1",
    "CinematicOperationsSnapshotV1",
    "DeviceProjectionV1",
    "EventProjectionV1",
    "GoalProjectionV1",
    "InboxProjectionV1",
    "SiteProjectionV1",
    "SiteFileProjectionV1",
    "WorkflowEdgeProjectionV1",
    "WorkflowNodeProjectionV1",
]
