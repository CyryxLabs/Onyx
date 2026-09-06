"""Governed, default-off Telegram Bot API text/PDF connector for Onyx.

This source-only boundary is deliberately absent from live activation.  It
supports plain-text ``sendMessage`` and bounded PDF ``sendDocument`` uploads to
the official HTTPS Bot API. A caller-supplied idempotency key is durably reserved
before the provider is invoked, and an ambiguous outcome is never retried.

The Bot API requires the bot token in the request path.  The token is therefore
resolved at the last possible moment from an injected OS-vault reader, used for
one route-pinned request, and never included in an exception, durable record,
audit event, or returned receipt.

Ordinary URLs are permitted inside the user's message text.  They remain inert
content: this connector never fetches a message URL. PDFs are snapshotted from
an explicit local root before exact-request approval; uploads use those bytes,
never a provider URL, file_id, or a reopened path.

Primary protocol reference: https://core.telegram.org/bots/api
"""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import re
import secrets
import sqlite3
import ssl
import stat
import threading
import time
import weakref
from contextlib import closing
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Callable, Final, Mapping, Protocol

import psutil

from core.native_vault import SecretReference


FEATURE_FLAG: Final = "ONYX_TELEGRAM_OFFICIAL_CONNECTOR_V1"
ENABLED_VALUE: Final = "true"
TELEGRAM_ORIGIN: Final = "api.telegram.org"
TELEGRAM_VAULT_SERVICE: Final = "onyx.telegram.bot"
MAX_TEXT_CHARACTERS: Final = 4_096
MAX_TEXT_BYTES: Final = 12_288
MAX_REQUEST_BYTES: Final = 32_768
MAX_DOCUMENT_BYTES: Final = 10 * 1024 * 1024
MAX_RESPONSE_BYTES: Final = 131_072
MAX_TIMEOUT_SECONDS: Final = 30.0
MINIMUM_LEASE_SECONDS: Final = 60.0
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}\Z")
_TOKEN = re.compile(rb"[0-9]{5,20}:[A-Za-z0-9_-]{20,160}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_PROCESS_START_MARKER = f"{psutil.Process(os.getpid()).create_time():.6f}"
_LIVE_OUTBOX_LOCK = threading.Lock()
_LIVE_OUTBOXES: weakref.WeakValueDictionary[str, object] = (
    weakref.WeakValueDictionary()
)


def _pid_alive(pid: int, expected_start: str) -> bool:
    if type(pid) is not int or pid <= 0 or type(expected_start) is not str:
        return False
    try:
        process = psutil.Process(pid)
        actual_start = f"{process.create_time():.6f}"
        return process.is_running() and actual_start == expected_start
    except (psutil.Error, OSError, ValueError):
        return False


class TelegramConnectorError(RuntimeError):
    """Base error with deliberately non-sensitive messages."""


class TelegramContractError(ValueError):
    pass


class TelegramDenied(PermissionError):
    pass


class TelegramNotDispatched(TelegramConnectorError):
    """Proof that no provider request was invoked."""


class TelegramProviderRejected(TelegramConnectorError):
    """The provider supplied a known terminal rejection."""


class TelegramOutcomeUnknown(TelegramConnectorError):
    """The provider may have accepted the request; reconciliation is required."""


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise TelegramContractError(f"{label} is invalid")
    return value


def _chat_id(value: object, label: str = "chat_id") -> str:
    if type(value) is not str or not value or value.startswith("+"):
        raise TelegramContractError(f"{label} is invalid")
    try:
        number = int(value, 10)
    except ValueError as exc:
        raise TelegramContractError(f"{label} is invalid") from exc
    if (
        str(number) != value
        or number == 0
        or not -(2**63) <= number <= (2**63) - 1
    ):
        raise TelegramContractError(f"{label} is invalid")
    return value


def _message_id(value: object) -> str:
    if type(value) is not str or not value.isascii() or not value.isdecimal():
        raise TelegramContractError("provider_message_id is invalid")
    number = int(value, 10)
    if number <= 0 or str(number) != value or number > 9_007_199_254_740_991:
        raise TelegramContractError("provider_message_id is invalid")
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise TelegramContractError("message text is invalid")
    if len(value) > MAX_TEXT_CHARACTERS:
        raise TelegramContractError("message text exceeds the character budget")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise TelegramContractError("message text exceeds the byte budget")
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise TelegramContractError("value is not canonical JSON") from exc


def _sha(value: bytes | object) -> str:
    raw = value if type(value) is bytes else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise TelegramContractError("an absolute outbox path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or (path.exists() and path.is_symlink()):
        raise TelegramDenied("linked outbox storage is forbidden")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(path.parent.stat(), "st_file_attributes", 0) & reparse:
        raise TelegramDenied("reparse-point outbox storage is forbidden")


def telegram_vault_reference_v1(
    owner_profile_id: str,
    workspace_id: str,
    account_id: str,
) -> SecretReference:
    """Return the only accepted OS-vault alias for an exact account scope."""

    owner = _identifier(owner_profile_id, "owner_profile_id")
    workspace = _identifier(workspace_id, "workspace_id")
    account = _identifier(account_id, "account_id")
    scope = _canonical(
        {
            "schema": "OnyxTelegramVaultScope.v1",
            "owner_profile_id": owner,
            "workspace_id": workspace,
            "account_id": account,
        }
    )
    return SecretReference(
        TELEGRAM_VAULT_SERVICE,
        "scope." + hashlib.sha256(scope).hexdigest(),
        "Onyx Telegram bot credential",
    )


@dataclass(frozen=True, slots=True)
class TelegramFeatureGateV1:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TelegramContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "TelegramFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class TelegramBudgetV1:
    maximum_request_bytes: int = MAX_REQUEST_BYTES
    maximum_response_bytes: int = MAX_RESPONSE_BYTES
    timeout_seconds: float = 20.0
    maximum_document_bytes: int = MAX_DOCUMENT_BYTES

    def __post_init__(self) -> None:
        if type(self.maximum_document_bytes) is not int or not 1 <= self.maximum_document_bytes <= MAX_DOCUMENT_BYTES:
            raise TelegramContractError("maximum_document_bytes is outside its bound")
        if type(self.maximum_request_bytes) is not int or not 1 <= self.maximum_request_bytes <= MAX_REQUEST_BYTES:
            raise TelegramContractError("maximum_request_bytes is outside its bound")
        if type(self.maximum_response_bytes) is not int or not 1 <= self.maximum_response_bytes <= MAX_RESPONSE_BYTES:
            raise TelegramContractError("maximum_response_bytes is outside its bound")
        if type(self.timeout_seconds) not in {int, float} or isinstance(self.timeout_seconds, bool):
            raise TelegramContractError("timeout_seconds is invalid")
        if not math.isfinite(float(self.timeout_seconds)) or not 0.01 <= float(self.timeout_seconds) <= MAX_TIMEOUT_SECONDS:
            raise TelegramContractError("timeout_seconds is outside its bound")


class TelegramCancellationV1:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class TelegramAccountV1:
    account_id: str
    owner_profile_id: str
    workspace_id: str
    secret_reference: SecretReference
    allowed_chat_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        account = _identifier(self.account_id, "account_id")
        owner = _identifier(self.owner_profile_id, "owner_profile_id")
        workspace = _identifier(self.workspace_id, "workspace_id")
        if type(self.secret_reference) is not SecretReference:
            raise TelegramContractError("exact SecretReference is required")
        expected = telegram_vault_reference_v1(owner, workspace, account)
        if self.secret_reference != expected:
            raise TelegramDenied("Telegram vault alias is outside the exact account scope")
        if type(self.allowed_chat_ids) is not tuple or not self.allowed_chat_ids:
            raise TelegramContractError("allowed chats are required")
        checked = tuple(_chat_id(item) for item in self.allowed_chat_ids)
        if len(set(checked)) != len(checked):
            raise TelegramContractError("duplicate chat scope")


@dataclass(frozen=True, slots=True)
class TelegramMessageV1:
    operation_id: str
    account_id: str
    owner_profile_id: str
    workspace_id: str
    chat_id: str
    text: str
    parse_mode: None = None

    def __post_init__(self) -> None:
        _identifier(self.operation_id, "operation_id")
        _identifier(self.account_id, "account_id")
        _identifier(self.owner_profile_id, "owner_profile_id")
        _identifier(self.workspace_id, "workspace_id")
        _chat_id(self.chat_id)
        _text(self.text)
        if self.parse_mode is not None:
            raise TelegramDenied("Telegram V1 permits plain text only")

    @property
    def content_digest(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def request_digest(self) -> str:
        return _sha(
            {
                "schema": "OnyxTelegramSendMessage.v1",
                "operation_id": self.operation_id,
                "account_id": self.account_id,
                "owner_profile_id": self.owner_profile_id,
                "workspace_id": self.workspace_id,
                "chat_id": self.chat_id,
                "content_digest": self.content_digest,
                "parse_mode": None,
            }
        )

    def provider_payload(self) -> dict[str, object]:
        return {
            "chat_id": self.chat_id,
            "text": self.text,
            "link_preview_options": {"is_disabled": True},
        }


@dataclass(frozen=True, slots=True)
class TelegramDocumentV1:
    """Immutable upload preview. Approval binds request_digest, not just a chat.

    PDF signature checks are format guards, not a malware/content certification.
    The Bot API does not echo a SHA-256: receipts bind the locally uploaded bytes
    to the returned Message and document metadata, not to a downloaded copy.
    """

    operation_id: str
    account_id: str
    owner_profile_id: str
    workspace_id: str
    chat_id: str
    filename: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        for label in ("operation_id", "account_id", "owner_profile_id", "workspace_id"):
            _identifier(getattr(self, label), label)
        _chat_id(self.chat_id)
        if type(self.filename) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.pdf", self.filename) is None:
            raise TelegramContractError("document filename must be a safe PDF basename")
        if type(self.content) is not bytes or not 1 <= len(self.content) <= MAX_DOCUMENT_BYTES:
            raise TelegramContractError("document bytes exceed the bound")
        if not self.content.startswith(b"%PDF-") or not self.content.rstrip().endswith(b"%%EOF"):
            raise TelegramContractError("document PDF signature is invalid")

    @property
    def content_digest(self) -> str:
        return _sha(self.content)

    @property
    def request_digest(self) -> str:
        return _sha({
            "schema": "OnyxTelegramSendDocument.v1",
            "operation_id": self.operation_id,
            "account_id": self.account_id,
            "owner_profile_id": self.owner_profile_id,
            "workspace_id": self.workspace_id,
            "chat_id": self.chat_id,
            "filename": self.filename,
            "content_digest": self.content_digest,
            "size_bytes": len(self.content),
            "mime_type": "application/pdf",
        })


def prepare_telegram_document_v1(
    *, operation_id: str, account: TelegramAccountV1, chat_id: str,
    pdf_path: Path | str, allowed_root: Path | str,
    expected_content_digest: str,
    budget: TelegramBudgetV1 = TelegramBudgetV1(),
) -> TelegramDocumentV1:
    """Read one local PDF under the owner-selected root into a bounded snapshot.

    Supply the digest of the generated/previewed artifact. All ancestors and the
    file must be unlinked; metadata/identity are checked around the bounded read.
    No path is resolved through a link and no path survives into the transport.
    """
    if type(account) is not TelegramAccountV1 or type(budget) is not TelegramBudgetV1:
        raise TelegramContractError("document dependencies are invalid")
    _identifier(operation_id, "operation_id")
    if _chat_id(chat_id) not in account.allowed_chat_ids:
        raise TelegramDenied("chat is outside the approved account scope")
    if type(expected_content_digest) is not str or _DIGEST.fullmatch(expected_content_digest) is None:
        raise TelegramContractError("expected_content_digest is invalid")
    for value in (pdf_path, allowed_root):
        if not isinstance(value, (str, Path)):
            raise TelegramContractError("document path is invalid")
        raw = str(value)
        path = Path(value)
        if (not path.is_absolute() or ".." in path.parts or "\x00" in raw
                or raw.startswith(("\\\\", "//")) or ":" in raw[len(path.drive):]):
            raise TelegramDenied("document requires a local absolute path")
    path, root = Path(pdf_path), Path(allowed_root)
    if path == root or not path.is_relative_to(root) or path.suffix != ".pdf":
        raise TelegramDenied("document is outside the PDF root scope")

    def checked_stat(candidate: Path, *, directory: bool) -> os.stat_result:
        info = candidate.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise TelegramDenied("linked document paths are forbidden")
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise TelegramDenied("document path type is invalid")
        if not directory and info.st_nlink != 1:
            raise TelegramDenied("hard-linked documents are forbidden")
        return info

    def identity(info: os.stat_result) -> tuple[int, int]:
        return info.st_dev, info.st_ino

    def version(info: os.stat_result) -> tuple[int, int, int, int]:
        # Windows Python versions can expose creation time from lstat's ctime
        # but change time from fstat's ctime. Compare ctime only within one API.
        return (*identity(info), info.st_size, info.st_mtime_ns)

    try:
        ancestors = [(item, checked_stat(item, directory=True)) for item in reversed(path.parents)]
        before = checked_stat(path, directory=False)
        if not 1 <= before.st_size <= budget.maximum_document_bytes:
            raise TelegramContractError("document size exceeds the budget")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or version(opened) != version(before):
                raise TelegramDenied("document changed before read")
            content = stream.read(budget.maximum_document_bytes + 1)
            after_read = os.fstat(stream.fileno())
            if (version(after_read) != version(opened) or after_read.st_nlink != 1
                    or after_read.st_ctime_ns != opened.st_ctime_ns):
                raise TelegramDenied("document changed during read")
        after = checked_stat(path, directory=False)
        if version(after) != version(before) or after.st_ctime_ns != before.st_ctime_ns:
            raise TelegramDenied("document changed during read")
        for item, info in ancestors:
            if identity(checked_stat(item, directory=True)) != identity(info):
                raise TelegramDenied("document ancestor changed during read")
    except TelegramDenied:
        raise
    except OSError:
        raise TelegramDenied("document unavailable or unsafe") from None
    if len(content) != before.st_size or len(content) > budget.maximum_document_bytes:
        raise TelegramDenied("document size changed during read")
    if _sha(content) != expected_content_digest:
        raise TelegramDenied("document content digest diverged")
    return TelegramDocumentV1(operation_id, account.account_id, account.owner_profile_id,
                              account.workspace_id, chat_id, path.name, content)


def _document_multipart(message: TelegramDocumentV1, budget: TelegramBudgetV1) -> tuple[bytes, str]:
    if len(message.content) > budget.maximum_document_bytes:
        raise TelegramNotDispatched("document_budget_exceeded")
    boundary = "OnyxPDF" + secrets.token_hex(24)
    if boundary.encode("ascii") in message.content:
        raise TelegramNotDispatched("multipart_boundary_collision")
    prefix = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{message.chat_id}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="disable_content_type_detection"\r\n\r\ntrue\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{message.filename}"\r\n'
        'Content-Type: application/pdf\r\n\r\n'
    ).encode("ascii")
    suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
    # Retain the text request ceiling as the multipart envelope budget.
    if len(prefix) + len(suffix) > budget.maximum_request_bytes:
        raise TelegramNotDispatched("request_budget_exceeded")
    return prefix + message.content + suffix, f"multipart/form-data; boundary={boundary}"


@dataclass(frozen=True, slots=True)
class TelegramProviderReceiptV1:
    provider_message_id: str
    chat_id: str
    content_digest: str
    accepted_at: float

    def __post_init__(self) -> None:
        _message_id(self.provider_message_id)
        _chat_id(self.chat_id)
        if type(self.content_digest) is not str or _DIGEST.fullmatch(self.content_digest) is None:
            raise TelegramContractError("content_digest is invalid")
        if type(self.accepted_at) not in {int, float} or isinstance(self.accepted_at, bool):
            raise TelegramContractError("accepted_at is invalid")
        if not math.isfinite(float(self.accepted_at)) or float(self.accepted_at) <= 0:
            raise TelegramContractError("accepted_at is invalid")


@dataclass(frozen=True, slots=True)
class TelegramDispatchV1:
    operation_id: str
    status: str
    request_digest: str
    content_digest: str
    provider_message_id: str | None
    detail: str

    def receipt_payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxTelegramDispatch.v1",
            "operation_id": self.operation_id,
            "status": self.status,
            "request_digest": self.request_digest,
            "content_digest": self.content_digest,
            "provider_message_id": self.provider_message_id,
            "detail": self.detail,
        }


class TelegramReconciliationDecisionV1(StrEnum):
    CONFIRMED_ACCEPTED = "confirmed_accepted"
    CONFIRMED_NOT_DISPATCHED = "confirmed_not_dispatched"


@dataclass(frozen=True, slots=True)
class TelegramReconciliationProofV1:
    operation_id: str
    decision: TelegramReconciliationDecisionV1
    chat_id: str
    content_digest: str
    provider_message_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.operation_id, "operation_id")
        if type(self.decision) is not TelegramReconciliationDecisionV1:
            raise TelegramContractError("reconciliation decision is invalid")
        _chat_id(self.chat_id)
        if type(self.content_digest) is not str or _DIGEST.fullmatch(self.content_digest) is None:
            raise TelegramContractError("content_digest is invalid")
        if self.decision is TelegramReconciliationDecisionV1.CONFIRMED_ACCEPTED:
            _message_id(self.provider_message_id)
        elif self.provider_message_id is not None:
            raise TelegramContractError("not-dispatched proof cannot bind a message")


class TelegramTransportV1(Protocol):
    def send(
        self,
        account: TelegramAccountV1,
        message: TelegramMessageV1 | TelegramDocumentV1,
        budget: TelegramBudgetV1,
        cancellation: TelegramCancellationV1,
    ) -> TelegramProviderReceiptV1: ...


class StdlibTelegramTransportV1:
    """Wire dependencies; public sending is intentionally impossible."""

    def __init__(
        self,
        *,
        vault_reader: Callable[[SecretReference], bytes | None],
        connection_factory: Callable[..., http.client.HTTPSConnection] = http.client.HTTPSConnection,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not callable(vault_reader) or not callable(connection_factory) or not callable(clock):
            raise TelegramContractError("transport dependencies are invalid")
        self._vault_reader = vault_reader
        self._connection_factory = connection_factory
        self._clock = clock
        self.background_workers = 0
        self.retry_count = 0

    def send(
        self,
        account: TelegramAccountV1,
        message: TelegramMessageV1 | TelegramDocumentV1,
        budget: TelegramBudgetV1,
        cancellation: TelegramCancellationV1,
    ) -> TelegramProviderReceiptV1:
        del account, message, budget, cancellation
        raise TelegramNotDispatched("outbox_dispatch_required")

class TelegramOfficialOutboxV1:
    """Durable, at-most-once Telegram send and reconciliation boundary."""

    _DDL_V1 = (
        """CREATE TABLE messages(
          operation_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
          owner_profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
          chat_id TEXT NOT NULL, request_digest TEXT NOT NULL,
          content_digest TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN
          ('reserved','dispatching','accepted','rejected','not_dispatched','reconciliation')),
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
    _DDL = (
        """CREATE TABLE messages(
          operation_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
          owner_profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
          chat_id TEXT NOT NULL, request_digest TEXT NOT NULL,
          content_digest TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN
          ('reserved','dispatching','accepted','rejected','not_dispatched','reconciliation')),
          provider_message_id TEXT, detail TEXT NOT NULL,
          dispatch_nonce TEXT NOT NULL, lease_owner_instance_id TEXT NOT NULL,
          lease_owner_pid INTEGER NOT NULL, lease_owner_start TEXT NOT NULL,
          lease_expires_at REAL NOT NULL,
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
    _SCHEMA_VERSION = 2

    def __init__(
        self,
        path: Path | str,
        *,
        gate: TelegramFeatureGateV1 = TelegramFeatureGateV1(),
        clock: Callable[[], float] = time.time,
    ) -> None:
        if type(gate) is not TelegramFeatureGateV1 or not gate.enabled:
            raise TelegramDenied("Telegram connector is disabled")
        if not callable(clock):
            raise TelegramContractError("clock is invalid")
        self.path = Path(path)
        _private_path(self.path)
        self._clock = clock
        self._lock = threading.RLock()
        self._instance_id = "telegram_outbox_" + secrets.token_hex(24)
        self._process_id = os.getpid()
        self._process_start_marker = _PROCESS_START_MARKER
        self._closed = False
        self.background_workers = 0
        self.polling_interval = None
        self.webhook_listener = None
        with _LIVE_OUTBOX_LOCK:
            _LIVE_OUTBOXES[self._instance_id] = self
        try:
            self._initialize()
        except BaseException:
            self.close()
            raise

        def send_stdlib(
            transport: StdlibTelegramTransportV1,
            validate_dispatch: Callable[[], None],
            account: TelegramAccountV1,
            message: TelegramMessageV1 | TelegramDocumentV1,
            budget: TelegramBudgetV1,
            cancellation: TelegramCancellationV1,
        ) -> TelegramProviderReceiptV1:
            validate_dispatch()
            if cancellation.cancelled:
                raise TelegramNotDispatched("cancelled_before_dispatch")
            try:
                secret = transport._vault_reader
                secret = secret(account.secret_reference)
            except Exception:
                raise TelegramNotDispatched("credential_unavailable") from None
            if type(secret) is not bytes or _TOKEN.fullmatch(secret) is None:
                raise TelegramNotDispatched("credential_unavailable")
            if type(message) is TelegramDocumentV1:
                body, content_type = _document_multipart(message, budget)
                method = "sendDocument"
            else:
                body = _canonical(message.provider_payload())
                content_type = "application/json"
                method = "sendMessage"
                if len(body) > budget.maximum_request_bytes:
                    raise TelegramNotDispatched("request_budget_exceeded")
            if cancellation.cancelled:
                raise TelegramNotDispatched("cancelled_before_dispatch")
            try:
                token = secret.decode("ascii")
            except UnicodeDecodeError:
                raise TelegramNotDispatched("credential_unavailable") from None
            try:
                connection = transport._connection_factory(
                    TELEGRAM_ORIGIN,
                    443,
                    timeout=float(budget.timeout_seconds),
                    context=ssl.create_default_context(),
                )
            except Exception:
                raise TelegramNotDispatched("connection_unavailable") from None
            dispatched = False
            try:
                if cancellation.cancelled:
                    raise TelegramNotDispatched("cancelled_before_dispatch")
                validate_dispatch()
                if cancellation.cancelled:
                    raise TelegramNotDispatched("cancelled_before_dispatch")
                dispatched = True
                connection.request(
                    "POST",
                    f"/bot{token}/{method}",
                    body=body,
                    headers={
                        "Content-Type": content_type,
                        "User-Agent": "Cyryx-Onyx/1.1",
                    },
                )
                response = connection.getresponse()
                raw = response.read(budget.maximum_response_bytes + 1)
            except TelegramNotDispatched:
                raise
            except Exception:
                if dispatched:
                    raise TelegramOutcomeUnknown(
                        "provider_outcome_unknown"
                    ) from None
                raise TelegramNotDispatched("request_not_dispatched") from None
            finally:
                try:
                    connection.close()
                except Exception:
                    pass
            if cancellation.cancelled:
                raise TelegramOutcomeUnknown("provider_outcome_unknown")
            if len(raw) > budget.maximum_response_bytes:
                raise TelegramOutcomeUnknown("provider_response_budget_exceeded")
            if 300 <= response.status < 400:
                raise TelegramProviderRejected("redirect_forbidden")
            if type(message) is TelegramDocumentV1 and response.status >= 500:
                raise TelegramOutcomeUnknown("provider_outcome_unknown")
            if response.status < 200 or response.status >= 300:
                raise TelegramProviderRejected("provider_rejected")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise TelegramOutcomeUnknown("provider_receipt_invalid") from None
            if type(payload) is not dict:
                raise TelegramOutcomeUnknown("provider_receipt_invalid")
            if type(message) is TelegramDocumentV1 and payload.get("ok") is not True:
                if payload.get("ok") is False and type(payload.get("error_code")) is int and 400 <= payload["error_code"] < 500:
                    raise TelegramProviderRejected("provider_rejected")
                raise TelegramOutcomeUnknown("provider_receipt_invalid")
            if payload.get("ok") is not True:
                raise TelegramProviderRejected("provider_rejected")
            result = payload.get("result")
            if type(result) is not dict or type(result.get("chat")) is not dict:
                raise TelegramOutcomeUnknown("provider_receipt_invalid")
            raw_message_id = result.get("message_id")
            raw_chat_id = result["chat"].get("id")
            if (
                type(raw_message_id) is not int
                or isinstance(raw_message_id, bool)
                or raw_message_id <= 0
            ):
                raise TelegramOutcomeUnknown("provider_receipt_invalid")
            if type(raw_chat_id) is not int or isinstance(raw_chat_id, bool):
                raise TelegramOutcomeUnknown("provider_receipt_invalid")
            provider_message_id = str(raw_message_id)
            receipt_chat_id = str(raw_chat_id)
            if receipt_chat_id != message.chat_id:
                raise TelegramOutcomeUnknown("provider_receipt_binding_diverged")
            if type(message) is TelegramDocumentV1:
                document = result.get("document")
                if (type(document) is not dict
                        or any(type(document.get(key)) is not str or not document[key]
                               for key in ("file_id", "file_unique_id"))
                        or document.get("file_name") != message.filename
                        or document.get("mime_type") != "application/pdf"
                        or type(document.get("file_size")) is not int
                        or document["file_size"] != len(message.content)
                        or result.get("caption") not in (None, "")):
                    raise TelegramOutcomeUnknown("provider_receipt_binding_diverged")
            elif result.get("text") != message.text:
                raise TelegramOutcomeUnknown("provider_receipt_binding_diverged")
            return TelegramProviderReceiptV1(
                provider_message_id,
                receipt_chat_id,
                message.content_digest,
                float(transport._clock()),
            )

        def dispatch_from_outbox(
            transport: TelegramTransportV1,
            account: TelegramAccountV1,
            message: TelegramMessageV1 | TelegramDocumentV1,
            budget: TelegramBudgetV1,
            cancellation: TelegramCancellationV1,
            dispatch_nonce: str,
            validate_approval: Callable[[], None] | None = None,
        ) -> TelegramProviderReceiptV1:
            def validate() -> None:
                self._validate_active_dispatch(message, dispatch_nonce)
                if validate_approval is not None:
                    validate_approval()

            validate()
            if type(transport) is StdlibTelegramTransportV1:
                return send_stdlib(
                    transport, validate, account, message, budget, cancellation
                )
            return transport.send(account, message, budget, cancellation)

        self.__dispatch_from_outbox = dispatch_from_outbox

    def _connect(self) -> sqlite3.Connection:
        _private_path(self.path)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def close(self) -> None:
        if getattr(self, "_closed", True):
            return
        self._closed = True
        with _LIVE_OUTBOX_LOCK:
            current = _LIVE_OUTBOXES.get(self._instance_id)
            if current is self:
                _LIVE_OUTBOXES.pop(self._instance_id, None)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def _lease_owner_live(row: sqlite3.Row) -> bool:
        owner_id = str(row["lease_owner_instance_id"])
        owner_pid = int(row["lease_owner_pid"])
        owner_start = str(row["lease_owner_start"])
        if owner_pid == os.getpid():
            if owner_start != _PROCESS_START_MARKER:
                return False
            with _LIVE_OUTBOX_LOCK:
                owner = _LIVE_OUTBOXES.get(owner_id)
            return owner is not None and not bool(getattr(owner, "_closed", True))
        return _pid_alive(owner_pid, owner_start)

    def _validate_active_dispatch(
        self, message: TelegramMessageV1 | TelegramDocumentV1, dispatch_nonce: str
    ) -> None:
        if self._closed:
            raise TelegramNotDispatched("outbox_closed")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM messages WHERE operation_id=?",
                (message.operation_id,),
            ).fetchone()
        now = float(self._clock())
        if (
            row is None
            or str(row["status"]) != "dispatching"
            or str(row["dispatch_nonce"]) != dispatch_nonce
            or str(row["lease_owner_instance_id"]) != self._instance_id
            or int(row["lease_owner_pid"]) != self._process_id
            or str(row["lease_owner_start"]) != self._process_start_marker
            or float(row["lease_expires_at"]) <= now
            or str(row["account_id"]) != message.account_id
            or str(row["owner_profile_id"]) != message.owner_profile_id
            or str(row["workspace_id"]) != message.workspace_id
            or str(row["chat_id"]) != message.chat_id
            or str(row["request_digest"]) != message.request_digest
            or str(row["content_digest"]) != message.content_digest
        ):
            raise TelegramNotDispatched("durable_dispatch_lease_invalid")

    def _reconciliation_owned_or_abandoned(
        self, row: sqlite3.Row, now: float
    ) -> bool:
        if str(row["lease_owner_instance_id"]) == self._instance_id:
            return True
        return (
            float(row["lease_expires_at"]) <= now
            and not self._lease_owner_live(row)
        )

    @staticmethod
    def _normalized_sql(value: str) -> str:
        return "".join(value.split()).lower()

    @classmethod
    def _validate_schema_signature(
        cls, connection: sqlite3.Connection, ddl: tuple[str, ...]
    ) -> None:
        expected = {
            ("table", "messages"): cls._normalized_sql(ddl[0]),
            ("table", "message_events"): cls._normalized_sql(ddl[1]),
            ("trigger", "message_events_no_update"): cls._normalized_sql(ddl[2]),
            ("trigger", "message_events_no_delete"): cls._normalized_sql(ddl[3]),
        }
        rows = connection.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        actual = {
            (str(row["type"]), str(row["name"])): cls._normalized_sql(
                str(row["sql"])
            )
            for row in rows
        }
        if actual != expected:
            raise TelegramConnectorError("outbox schema signature is invalid")

    @staticmethod
    def _validate_event_chain(connection: sqlite3.Connection) -> None:
        previous = "0" * 64
        expected_seq = 1
        rows = connection.execute(
            "SELECT seq,operation_id,occurred_at,event,detail_json,prev_hash,event_hash FROM message_events ORDER BY seq"
        ).fetchall()
        for row in rows:
            if int(row["seq"]) != expected_seq:
                raise TelegramConnectorError("message event sequence is invalid")
            detail_json = str(row["detail_json"])
            try:
                detail = json.loads(detail_json)
            except json.JSONDecodeError as exc:
                raise TelegramConnectorError(
                    "message event detail is invalid"
                ) from exc
            if (
                type(detail) is not dict
                or _canonical(detail).decode("ascii") != detail_json
                or str(row["prev_hash"]) != previous
            ):
                raise TelegramConnectorError("message event chain is invalid")
            expected_hash = _sha(
                {
                    "operation_id": str(row["operation_id"]),
                    "occurred_at": float(row["occurred_at"]),
                    "event": str(row["event"]),
                    "detail_json": detail_json,
                    "prev_hash": previous,
                }
            )
            if str(row["event_hash"]) != expected_hash:
                raise TelegramConnectorError("message event chain is invalid")
            previous = expected_hash
            expected_seq += 1

    def _migrate_v1(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN EXCLUSIVE")
        try:
            self._validate_schema_signature(connection, self._DDL_V1)
            self._validate_event_chain(connection)
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise TelegramConnectorError("outbox integrity failed")
            legacy_rows = connection.execute(
                "SELECT * FROM messages ORDER BY operation_id"
            ).fetchall()
            connection.execute("ALTER TABLE messages RENAME TO messages_v1")
            connection.execute(self._DDL[0])
            now = float(self._clock())
            migrated_events: list[tuple[str, str, str]] = []
            for row in legacy_rows:
                prior_status = str(row["status"])
                status = prior_status
                detail = str(row["detail"])
                updated_at = float(row["updated_at"])
                lease_expires_at = now
                if prior_status == "reserved":
                    status = "not_dispatched"
                    detail = "legacy_v1_reserved_migrated_not_dispatched"
                    updated_at = now
                    migrated_events.append(
                        (str(row["operation_id"]), status, detail)
                    )
                elif prior_status == "dispatching":
                    status = "reconciliation"
                    detail = "legacy_v1_dispatching_migrated_reconciliation"
                    updated_at = now
                    lease_expires_at = now + MINIMUM_LEASE_SECONDS
                    migrated_events.append(
                        (str(row["operation_id"]), status, detail)
                    )
                elif prior_status == "reconciliation":
                    lease_expires_at = now + MINIMUM_LEASE_SECONDS
                connection.execute(
                    "INSERT INTO messages(operation_id,account_id,owner_profile_id,workspace_id,chat_id,request_digest,content_digest,status,provider_message_id,detail,dispatch_nonce,lease_owner_instance_id,lease_owner_pid,lease_owner_start,lease_expires_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(row["operation_id"]),
                        str(row["account_id"]),
                        str(row["owner_profile_id"]),
                        str(row["workspace_id"]),
                        str(row["chat_id"]),
                        str(row["request_digest"]),
                        str(row["content_digest"]),
                        status,
                        (
                            None
                            if row["provider_message_id"] is None
                            else str(row["provider_message_id"])
                        ),
                        detail,
                        secrets.token_hex(32),
                        self._instance_id,
                        self._process_id,
                        self._process_start_marker,
                        lease_expires_at,
                        float(row["created_at"]),
                        updated_at,
                    ),
                )
            connection.execute("DROP TABLE messages_v1")
            for operation_id, status, reason in migrated_events:
                self._event(
                    connection,
                    operation_id,
                    f"telegram.{status}",
                    {"reason": reason, "schema_migration": "v1_to_v2"},
                    now,
                )
            connection.execute(f"PRAGMA user_version={self._SCHEMA_VERSION}")
            self._validate_schema_signature(connection, self._DDL)
            self._validate_event_chain(connection)
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise TelegramConnectorError("outbox integrity failed")
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchone()[0]
            )
            if version == 0 and count == 0:
                connection.execute("BEGIN EXCLUSIVE")
                try:
                    for statement in self._DDL:
                        connection.execute(statement)
                    connection.execute(
                        f"PRAGMA user_version={self._SCHEMA_VERSION}"
                    )
                    connection.execute("COMMIT")
                except BaseException:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
            elif version == 1:
                self._migrate_v1(connection)
            elif version != self._SCHEMA_VERSION or count == 0:
                raise TelegramConnectorError("outbox schema version is invalid")
            self._validate_schema_signature(connection, self._DDL)
            self._validate_event_chain(connection)
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise TelegramConnectorError("outbox integrity failed")
            interrupted = connection.execute(
                "SELECT * FROM messages WHERE status IN ('reserved','dispatching')"
            ).fetchall()
            if interrupted:
                now = float(self._clock())
                connection.execute("BEGIN IMMEDIATE")
                for row in interrupted:
                    if (
                        float(row["lease_expires_at"]) > now
                        or self._lease_owner_live(row)
                    ):
                        continue
                    operation_id = str(row["operation_id"])
                    prior_status = str(row["status"])
                    target = (
                        "not_dispatched"
                        if prior_status == "reserved"
                        else "reconciliation"
                    )
                    reason = (
                        "reserved_before_dispatch"
                        if prior_status == "reserved"
                        else "prior_dispatch_interrupted"
                    )
                    changed = connection.execute(
                        "UPDATE messages SET status=?,detail=?,dispatch_nonce=?,lease_owner_instance_id=?,lease_owner_pid=?,lease_owner_start=?,lease_expires_at=?,updated_at=? WHERE operation_id=? AND status=? AND lease_owner_instance_id=?",
                        (
                            target,
                            reason,
                            secrets.token_hex(32),
                            self._instance_id,
                            self._process_id,
                            self._process_start_marker,
                            now + MINIMUM_LEASE_SECONDS,
                            now,
                            operation_id,
                            prior_status,
                            str(row["lease_owner_instance_id"]),
                        ),
                    )
                    if changed.rowcount == 1:
                        self._event(
                            connection,
                            operation_id,
                            f"telegram.{target}",
                            {"reason": reason},
                            now,
                        )
                connection.execute("COMMIT")

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
        detail_json = _canonical(dict(detail)).decode("ascii")
        event_hash = _sha(
            {
                "operation_id": operation_id,
                "occurred_at": now,
                "event": event,
                "detail_json": detail_json,
                "prev_hash": prev_hash,
            }
        )
        connection.execute(
            "INSERT INTO message_events(operation_id,occurred_at,event,detail_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
            (operation_id, now, event, detail_json, prev_hash, event_hash),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TelegramDispatchV1:
        return TelegramDispatchV1(
            str(row["operation_id"]),
            str(row["status"]),
            str(row["request_digest"]),
            str(row["content_digest"]),
            None if row["provider_message_id"] is None else str(row["provider_message_id"]),
            str(row["detail"]),
        )

    def _set_status(
        self,
        operation_id: str,
        status: str,
        detail: str,
        *,
        event: str,
        provider_message_id: str | None = None,
        event_detail: Mapping[str, object] | None = None,
        expected_status: str = "dispatching",
    ) -> TelegramDispatchV1:
        now = float(self._clock())
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE messages SET status=?,provider_message_id=?,detail=?,updated_at=? WHERE operation_id=? AND status=? AND lease_owner_instance_id=?",
                (
                    status,
                    provider_message_id,
                    detail,
                    now,
                    operation_id,
                    expected_status,
                    self._instance_id,
                ),
            )
            if changed.rowcount == 1:
                self._event(connection, operation_id, event, event_detail or {}, now)
            row = connection.execute(
                "SELECT * FROM messages WHERE operation_id=?", (operation_id,)
            ).fetchone()
            connection.execute("COMMIT")
        if row is None:
            raise TelegramConnectorError("message operation disappeared")
        return self._from_row(row)

    def _after_dispatching_commit(self) -> None:
        """Test failpoint: production leaves the atomic boundary untouched."""

    def send_message(
        self,
        *,
        operation_id: str,
        account: TelegramAccountV1,
        chat_id: str,
        text: str,
        authority: Callable[[str, str, str, str, str], bool],
        transport: TelegramTransportV1,
        budget: TelegramBudgetV1 = TelegramBudgetV1(),
        cancellation: TelegramCancellationV1 | None = None,
        parse_mode: None = None,
    ) -> TelegramDispatchV1:
        if self._closed:
            raise TelegramDenied("Telegram outbox is closed")
        if type(account) is not TelegramAccountV1 or not callable(authority):
            raise TelegramContractError("Telegram dependencies are invalid")
        if type(budget) is not TelegramBudgetV1:
            raise TelegramContractError("budget must be exact")
        cancel = TelegramCancellationV1() if cancellation is None else cancellation
        if type(cancel) is not TelegramCancellationV1:
            raise TelegramContractError("cancellation must be exact")
        message = TelegramMessageV1(
            _identifier(operation_id, "operation_id"),
            account.account_id,
            account.owner_profile_id,
            account.workspace_id,
            _chat_id(chat_id),
            _text(text),
            parse_mode,
        )
        return self._send_prepared(
            message=message, account=account, authority=authority, transport=transport,
            budget=budget, cancellation=cancel,
        )

    def send_document(
        self,
        *,
        document: TelegramDocumentV1,
        account: TelegramAccountV1,
        authority: Callable[[str, str, str, str, str], bool],
        owner_approval: Callable[[str], bool],
        transport: TelegramTransportV1,
        budget: TelegramBudgetV1 = TelegramBudgetV1(),
        cancellation: TelegramCancellationV1 | None = None,
    ) -> TelegramDispatchV1:
        """Upload the exact preview through the existing durable send boundary.

        owner_approval(request_digest) must verify a current owner approval for
        this exact PDF, filename, operation, recipient and account scope. It is
        checked before reservation and again at the wire boundary, and therefore
        must be repeatable (not a consume-on-read callback). Central authority
        still gates official_message.send. Reconciliation uses the existing API.
        No captions, URL/file_id sends, retries, or live activation are added.
        """
        if type(document) is not TelegramDocumentV1 or not callable(owner_approval):
            raise TelegramContractError("exact document and owner approval are required")
        document.__post_init__()
        return self._send_prepared(
            message=document, account=account, authority=authority, transport=transport,
            budget=budget, cancellation=cancellation, owner_approval=owner_approval,
        )

    def _send_prepared(
        self, *, message: TelegramMessageV1 | TelegramDocumentV1,
        account: TelegramAccountV1,
        authority: Callable[[str, str, str, str, str], bool],
        transport: TelegramTransportV1, budget: TelegramBudgetV1,
        cancellation: TelegramCancellationV1 | None,
        owner_approval: Callable[[str], bool] | None = None,
    ) -> TelegramDispatchV1:
        if self._closed:
            raise TelegramDenied("Telegram outbox is closed")
        if type(account) is not TelegramAccountV1 or not callable(authority):
            raise TelegramContractError("Telegram dependencies are invalid")
        if type(budget) is not TelegramBudgetV1:
            raise TelegramContractError("budget must be exact")
        cancel = TelegramCancellationV1() if cancellation is None else cancellation
        if type(cancel) is not TelegramCancellationV1:
            raise TelegramContractError("cancellation must be exact")
        if (message.account_id, message.owner_profile_id, message.workspace_id) != (
                account.account_id, account.owner_profile_id, account.workspace_id):
            raise TelegramDenied("document account scope diverged")
        if message.chat_id not in account.allowed_chat_ids:
            raise TelegramDenied("chat is outside the approved account scope")
        decision = authority(
            account.owner_profile_id,
            account.workspace_id,
            "official_message.send",
            account.account_id,
            message.chat_id,
        )
        if type(decision) is not bool or not decision:
            raise TelegramDenied("central authority denied the message")

        validate_approval = None
        if type(message) is TelegramDocumentV1:
            if owner_approval is None:
                raise TelegramDenied("exact document owner approval is required")
            if len(message.content) > budget.maximum_document_bytes:
                raise TelegramContractError("document size exceeds the budget")
            approved_digest = message.request_digest
            if owner_approval(approved_digest) is not True:
                raise TelegramDenied("owner denied the exact document request")

            def validate_approval() -> None:
                try:
                    decision = authority(account.owner_profile_id, account.workspace_id,
                                         "official_message.send", account.account_id, message.chat_id)
                    if (decision is not True or owner_approval(approved_digest) is not True
                            or message.request_digest != approved_digest
                            or message.chat_id not in account.allowed_chat_ids):
                        raise TelegramNotDispatched("document_approval_invalid")
                except Exception:
                    raise TelegramNotDispatched("document_approval_invalid") from None

            if message.request_digest != approved_digest:
                raise TelegramDenied("approved document request changed")

        now = float(self._clock())
        dispatch_nonce = secrets.token_hex(32)
        lease_expires_at = now + max(
            MINIMUM_LEASE_SECONDS, float(budget.timeout_seconds) + 30.0
        )
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM messages WHERE operation_id=?", (message.operation_id,)
            ).fetchone()
            if existing is not None:
                if str(existing["request_digest"]) != message.request_digest:
                    connection.execute("ROLLBACK")
                    raise TelegramDenied("idempotency key is bound to another request")
                connection.execute("COMMIT")
                return self._from_row(existing)
            connection.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    message.operation_id,
                    message.account_id,
                    message.owner_profile_id,
                    message.workspace_id,
                    message.chat_id,
                    message.request_digest,
                    message.content_digest,
                    "dispatching",
                    None,
                    "dispatching_committed_before_provider",
                    dispatch_nonce,
                    self._instance_id,
                    self._process_id,
                    self._process_start_marker,
                    lease_expires_at,
                    now,
                    now,
                ),
            )
            self._event(
                connection,
                message.operation_id,
                "telegram.reserved",
                {
                    "provider": "telegram",
                    "chat_digest": _sha(message.chat_id.encode("ascii")),
                    "content_digest": message.content_digest,
                },
                now,
            )
            self._event(
                connection,
                message.operation_id,
                "telegram.dispatching",
                {},
                now,
            )
            connection.execute("COMMIT")

        self._after_dispatching_commit()
        if cancel.cancelled:
            return self._set_status(
                message.operation_id,
                "not_dispatched",
                "cancelled_before_dispatch",
                event="telegram.not_dispatched",
            )
        try:
            receipt = self.__dispatch_from_outbox(
                transport, account, message, budget, cancel, dispatch_nonce, validate_approval
            )
            if type(message) is TelegramDocumentV1 and cancel.cancelled:
                raise TelegramOutcomeUnknown("provider_outcome_unknown")
            if type(receipt) is not TelegramProviderReceiptV1:
                raise TelegramOutcomeUnknown("provider_receipt_invalid")
            if (
                receipt.chat_id != message.chat_id
                or receipt.content_digest != message.content_digest
            ):
                raise TelegramOutcomeUnknown("provider_receipt_binding_diverged")
        except TelegramNotDispatched:
            return self._set_status(
                message.operation_id,
                "not_dispatched",
                "provider_not_invoked",
                event="telegram.not_dispatched",
            )
        except TelegramProviderRejected:
            return self._set_status(
                message.operation_id,
                "rejected",
                "provider_rejected",
                event="telegram.rejected",
            )
        except Exception:
            return self._set_status(
                message.operation_id,
                "reconciliation",
                "provider_outcome_unknown",
                event="telegram.reconciliation",
            )
        return self._set_status(
            message.operation_id,
            "accepted",
            "provider_receipt_verified",
            event="telegram.accepted",
            provider_message_id=receipt.provider_message_id,
            event_detail={
                "provider_message_id": receipt.provider_message_id,
                "content_digest": message.content_digest,
            },
        )

    def status(self, operation_id: str) -> TelegramDispatchV1:
        key = _identifier(operation_id, "operation_id")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM messages WHERE operation_id=?", (key,)
            ).fetchone()
        if row is None:
            raise TelegramDenied("message operation is unavailable")
        return self._from_row(row)

    def reconcile(
        self,
        proof: TelegramReconciliationProofV1,
        *,
        authority: Callable[[str, str, str, str, str], bool],
    ) -> TelegramDispatchV1:
        if type(proof) is not TelegramReconciliationProofV1 or not callable(authority):
            raise TelegramContractError("reconciliation dependencies are invalid")
        # This first read provides only the scope needed to ask central
        # authority.  It is not used as the state-transition precondition.
        with closing(self._connect()) as connection:
            preliminary = connection.execute(
                "SELECT * FROM messages WHERE operation_id=?", (proof.operation_id,)
            ).fetchone()
        if preliminary is None:
            raise TelegramDenied("message operation is unavailable")
        if (
            str(preliminary["chat_id"]) != proof.chat_id
            or str(preliminary["content_digest"]) != proof.content_digest
        ):
            raise TelegramDenied("reconciliation proof binding diverged")
        if not self._reconciliation_owned_or_abandoned(
            preliminary, float(self._clock())
        ):
            raise TelegramDenied("reconciliation lease is owned by a live instance")
        decision = authority(
            str(preliminary["owner_profile_id"]),
            str(preliminary["workspace_id"]),
            "official_message.reconcile",
            str(preliminary["account_id"]),
            str(preliminary["chat_id"]),
        )
        if type(decision) is not bool or not decision:
            raise TelegramDenied("central authority denied reconciliation")
        accepted = (
            proof.decision
            is TelegramReconciliationDecisionV1.CONFIRMED_ACCEPTED
        )
        target = "accepted" if accepted else "not_dispatched"
        detail = (
            "reconciled_provider_receipt"
            if accepted
            else "reconciled_not_dispatched"
        )
        event = (
            "telegram.reconciled_accepted"
            if accepted
            else "telegram.reconciled_not_dispatched"
        )
        provider_message_id = proof.provider_message_id if accepted else None
        now = float(self._clock())
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM messages WHERE operation_id=?",
                    (proof.operation_id,),
                ).fetchone()
                if row is None:
                    raise TelegramDenied("message operation is unavailable")
                if str(row["status"]) != "reconciliation":
                    raise TelegramDenied(
                        "message operation does not require reconciliation"
                    )
                if (
                    str(row["chat_id"]) != proof.chat_id
                    or str(row["content_digest"]) != proof.content_digest
                    or str(row["owner_profile_id"])
                    != str(preliminary["owner_profile_id"])
                    or str(row["workspace_id"])
                    != str(preliminary["workspace_id"])
                    or str(row["account_id"]) != str(preliminary["account_id"])
                ):
                    raise TelegramDenied("reconciliation proof binding diverged")
                if not self._reconciliation_owned_or_abandoned(row, now):
                    raise TelegramDenied(
                        "reconciliation lease is owned by a live instance"
                    )
                prior_owner = str(row["lease_owner_instance_id"])
                changed = connection.execute(
                    "UPDATE messages SET status=?,provider_message_id=?,detail=?,lease_owner_instance_id=?,lease_owner_pid=?,lease_owner_start=?,lease_expires_at=?,updated_at=? WHERE operation_id=? AND status='reconciliation' AND lease_owner_instance_id=?",
                    (
                        target,
                        provider_message_id,
                        detail,
                        self._instance_id,
                        self._process_id,
                        self._process_start_marker,
                        now,
                        now,
                        proof.operation_id,
                        prior_owner,
                    ),
                )
                if changed.rowcount != 1:
                    raise TelegramDenied("reconciliation state changed")
                self._event(
                    connection,
                    proof.operation_id,
                    event,
                    (
                        {"provider_message_id": provider_message_id}
                        if accepted
                        else {}
                    ),
                    now,
                )
                final = connection.execute(
                    "SELECT * FROM messages WHERE operation_id=?",
                    (proof.operation_id,),
                ).fetchone()
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        if final is None:
            raise TelegramConnectorError("message operation disappeared")
        return self._from_row(final)


__all__ = [
    "FEATURE_FLAG",
    "TELEGRAM_ORIGIN",
    "TelegramFeatureGateV1",
    "TelegramBudgetV1",
    "TelegramCancellationV1",
    "TelegramAccountV1",
    "TelegramMessageV1",
    "TelegramDocumentV1",
    "MAX_DOCUMENT_BYTES",
    "prepare_telegram_document_v1",
    "TelegramProviderReceiptV1",
    "TelegramDispatchV1",
    "TelegramReconciliationDecisionV1",
    "TelegramReconciliationProofV1",
    "TelegramTransportV1",
    "StdlibTelegramTransportV1",
    "TelegramOfficialOutboxV1",
    "TelegramConnectorError",
    "TelegramContractError",
    "TelegramDenied",
    "TelegramNotDispatched",
    "TelegramProviderRejected",
    "TelegramOutcomeUnknown",
    "telegram_vault_reference_v1",
]
