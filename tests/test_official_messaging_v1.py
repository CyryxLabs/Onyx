from __future__ import annotations

import sqlite3

import pytest

from core.native_vault import SecretReference
from core.official_messaging_v1 import (
    DiscordMessageV1,
    DiscordAccountV1,
    OfficialMessagingDenied,
    OfficialMessagingError,
    OfficialMessagingOutboxV1,
    ProviderMessageReceiptV1,
    StdlibDiscordTransportV1,
)


CHANNEL = "123456789012345678"


def _account() -> DiscordAccountV1:
    return DiscordAccountV1(
        "discord.cyryx", "owner.primary", "workspace.main",
        SecretReference("onyx.messaging", "discord.cyryx", "Discord bot"),
        (CHANNEL,),
    )


class _Transport:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []

    def send(self, account, message):
        self.calls.append((account, message))
        if self.fail:
            raise OfficialMessagingError("unknown")
        return ProviderMessageReceiptV1(
            "discord", "987654321098765432", message.channel_id,
            message.nonce, 1001.0,
        )


def test_message_is_reserved_then_bound_to_official_provider_receipt(tmp_path) -> None:
    clock = iter((1000.0, 1001.0))
    outbox = OfficialMessagingOutboxV1(
        tmp_path / "messages.sqlite3", enabled=True, clock=lambda: next(clock)
    )
    transport = _Transport()
    result = outbox.send_discord(
        account=_account(), channel_id=CHANNEL, content="Operational update.",
        authority=lambda *args: True, transport=transport,
    )
    assert result.status == "accepted"
    assert result.provider_message_id == "987654321098765432"
    assert outbox.dispatch(result.operation_id) == result
    assert transport.calls[0][1].provider_payload()["allowed_mentions"] == {
        "parse": [], "users": [], "roles": [], "replied_user": False,
    }
    assert transport.calls[0][1].provider_payload()["enforce_nonce"] is True


def test_outbox_persists_digest_and_receipt_but_never_content_or_secret(tmp_path) -> None:
    clock = iter((1000.0, 1001.0))
    path = tmp_path / "messages.sqlite3"
    outbox = OfficialMessagingOutboxV1(path, enabled=True, clock=lambda: next(clock))
    result = outbox.send_discord(
        account=_account(), channel_id=CHANNEL, content="Never persist this body 7KQ9.",
        authority=lambda *args: True, transport=_Transport(),
    )
    raw = path.read_bytes()
    assert b"Never persist this body 7KQ9" not in raw
    assert b"Discord bot" not in raw
    assert result.content_digest.encode() in raw


def test_scope_and_authority_fail_before_transport_or_reservation(tmp_path) -> None:
    path = tmp_path / "messages.sqlite3"
    outbox = OfficialMessagingOutboxV1(path, enabled=True)
    transport = _Transport()
    with pytest.raises(OfficialMessagingDenied, match="outside"):
        outbox.send_discord(
            account=_account(), channel_id="222222222222222222", content="No.",
            authority=lambda *args: True, transport=transport,
        )
    with pytest.raises(OfficialMessagingDenied, match="authority"):
        outbox.send_discord(
            account=_account(), channel_id=CHANNEL, content="No.",
            authority=lambda *args: False, transport=transport,
        )
    assert transport.calls == []
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_unknown_provider_outcome_enters_reconciliation_without_retry(tmp_path) -> None:
    clock = iter((1000.0, 1001.0))
    outbox = OfficialMessagingOutboxV1(
        tmp_path / "messages.sqlite3", enabled=True, clock=lambda: next(clock)
    )
    transport = _Transport(fail=True)
    with pytest.raises(OfficialMessagingError):
        outbox.send_discord(
            account=_account(), channel_id=CHANNEL, content="One call only.",
            authority=lambda *args: True, transport=transport,
        )
    assert len(transport.calls) == 1
    with sqlite3.connect(tmp_path / "messages.sqlite3") as connection:
        assert connection.execute("SELECT status FROM messages").fetchone()[0] == "reconciliation"


def test_disabled_outbox_and_oversized_content_fail_closed(tmp_path) -> None:
    with pytest.raises(OfficialMessagingDenied, match="disabled"):
        OfficialMessagingOutboxV1(tmp_path / "off.sqlite3", enabled=False)
    outbox = OfficialMessagingOutboxV1(tmp_path / "on.sqlite3", enabled=True)
    with pytest.raises(ValueError, match="provider limit"):
        outbox.send_discord(
            account=_account(), channel_id=CHANNEL, content="x" * 2001,
            authority=lambda *args: True, transport=_Transport(),
        )


def test_stdlib_transport_is_route_pinned_one_call_and_receipt_bound() -> None:
    observed = {}

    class Response:
        status = 200

        @staticmethod
        def read(_limit):
            return b'{"id":"987654321098765432","channel_id":"123456789012345678","nonce":"nonce-1"}'

    class Connection:
        def request(self, method, path, body, headers):
            observed.update(method=method, path=path, body=body, headers=headers)

        @staticmethod
        def getresponse():
            return Response()

        @staticmethod
        def close():
            observed["closed"] = True

    def factory(origin, port, timeout, context):
        observed.update(origin=origin, port=port, timeout=timeout, context=context)
        return Connection()

    transport = StdlibDiscordTransportV1(
        vault_reader=lambda _reference: b"discord-secret-value-1234567890",
        connection_factory=factory,
        clock=lambda: 1001.0,
    )
    message = DiscordMessageV1(
        "msg_operation", "discord.cyryx", "owner.primary", "workspace.main",
        CHANNEL, "Hello.", "nonce-1",
    )
    receipt = transport.send(_account(), message)
    assert receipt.provider_message_id == "987654321098765432"
    assert observed["origin"] == "discord.com"
    assert observed["path"] == f"/api/v10/channels/{CHANNEL}/messages"
    assert observed["method"] == "POST"
    assert observed["headers"]["Authorization"].startswith("Bot ")
    assert observed["closed"] is True
    assert transport.retry_count == 0
