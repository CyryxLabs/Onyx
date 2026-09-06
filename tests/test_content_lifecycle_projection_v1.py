from __future__ import annotations

import sqlite3

import pytest

from core.content_lifecycle_projection_v1 import (
    ContentLifecycleDenied,
    ContentLifecycleProjectionV1,
    ContentProviderReceiptV1,
)


OWNER = "owner.primary"
WORKSPACE = "workspace.main"


def _schedule(store, body="Do not persist this content body 8ZP4."):
    return store.schedule(
        owner_profile_id=OWNER, workspace_id=WORKSPACE, provider="discord",
        account_id="discord.cyryx", destination_id="channel.general",
        content=body, scheduled_for=1100.0,
    )


def test_lifecycle_is_reserved_before_effect_and_exact_receipt_completes(tmp_path) -> None:
    clock = iter((1000.0, 1001.0, 1002.0, 1003.0))
    store = ContentLifecycleProjectionV1(
        tmp_path / "content.sqlite3", enabled=True, clock=lambda: next(clock)
    )
    scheduled = _schedule(store)
    reserved = store.reserve(
        scheduled.content_id, owner_profile_id=OWNER, workspace_id=WORKSPACE,
        authority=lambda *args: True,
    )
    assert reserved.status == "reserved"
    assert reserved.reservation_id is not None
    publishing = store.begin_publish(
        scheduled.content_id, owner_profile_id=OWNER, workspace_id=WORKSPACE,
        reservation_id=reserved.reservation_id,
    )
    with sqlite3.connect(store.path) as connection:
        key = connection.execute(
            "SELECT idempotency_key FROM content_items WHERE content_id=?",
            (scheduled.content_id,),
        ).fetchone()[0]
    receipt = ContentProviderReceiptV1(
        scheduled.content_id, reserved.reservation_id, "discord", "discord.cyryx",
        "channel.general", "message.verified", scheduled.content_digest, key, 1003.0,
    )
    published = store.record_receipt(
        receipt, owner_profile_id=OWNER, workspace_id=WORKSPACE
    )
    assert publishing.status == "publishing"
    assert published.status == "published"
    assert published.provider_item_id == "message.verified"
    assert store.background_workers == store.network_calls == store.provider_calls == 0


def test_only_digest_and_metadata_survive_restart(tmp_path) -> None:
    body = "Secret draft body that must never be stored 3QX7."
    path = tmp_path / "content.sqlite3"
    store = ContentLifecycleProjectionV1(path, enabled=True, clock=lambda: 1000.0)
    item = _schedule(store, body)
    assert body.encode() not in path.read_bytes()
    assert item.content_digest.encode() in path.read_bytes()
    reopened = ContentLifecycleProjectionV1(path, enabled=True, clock=lambda: 1001.0)
    assert reopened.get(
        item.content_id, owner_profile_id=OWNER, workspace_id=WORKSPACE
    ).content_digest == item.content_digest


def test_scope_authority_and_state_machine_fail_closed(tmp_path) -> None:
    store = ContentLifecycleProjectionV1(
        tmp_path / "content.sqlite3", enabled=True, clock=lambda: 1000.0
    )
    item = _schedule(store)
    with pytest.raises(ContentLifecycleDenied, match="authority"):
        store.reserve(
            item.content_id, owner_profile_id=OWNER, workspace_id=WORKSPACE,
            authority=lambda *args: False,
        )
    with pytest.raises(ContentLifecycleDenied, match="unavailable"):
        store.get(item.content_id, owner_profile_id="owner.other", workspace_id=WORKSPACE)
    with pytest.raises(ContentLifecycleDenied, match="transition"):
        store.begin_publish(
            item.content_id, owner_profile_id=OWNER, workspace_id=WORKSPACE,
            reservation_id="reservation.invalid",
        )


def test_divergent_receipt_is_rejected_and_outcome_can_enter_reconciliation(tmp_path) -> None:
    clock = iter((1000.0, 1001.0, 1002.0, 1003.0))
    store = ContentLifecycleProjectionV1(
        tmp_path / "content.sqlite3", enabled=True, clock=lambda: next(clock)
    )
    item = _schedule(store)
    reserved = store.reserve(
        item.content_id, owner_profile_id=OWNER, workspace_id=WORKSPACE,
        authority=lambda *args: True,
    )
    store.begin_publish(
        item.content_id, owner_profile_id=OWNER, workspace_id=WORKSPACE,
        reservation_id=reserved.reservation_id,
    )
    bad = ContentProviderReceiptV1(
        item.content_id, reserved.reservation_id, "discord", "discord.other",
        "channel.general", "message.bad", item.content_digest,
        "publish.invalid", 1003.0,
    )
    with pytest.raises(ContentLifecycleDenied, match="binding"):
        store.record_receipt(bad, owner_profile_id=OWNER, workspace_id=WORKSPACE)
    uncertain = store.mark_uncertain(
        item.content_id, owner_profile_id=OWNER, workspace_id=WORKSPACE,
        reservation_id=reserved.reservation_id,
    )
    assert uncertain.status == "reconciliation"


def test_cancel_and_bounded_scope_projection(tmp_path) -> None:
    store = ContentLifecycleProjectionV1(
        tmp_path / "content.sqlite3", enabled=True, clock=lambda: 1000.0
    )
    item = _schedule(store)
    cancelled = store.cancel(
        item.content_id, owner_profile_id=OWNER, workspace_id=WORKSPACE
    )
    assert cancelled.status == "cancelled"
    assert store.list_items(owner_profile_id=OWNER, workspace_id=WORKSPACE) == (cancelled,)
    with pytest.raises(ValueError, match="limit"):
        store.list_items(owner_profile_id=OWNER, workspace_id=WORKSPACE, limit=201)
