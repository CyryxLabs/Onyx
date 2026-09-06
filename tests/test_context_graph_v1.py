from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.context_graph_v1 import (
    ContextGraphDenied,
    ContextGraphFeatureGateV1,
    ContextGraphStoreV1,
)


def _store(tmp_path: Path) -> ContextGraphStoreV1:
    return ContextGraphStoreV1(
        tmp_path / "context-graph.sqlite3", ContextGraphFeatureGateV1(True)
    )


def test_context_graph_defaults_off_and_has_zero_idle_work(tmp_path: Path) -> None:
    assert ContextGraphFeatureGateV1.from_environ({}).enabled is False
    with pytest.raises(ContextGraphDenied, match="disabled"):
        ContextGraphStoreV1(
            tmp_path / "disabled.sqlite3", ContextGraphFeatureGateV1(False)
        )
    store = _store(tmp_path)
    assert store.background_workers == 0
    assert store.polling_interval is None


def test_context_graph_persists_application_project_relation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.observe(
        signal_kind="workspace.changed",
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        occurred_at=100.0,
        metadata={"project_id": "project.onyx"},
    )
    store.observe(
        signal_kind="foreground.changed",
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        occurred_at=101.0,
        metadata={"application_id": "app.editor"},
    )
    projection = ContextGraphStoreV1(
        store.path, ContextGraphFeatureGateV1(True)
    ).projection("owner_primary", "workspace_personal")
    assert projection.active_application_id == "app.editor"
    assert projection.active_project_id == "project.onyx"
    assert projection.nodes == (
        ("application", "app.editor"),
        ("project", "project.onyx"),
    )
    assert projection.edges == (
        ("app.editor", "active_in", "project.onyx", 1),
    )
    assert projection.observations == 2


def test_context_graph_rejects_content_and_is_scope_isolated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ContextGraphDenied, match="allowlisted"):
        store.observe(
            signal_kind="foreground.changed",
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            occurred_at=100.0,
            metadata={"screenshot": "captured"},
        )
    assert store.projection("owner_other", "workspace_personal").observations == 0


def test_context_event_chain_is_append_only_and_tamper_visible(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for occurred_at, application in ((100.0, "app.editor"), (101.0, "app.browser")):
        store.observe(
            signal_kind="foreground.changed",
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            occurred_at=occurred_at,
            metadata={"application_id": application},
        )
    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT previous_hash,event_hash FROM context_events ORDER BY sequence"
        ).fetchall()
    assert rows[0][0] == "0" * 64
    assert rows[1][0] == rows[0][1]
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE context_events SET payload_json='{}' WHERE sequence=1"
            )


def test_context_event_chain_fails_closed_if_storage_boundary_is_bypassed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.observe(
        signal_kind="foreground.changed",
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        occurred_at=100.0,
        metadata={"application_id": "app.editor"},
    )
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TRIGGER context_events_no_update")
        connection.execute(
            "UPDATE context_events SET payload_json='{}' WHERE sequence=1"
        )
    with pytest.raises(ContextGraphDenied, match="event chain diverged"):
        store.projection("owner_primary", "workspace_personal")
