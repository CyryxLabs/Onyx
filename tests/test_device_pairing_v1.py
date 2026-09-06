from __future__ import annotations

import sqlite3

import pytest

from core.device_pairing_v1 import (
    DevicePairingDenied,
    DevicePairingStoreV1,
    MAX_ATTEMPTS,
)


def _store(tmp_path, now):
    return DevicePairingStoreV1(
        tmp_path / "pairing.sqlite3",
        enabled=True,
        clock=lambda: now[0],
        code_factory=lambda: "23456789",
        salt_factory=lambda size: b"s" * size,
    )


def _initiate(store):
    return store.initiate(
        owner_profile_id="owner.primary",
        workspace_id="workspace.main",
        device_id="device.phone",
        issuer="onyx.phone",
    )


def test_pairing_code_is_returned_once_but_never_persisted(tmp_path) -> None:
    now = [1000.0]
    store = _store(tmp_path, now)
    challenge = _initiate(store)
    assert challenge.display_code == "2345-6789"
    assert challenge.background_workers == 0
    assert challenge.polling_interval is None
    raw = (tmp_path / "pairing.sqlite3").read_bytes()
    assert b"23456789" not in raw
    with sqlite3.connect(tmp_path / "pairing.sqlite3") as connection:
        salt, digest = connection.execute(
            "SELECT salt,code_digest FROM pairing_sessions"
        ).fetchone()
    assert salt == b"s" * 32
    assert digest != "23456789"


def test_valid_claim_is_one_time_and_does_not_issue_credentials(tmp_path) -> None:
    now = [1000.0]
    store = _store(tmp_path, now)
    challenge = _initiate(store)
    claim = store.claim(pairing_id=challenge.pairing_id, display_code="2345 6789")
    assert claim.status == "claimed"
    assert claim.code_exposed is False
    assert claim.credential_issued is False
    assert store.status(challenge.pairing_id).status == "claimed"
    with pytest.raises(DevicePairingDenied, match="not pending"):
        store.claim(pairing_id=challenge.pairing_id, display_code="23456789")
    with sqlite3.connect(tmp_path / "pairing.sqlite3") as connection:
        salt, digest = connection.execute(
            "SELECT salt,code_digest FROM pairing_sessions"
        ).fetchone()
    assert salt == b""
    assert digest == "0" * 64


def test_expiry_and_attempt_limit_fail_closed(tmp_path) -> None:
    now = [1000.0]
    store = _store(tmp_path, now)
    challenge = _initiate(store)
    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(DevicePairingDenied):
            store.claim(pairing_id=challenge.pairing_id, display_code="ABCDEFGH")
    assert store.status(challenge.pairing_id).status == "cancelled"

    challenge2 = store.initiate(
        owner_profile_id="owner.primary",
        workspace_id="workspace.main",
        device_id="device.tablet",
        issuer="onyx.tablet",
        ttl_seconds=30,
    )
    now[0] = challenge2.expires_at
    with pytest.raises(DevicePairingDenied, match="expired"):
        store.claim(pairing_id=challenge2.pairing_id, display_code="23456789")
    assert store.status(challenge2.pairing_id).status == "expired"


def test_pending_device_is_unique_and_cancel_is_reversible(tmp_path) -> None:
    now = [1000.0]
    store = _store(tmp_path, now)
    first = _initiate(store)
    with pytest.raises(DevicePairingDenied, match="already exists"):
        _initiate(store)
    cancelled = store.cancel(first.pairing_id)
    assert cancelled.status == "cancelled"
    replacement = _initiate(store)
    assert store.status(replacement.pairing_id).status == "pending"


def test_disabled_and_linked_storage_are_denied(tmp_path) -> None:
    with pytest.raises(DevicePairingDenied, match="disabled"):
        DevicePairingStoreV1(tmp_path / "off.sqlite3", enabled=False)
