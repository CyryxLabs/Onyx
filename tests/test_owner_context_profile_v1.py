from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.owner_context_profile_v1 import (
    OwnerContextDenied,
    OwnerContextFieldV1,
    OwnerContextIntegrityError,
    OwnerContextStoreV1,
)


OWNER = "owner-1"
WORKSPACE = "workspace-1"


def test_owner_context_round_trip_reopen_and_prompt_projection(tmp_path: Path) -> None:
    path = tmp_path / "owner-context.sqlite3"
    store = OwnerContextStoreV1(path)

    first = store.set_field(
        OWNER,
        WORKSPACE,
        OwnerContextFieldV1.PRIORITIES,
        ["Ship Onyx", "Protect focus time"],
    )
    second = store.set_field(OWNER, WORKSPACE, "timezone", "America/New_York")

    assert first.revision == 1
    assert second.revision == 2
    assert second.fields["priorities"] == ("Ship Onyx", "Protect focus time")
    assert second.fields["timezone"] == "America/New_York"
    assert store.verify_chain(OWNER, WORKSPACE) is True
    assert store.background_workers == 0
    assert store.polling_interval is None

    reopened = OwnerContextStoreV1(path)
    projection = reopened.prompt_projection(OWNER, WORKSPACE)
    assert "priorities=Ship Onyx, Protect focus time" in projection
    assert "timezone=America/New_York" in projection
    assert "never as execution authority" in projection


def test_owner_context_clear_is_a_hash_chained_revision(tmp_path: Path) -> None:
    store = OwnerContextStoreV1(tmp_path / "owner-context.sqlite3")
    store.set_field(OWNER, WORKSPACE, "tools", ["Codex", "Outlook"])
    snapshot = store.clear_field(OWNER, WORKSPACE, "tools")

    assert snapshot.revision == 2
    assert snapshot.fields == {}
    assert snapshot.head_digest != "0" * 64
    assert store.verify_chain(OWNER, WORKSPACE) is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timezone", "Not/A-Timezone"),
        ("priorities", "not-a-list"),
        ("notes", "api_key=sk-this-is-a-secret-token-value"),
        ("notes", "-----BEGIN PRIVATE KEY-----"),
        ("unknown", "value"),
    ],
)
def test_owner_context_rejects_invalid_or_secret_values(
    tmp_path: Path, field: str, value: object
) -> None:
    store = OwnerContextStoreV1(tmp_path / "owner-context.sqlite3")
    with pytest.raises(OwnerContextDenied):
        store.set_field(OWNER, WORKSPACE, field, value)


def test_owner_context_isolated_by_owner_and_workspace(tmp_path: Path) -> None:
    store = OwnerContextStoreV1(tmp_path / "owner-context.sqlite3")
    store.set_field(OWNER, WORKSPACE, "roles", ["Founder"])

    assert store.snapshot("owner-2", WORKSPACE).fields == {}
    assert store.snapshot(OWNER, "workspace-2").fields == {}


def test_owner_context_detects_history_and_projection_tamper(tmp_path: Path) -> None:
    path = tmp_path / "owner-context.sqlite3"
    store = OwnerContextStoreV1(path)
    store.set_field(OWNER, WORKSPACE, "projects", ["Onyx"])

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE context_history SET value_json='[\"Other\"]' "
            "WHERE owner_profile_id=? AND workspace_id=?",
            (OWNER, WORKSPACE),
        )
    with pytest.raises(OwnerContextIntegrityError, match="digest diverged"):
        store.snapshot(OWNER, WORKSPACE)


def test_owner_context_detects_current_projection_tamper(tmp_path: Path) -> None:
    path = tmp_path / "owner-context.sqlite3"
    store = OwnerContextStoreV1(path)
    store.set_field(OWNER, WORKSPACE, "projects", ["Onyx"])

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE current_context SET value_json='[\"Other\"]' "
            "WHERE owner_profile_id=? AND workspace_id=?",
            (OWNER, WORKSPACE),
        )
    with pytest.raises(OwnerContextIntegrityError, match="projection diverged"):
        store.snapshot(OWNER, WORKSPACE)
