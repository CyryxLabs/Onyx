from __future__ import annotations

from pathlib import Path

import pytest

from core.event_awareness_v1 import AwarenessPolicyV1, EventDrivenAwarenessV1
from core.native_workspace_events_v1 import (
    NativeWorkspaceEventDenied,
    NativeWorkspaceEventFeatureGateV1,
    NativeWorkspaceEventPublisherV1,
)


class _Signal:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self, path: Path) -> None:
        for callback in tuple(self.callbacks):
            callback(str(path))


class _Watcher:
    def __init__(self, *, rejected: list[str] | None = None) -> None:
        self.directoryChanged = _Signal()
        self.fileChanged = _Signal()
        self.rejected = rejected or []
        self.added: list[str] = []
        self.removed: list[str] = []

    def addPaths(self, paths):
        self.added.extend(paths)
        return self.rejected

    def removePaths(self, paths):
        self.removed.extend(paths)
        return []


class _Automation:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event):
        self.events.append(event)
        return ()


def _awareness() -> EventDrivenAwarenessV1:
    return EventDrivenAwarenessV1(
        AwarenessPolicyV1(allowed_sources=("native_workspace_events",))
    )


def _publisher(root: Path, watcher: _Watcher, automation, awareness):
    # The runtime type checks are deliberately strict in production.  Tests use
    # minimal exact-behaviour doubles by creating without invoking __init__.
    from core.governed_automation_v1 import EventDrivenAutomationRuntimeV1

    runtime = object.__new__(EventDrivenAutomationRuntimeV1)
    runtime.publish = automation.publish
    return NativeWorkspaceEventPublisherV1(
        gate=NativeWorkspaceEventFeatureGateV1(True),
        roots=(root,),
        watched_paths=(root,),
        owner_profile_id="owner_test",
        workspace_id="workspace_test",
        automation=runtime,
        awareness=awareness,
        watcher=watcher,
        clock=lambda: 100.0,
    )


def test_gate_is_default_off_and_rejects_activation(tmp_path: Path):
    root = tmp_path.resolve()
    from core.governed_automation_v1 import EventDrivenAutomationRuntimeV1

    with pytest.raises(NativeWorkspaceEventDenied, match="disabled"):
        NativeWorkspaceEventPublisherV1(
            gate=NativeWorkspaceEventFeatureGateV1(),
            roots=(root,),
            watched_paths=(root,),
            owner_profile_id="owner_test",
            workspace_id="workspace_test",
            automation=object.__new__(EventDrivenAutomationRuntimeV1),
            awareness=_awareness(),
            watcher=_Watcher(),
        )


def test_directory_events_publish_metadata_only_without_polling(tmp_path: Path):
    root = tmp_path.resolve()
    watcher = _Watcher()
    automation = _Automation()
    awareness = _awareness()
    publisher = _publisher(root, watcher, automation, awareness)

    created = root / "report.txt"
    created.write_text("secret body must never be captured", encoding="utf-8")
    watcher.directoryChanged.emit(root)

    assert publisher.background_workers == 0
    assert publisher.polling_interval is None
    assert len(automation.events) == 1
    assert automation.events[0].event_type == "workspace.file.changed"
    assert "report.txt" not in repr(automation.events[0].metadata)
    assert "secret body" not in repr(automation.events[0].metadata)
    assert awareness.queued == 1
    assert publisher.status().published_events == 1
    assert publisher.status().coalesced_automation_events == 1

    created.unlink()
    watcher.directoryChanged.emit(root)
    assert len(automation.events) == 2
    assert dict(automation.events[1].metadata)["event_kind"] == "deleted"
    assert "report.txt" not in repr(automation.events[1].metadata)


def test_explicit_file_event_and_close_are_bounded(tmp_path: Path):
    root = tmp_path.resolve()
    file_path = root / "state.json"
    file_path.write_text("{}", encoding="utf-8")
    watcher = _Watcher()
    automation = _Automation()
    awareness = _awareness()
    publisher = _publisher(root, watcher, automation, awareness)
    publisher.close()

    watcher.fileChanged.emit(file_path)
    assert automation.events == []
    assert publisher.status().active is False
    assert publisher.status().watched_paths == 0
    assert watcher.removed == [str(root)]


def test_paths_outside_roots_and_watcher_rejection_fail_closed(tmp_path: Path):
    root = (tmp_path / "root").resolve()
    outside = (tmp_path / "outside").resolve()
    root.mkdir()
    outside.mkdir()
    from core.governed_automation_v1 import EventDrivenAutomationRuntimeV1

    runtime = object.__new__(EventDrivenAutomationRuntimeV1)
    runtime.publish = lambda event: ()
    with pytest.raises(NativeWorkspaceEventDenied, match="outside"):
        NativeWorkspaceEventPublisherV1(
            gate=NativeWorkspaceEventFeatureGateV1(True),
            roots=(root,),
            watched_paths=(outside,),
            owner_profile_id="owner_test",
            workspace_id="workspace_test",
            automation=runtime,
            awareness=_awareness(),
            watcher=_Watcher(),
        )

    with pytest.raises(NativeWorkspaceEventDenied, match="rejected"):
        NativeWorkspaceEventPublisherV1(
            gate=NativeWorkspaceEventFeatureGateV1(True),
            roots=(root,),
            watched_paths=(root,),
            owner_profile_id="owner_test",
            workspace_id="workspace_test",
            automation=runtime,
            awareness=_awareness(),
            watcher=_Watcher(rejected=[str(root)]),
        )
