"""Qt-native workspace event publication with zero idle polling.

The publisher is an opt-in host binding.  It observes only explicitly supplied
paths through ``QFileSystemWatcher`` (or an exact-compatible injected watcher),
normalizes metadata through the existing workspace adapter, and publishes to
the already-owned automation and awareness queues.  It never reads file
contents, creates a worker, starts a timer, or drains either queue.
"""

from __future__ import annotations

import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from core.automation_adapters_v1 import WorkspaceFileEventAdapterV1
from core.event_awareness_v1 import AwarenessSignalV1, EventDrivenAwarenessV1, SignalKindV1
from core.governed_automation_v1 import EventDrivenAutomationRuntimeV1


FEATURE_FLAG = "ONYX_NATIVE_WORKSPACE_EVENTS_V1"
_MAX_ROOTS = 16
_MAX_WATCHED_PATHS = 128
_MAX_DIRECTORY_ENTRIES = 4_096


class NativeWorkspaceEventError(RuntimeError):
    pass


class NativeWorkspaceEventContractError(ValueError):
    pass


class NativeWorkspaceEventDenied(PermissionError):
    pass


class _SignalV1(Protocol):
    def connect(self, callback: Callable[[str], None]) -> object: ...

    def disconnect(self, callback: Callable[[str], None]) -> object: ...


class _FileSystemWatcherV1(Protocol):
    directoryChanged: _SignalV1
    fileChanged: _SignalV1

    def addPaths(self, paths: list[str]) -> list[str]: ...  # noqa: N802

    def removePaths(self, paths: list[str]) -> list[str]: ...  # noqa: N802


@dataclass(frozen=True)
class NativeWorkspaceEventFeatureGateV1:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise NativeWorkspaceEventContractError("enabled must be an exact bool")


@dataclass(frozen=True)
class NativeWorkspaceEventStatusV1:
    active: bool
    watched_paths: int
    published_events: int
    coalesced_automation_events: int
    denied_events: int
    callback_errors: int
    background_workers: int = 0
    polling_interval: None = None


def _real_path(value: Path | str, *, directory: bool | None = None) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute() or candidate.is_symlink():
        raise NativeWorkspaceEventDenied("watched paths must be real and absolute")
    try:
        resolved = candidate.resolve(strict=True)
        info = resolved.lstat()
    except OSError as exc:
        raise NativeWorkspaceEventDenied("watched path is unavailable") from exc
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(info, "st_file_attributes", 0) & reparse:
        raise NativeWorkspaceEventDenied("reparse points may not be watched")
    if directory is True and not resolved.is_dir():
        raise NativeWorkspaceEventDenied("workspace roots must be directories")
    if directory is False and not resolved.is_file():
        raise NativeWorkspaceEventDenied("watched file is invalid")
    return resolved


def _bounded_children(directory: Path) -> frozenset[Path]:
    try:
        children: list[Path] = []
        for index, child in enumerate(directory.iterdir()):
            if index >= _MAX_DIRECTORY_ENTRIES:
                raise NativeWorkspaceEventDenied("watched directory exceeds its entry budget")
            if child.is_symlink():
                continue
            info = child.lstat()
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if not getattr(info, "st_file_attributes", 0) & reparse:
                children.append(child.absolute())
        return frozenset(children)
    except NativeWorkspaceEventDenied:
        raise
    except OSError as exc:
        raise NativeWorkspaceEventDenied("watched directory cannot be enumerated") from exc


class NativeWorkspaceEventPublisherV1:
    """Own one native watcher and publish into existing governed runtimes."""

    def __init__(
        self,
        *,
        gate: NativeWorkspaceEventFeatureGateV1,
        roots: Sequence[Path | str],
        watched_paths: Sequence[Path | str],
        owner_profile_id: str,
        workspace_id: str,
        automation: EventDrivenAutomationRuntimeV1,
        awareness: EventDrivenAwarenessV1,
        watcher: _FileSystemWatcherV1,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if type(gate) is not NativeWorkspaceEventFeatureGateV1 or not gate.enabled:
            raise NativeWorkspaceEventDenied("native workspace events are disabled")
        if type(automation) is not EventDrivenAutomationRuntimeV1:
            raise NativeWorkspaceEventContractError("exact automation runtime is required")
        if type(awareness) is not EventDrivenAwarenessV1:
            raise NativeWorkspaceEventContractError("exact awareness runtime is required")
        if type(roots) not in {tuple, list} or not 1 <= len(roots) <= _MAX_ROOTS:
            raise NativeWorkspaceEventContractError("workspace roots are invalid")
        if (
            type(watched_paths) not in {tuple, list}
            or not 1 <= len(watched_paths) <= _MAX_WATCHED_PATHS
        ):
            raise NativeWorkspaceEventContractError("watched paths are invalid")
        if not callable(clock):
            raise NativeWorkspaceEventContractError("clock is invalid")

        controlled_roots = tuple(_real_path(item, directory=True) for item in roots)
        controlled_paths: list[Path] = []
        for item in watched_paths:
            candidate = _real_path(item)
            if not any(candidate == root or root in candidate.parents for root in controlled_roots):
                raise NativeWorkspaceEventDenied("watched path is outside controlled workspaces")
            controlled_paths.append(candidate)
        if len(set(controlled_paths)) != len(controlled_paths):
            raise NativeWorkspaceEventContractError("watched paths contain duplicates")

        self._owner_profile_id = owner_profile_id
        self._workspace_id = workspace_id
        self._automation = automation
        self._awareness = awareness
        self._adapter = WorkspaceFileEventAdapterV1(controlled_roots)
        self._watcher = watcher
        self._clock = clock
        self._paths = tuple(controlled_paths)
        self._directory_snapshots = {
            path: _bounded_children(path) for path in self._paths if path.is_dir()
        }
        self._published_events = 0
        self._coalesced_automation_events = 0
        self._denied_events = 0
        self._callback_errors = 0
        self._closed = False

        rejected = watcher.addPaths([str(path) for path in self._paths])
        if rejected:
            accepted = [str(path) for path in self._paths if str(path) not in set(rejected)]
            if accepted:
                watcher.removePaths(accepted)
            raise NativeWorkspaceEventDenied("native watcher rejected a controlled path")
        watcher.directoryChanged.connect(self._directory_changed)
        watcher.fileChanged.connect(self._file_changed)

    @property
    def background_workers(self) -> int:
        return 0

    @property
    def polling_interval(self) -> None:
        return None

    def status(self) -> NativeWorkspaceEventStatusV1:
        return NativeWorkspaceEventStatusV1(
            active=not self._closed,
            watched_paths=0 if self._closed else len(self._paths),
            published_events=self._published_events,
            coalesced_automation_events=self._coalesced_automation_events,
            denied_events=self._denied_events,
            callback_errors=self._callback_errors,
        )

    def _publish(self, path: Path, event_kind: str, occurred_at: float) -> None:
        event = self._adapter.from_native_event(
            path=path,
            event_kind=event_kind,
            owner_profile_id=self._owner_profile_id,
            workspace_id=self._workspace_id,
            occurred_at=occurred_at,
        )
        queued = self._automation.publish(event)
        if not queued:
            self._coalesced_automation_events += 1
        metadata = dict(event.metadata)
        metadata["automation_matches"] = len(queued)
        self._awareness.publish(
            AwarenessSignalV1.create(
                kind=SignalKindV1.WORKSPACE_CHANGED,
                source_id="native_workspace_events",
                owner_profile_id=self._owner_profile_id,
                workspace_id=self._workspace_id,
                metadata=metadata,
                coalesce_key=event.coalesce_key,
                occurred_at=occurred_at,
            ),
            now=occurred_at,
        )
        self._published_events += 1

    def _file_changed(self, raw_path: str) -> None:
        if self._closed:
            return
        try:
            path = Path(raw_path).absolute()
            self._publish(path, "modified" if path.exists() else "deleted", self._clock())
        except NativeWorkspaceEventDenied:
            self._denied_events += 1
        except BaseException:
            self._callback_errors += 1

    def _directory_changed(self, raw_path: str) -> None:
        if self._closed:
            return
        try:
            directory = Path(raw_path).absolute()
            previous = self._directory_snapshots.get(directory)
            if previous is None:
                raise NativeWorkspaceEventDenied("unregistered directory event was rejected")
            current = _bounded_children(directory)
            occurred_at = self._clock()
            for path in sorted(current - previous, key=str):
                self._publish(path, "created", occurred_at)
            for path in sorted(previous - current, key=str):
                self._publish(path, "deleted", occurred_at)
            self._directory_snapshots[directory] = current
        except NativeWorkspaceEventDenied:
            self._denied_events += 1
        except BaseException:
            self._callback_errors += 1

    def close(self) -> None:
        if self._closed:
            return
        self._watcher.directoryChanged.disconnect(self._directory_changed)
        self._watcher.fileChanged.disconnect(self._file_changed)
        self._watcher.removePaths([str(path) for path in self._paths])
        self._directory_snapshots.clear()
        self._closed = True


def create_qt_native_workspace_event_publisher_v1(**kwargs: object) -> NativeWorkspaceEventPublisherV1:
    """Construct the opt-in publisher on a host-owned Qt event loop."""

    from PySide6.QtCore import QCoreApplication, QFileSystemWatcher, QThread

    application = QCoreApplication.instance()
    if application is None or QThread.currentThread() != application.thread():
        raise NativeWorkspaceEventDenied("Qt native watcher must be created on the application thread")
    if "watcher" in kwargs:
        raise NativeWorkspaceEventContractError("the Qt factory owns its native watcher")
    return NativeWorkspaceEventPublisherV1(watcher=QFileSystemWatcher(), **kwargs)
