"""Official, receipt-bound outbound messaging for Onyx.

This is an adapter around the existing authority boundary, not a second tool
dispatcher.  A message is scope-checked and durably reserved before one exact
provider call.  Only metadata and content digests are persisted.  Credentials
remain in the native vault and there is no automatic retry or background work.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import sqlite3
import ssl
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, Mapping, Protocol

from core.native_vault import SecretReference


FEATURE_FLAG: Final = "ONYX_OFFICIAL_MESSAGING_V1"
DISCORD_ORIGIN: Final = "discord.com"
DISCORD_API_PREFIX: Final = "/api/v10"
MAX_CONTENT_CHARACTERS: Final = 2000
MAX_RESPONSE_BYTES: Final = 131_072
_SNOWFLAKE = re.compile(r"[0-9]{5,32}")
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


class OfficialMessagingError(RuntimeError):
    pass


class OfficialMessagingContractError(ValueError):
    pass


class OfficialMessagingDenied(PermissionError):
    pass


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise OfficialMessagingContractError(f"{label} is invalid")
    return value


def _snowflake(value: object, label: str) -> str:
    if type(value) is not str or _SNOWFLAKE.fullmatch(value) is None:
        raise OfficialMessagingContractError(f"{label} is invalid")
    return value


def _content(value: object) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise OfficialMessagingContractError("message content is invalid")
    if len(value) > MAX_CONTENT_CHARACTERS:
        raise OfficialMessagingContractError("message content exceeds provider limit")
    return value


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise OfficialMessagingContractError("value is not canonical JSON") from exc


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise OfficialMessagingContractError("an absolute outbox path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or (path.exists() and path.is_symlink()):
        raise OfficialMessagingDenied("linked outbox storage is forbidden")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(path.parent.stat(), "st_file_attributes", 0) & reparse:
        raise OfficialMessagingDenied("reparse-point outbox storage is forbidden")


@dataclass(frozen=True, slots=True)
class DiscordAccountV1:
    account_id: str
    owner_profile_id: str
    workspace_id: str
    secret_reference: SecretReference
    allowed_channel_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.account_id, "account_id")
        _identifier(self.owner_profile_id, "owner_profile_id")
        _identifier(self.workspace_id, "workspace_id")
        if type(self.secret_reference) is not SecretReference:
            raise OfficialMessagingContractError("exact SecretReference is required")
        if type(self.allowed_channel_ids) is not tuple or not self.allowed_channel_ids:
            raise OfficialMessagingContractError("allowed channels are required")
        checked = tuple(_snowflake(item, "channel_id") for item in self.allowed_channel_ids)
        if len(set(checked)) != len(checked):
            raise OfficialMessagingContractError("duplicate channel scope")


@dataclass(frozen=True, slots=True)
class DiscordMessageV1:
    operation_id: str
    account_id: str
    owner_profile_id: str
    workspace_id: str
    channel_id: str
    content: str
    nonce: str

    def __post_init__(self) -> None:
        _identifier(self.operation_id, "operation_id")
        _identifier(self.account_id, "account_id")
        _identifier(self.owner_profile_id, "owner_profile_id")
        _identifier(self.workspace_id, "workspace_id")
        _snowflake(self.channel_id, "channel_id")
        _content(self.content)
        if type(self.nonce) is not str or not 1 <= len(self.nonce) <= 25:
            raise OfficialMessagingContractError("nonce is invalid")

    @property
    def content_digest(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    def provider_payload(self) -> dict[str, object]:
        return {
            "content": self.content,
            "nonce": self.nonce,
            "enforce_nonce": True,
            "allowed_mentions": {"parse": [], "users": [], "roles": [], "replied_user": False},
        }


@dataclass(frozen=True, slots=True)
class ProviderMessageReceiptV1:
    provider: str
    provider_message_id: str
    channel_id: str
    nonce: str
    accepted_at: float

    def __post_init__(self) -> None:
        if self.provider != "discord":
            raise OfficialMessagingContractError("provider is invalid")
        _snowflake(self.provider_message_id, "provider_message_id")
        _snowflake(self.channel_id, "channel_id")
        if type(self.nonce) is not str or not self.nonce:
            raise OfficialMessagingContractError("receipt nonce is invalid")
        if isinstance(self.accepted_at, bool) or not isinstance(self.accepted_at, (int, float)):
            raise OfficialMessagingContractError("receipt time is invalid")
        if not math.isfinite(float(self.accepted_at)) or float(self.accepted_at) <= 0:
            raise OfficialMessagingContractError("receipt time is invalid")


@dataclass(frozen=True, slots=True)
class OfficialMessageDispatchV1:
    operation_id: str
    status: str
    content_digest: str
    provider_message_id: str | None
    detail: str


class DiscordTransportV1(Protocol):
    def send(
        self, account: DiscordAccountV1, message: DiscordMessageV1
    ) -> ProviderMessageReceiptV1: ...


class StdlibDiscordTransportV1:
    """One route-pinned HTTPS call to Discord's official Create Message API."""

    def __init__(
        self,
        *,
        vault_reader: Callable[[SecretReference], bytes | None],
        connection_factory: Callable[..., http.client.HTTPSConnection] = http.client.HTTPSConnection,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not callable(vault_reader) or not callable(connection_factory) or not callable(clock):
            raise OfficialMessagingContractError("transport dependencies are invalid")
        self._vault_reader = vault_reader
        self._connection_factory = connection_factory
        self._clock = clock
        self.background_workers = 0
        self.retry_count = 0

    def send(
        self, account: DiscordAccountV1, message: DiscordMessageV1
    ) -> ProviderMessageReceiptV1:
        if type(account) is not DiscordAccountV1 or type(message) is not DiscordMessageV1:
            raise OfficialMessagingContractError("exact Discord contracts are required")
        secret = self._vault_reader(account.secret_reference)
        if not isinstance(secret, bytes) or not 20 <= len(secret) <= 512:
            raise OfficialMessagingDenied("Discord credential is unavailable")
        try:
            authorization = "Bot " + secret.decode("ascii")
        except UnicodeDecodeError as exc:
            raise OfficialMessagingDenied("Discord credential is invalid") from exc
        body = _canonical(message.provider_payload()).encode("utf-8")
        connection = self._connection_factory(
            DISCORD_ORIGIN, 443, timeout=20, context=ssl.create_default_context()
        )
        try:
            connection.request(
                "POST",
                f"{DISCORD_API_PREFIX}/channels/{message.channel_id}/messages",
                body=body,
                headers={
                    "Authorization": authorization,
                    "Content-Type": "application/json",
                    "User-Agent": "Cyryx-Onyx/1.1",
                },
            )
            response = connection.getresponse()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        except Exception as exc:
            raise OfficialMessagingError("Discord request outcome is unknown") from exc
        finally:
            connection.close()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise OfficialMessagingError("Discord response exceeded its byte budget")
        if response.status < 200 or response.status >= 300:
            raise OfficialMessagingError(f"Discord rejected the message ({response.status})")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OfficialMessagingError("Discord returned an invalid receipt") from exc
        if type(payload) is not dict:
            raise OfficialMessagingError("Discord returned an invalid receipt")
        provider_id = _snowflake(payload.get("id"), "provider_message_id")
        channel_id = _snowflake(payload.get("channel_id"), "channel_id")
        nonce = payload.get("nonce")
        if channel_id != message.channel_id or str(nonce) != message.nonce:
            raise OfficialMessagingError("Discord receipt binding diverged")
        return ProviderMessageReceiptV1(
            "discord", provider_id, channel_id, message.nonce, float(self._clock())
        )


class OfficialMessagingOutboxV1:
    """Durable reservation and provider-receipt projection."""

    _DDL = (
        """CREATE TABLE messages(
          operation_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
          owner_profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
          channel_id TEXT NOT NULL, nonce TEXT NOT NULL UNIQUE,
          content_digest TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN
          ('reserved','sending','accepted','reconciliation','denied')),
          provider_message_id TEXT, detail TEXT NOT NULL,
          created_at REAL NOT NULL, updated_at REAL NOT NULL
        )""",
        """CREATE TABLE message_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT NOT NULL,
          occurred_at REAL NOT NULL, event TEXT NOT NULL, detail_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE TRIGGER message_events_no_update BEFORE UPDATE ON message_events
          BEGIN SELECT RAISE(ABORT,'message events are immutable'); END""",
        """CREATE TRIGGER message_events_no_delete BEFORE DELETE ON message_events
          BEGIN SELECT RAISE(ABORT,'message events are immutable'); END""",
    )

    def __init__(self, path: Path | str, *, enabled: bool, clock: Callable[[], float] = time.time) -> None:
        if type(enabled) is not bool or not enabled:
            raise OfficialMessagingDenied("official messaging is disabled")
        if not callable(clock):
            raise OfficialMessagingContractError("clock is invalid")
        self.path = Path(path)
        _private_path(self.path)
        self._clock = clock
        self._lock = threading.RLock()
        self.background_workers = 0
        self.polling_interval = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        _private_path(self.path)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            count = int(connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchone()[0])
            if version == 0 and count == 0:
                connection.execute("BEGIN IMMEDIATE")
                for statement in self._DDL:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=1")
                connection.execute("COMMIT")
            if int(connection.execute("PRAGMA user_version").fetchone()[0]) != 1:
                raise OfficialMessagingError("outbox schema version is invalid")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise OfficialMessagingError("outbox integrity failed")

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        operation_id: str,
        event: str,
        detail: Mapping[str, object],
        now: float,
    ) -> None:
        previous = connection.execute(
            "SELECT event_hash FROM message_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = "0" * 64 if previous is None else str(previous[0])
        detail_json = _canonical(dict(detail))
        event_hash = hashlib.sha256(_canonical({
            "operation_id": operation_id, "occurred_at": now, "event": event,
            "detail_json": detail_json, "prev_hash": prev_hash,
        }).encode("utf-8")).hexdigest()
        connection.execute(
            "INSERT INTO message_events(operation_id,occurred_at,event,detail_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
            (operation_id, now, event, detail_json, prev_hash, event_hash),
        )

    def send_discord(
        self,
        *,
        account: DiscordAccountV1,
        channel_id: str,
        content: str,
        authority: Callable[[str, str, str, str, str], bool],
        transport: DiscordTransportV1,
    ) -> OfficialMessageDispatchV1:
        if type(account) is not DiscordAccountV1 or not callable(authority):
            raise OfficialMessagingContractError("messaging dependencies are invalid")
        channel = _snowflake(channel_id, "channel_id")
        text = _content(content)
        if channel not in account.allowed_channel_ids:
            raise OfficialMessagingDenied("channel is outside the approved account scope")
        decision = authority(
            account.owner_profile_id, account.workspace_id,
            "official_message.send", account.account_id, channel,
        )
        if type(decision) is not bool or not decision:
            raise OfficialMessagingDenied("central authority denied the message")
        operation_id = "msg_" + uuid.uuid4().hex
        message = DiscordMessageV1(
            operation_id, account.account_id, account.owner_profile_id,
            account.workspace_id, channel, text, uuid.uuid4().hex[:25],
        )
        now = float(self._clock())
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (operation_id, account.account_id, account.owner_profile_id,
                 account.workspace_id, channel, message.nonce, message.content_digest,
                 "reserved", None, "registered_before_provider", now, now),
            )
            self._event(connection, operation_id, "message.reserved", {
                "provider": "discord", "channel_id": channel,
                "content_digest": message.content_digest,
            }, now)
            connection.execute("COMMIT")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE messages SET status='sending',detail=?,updated_at=? WHERE operation_id=?",
                ("provider_invoked_after_reservation", now, operation_id),
            )
            self._event(connection, operation_id, "message.sending", {}, now)
            connection.execute("COMMIT")
        try:
            receipt = transport.send(account, message)
            if type(receipt) is not ProviderMessageReceiptV1:
                raise OfficialMessagingError("provider returned no exact receipt")
            if receipt.channel_id != channel or receipt.nonce != message.nonce:
                raise OfficialMessagingError("provider receipt binding diverged")
        except BaseException:
            uncertain = float(self._clock())
            with self._lock, self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE messages SET status='reconciliation',detail=?,updated_at=? WHERE operation_id=?",
                    ("provider_outcome_unknown", uncertain, operation_id),
                )
                self._event(connection, operation_id, "message.reconciliation", {}, uncertain)
                connection.execute("COMMIT")
            raise
        accepted = float(self._clock())
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE messages SET status='accepted',provider_message_id=?,detail=?,updated_at=? WHERE operation_id=?",
                (receipt.provider_message_id, "provider_receipt_verified", accepted, operation_id),
            )
            self._event(connection, operation_id, "message.accepted", {
                "provider_message_id": receipt.provider_message_id,
                "content_digest": message.content_digest,
            }, accepted)
            connection.execute("COMMIT")
        return OfficialMessageDispatchV1(
            operation_id, "accepted", message.content_digest,
            receipt.provider_message_id, "provider_receipt_verified",
        )

    def dispatch(self, operation_id: str) -> OfficialMessageDispatchV1:
        key = _identifier(operation_id, "operation_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT operation_id,status,content_digest,provider_message_id,detail FROM messages WHERE operation_id=?",
                (key,),
            ).fetchone()
        if row is None:
            raise OfficialMessagingDenied("message operation is unavailable")
        return OfficialMessageDispatchV1(
            str(row["operation_id"]), str(row["status"]), str(row["content_digest"]),
            None if row["provider_message_id"] is None else str(row["provider_message_id"]),
            str(row["detail"]),
        )


__all__ = [
    "FEATURE_FLAG", "DiscordAccountV1", "DiscordMessageV1",
    "ProviderMessageReceiptV1", "OfficialMessageDispatchV1",
    "DiscordTransportV1", "StdlibDiscordTransportV1", "OfficialMessagingOutboxV1",
    "OfficialMessagingError", "OfficialMessagingContractError", "OfficialMessagingDenied",
]
