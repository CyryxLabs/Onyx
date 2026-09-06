"""Default-off host anchor for a future immutable domain-ledger schema.

M2b-a intentionally has no SQLite or runtime integration.  A trusted host owns
the injected :class:`LedgerAnchorPort`; this module only seals snapshots from
that port into a native-vault state and an owner-only HMAC journal.

Security boundary: this provides integrity discipline against accidental or
offline journal tampering, not a Python sandbox.  Arbitrary code in this process
can monkeypatch Python, and another process running as the same OS user can use
that user's native credential vault.  Neither case is claimed to be protected.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import ctypes
import re
import secrets
import stat
import struct
import threading
import time
import weakref
from collections import deque
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol, runtime_checkable

from core import native_vault
from core.control_plane import (
    ControlPlaneError,
    _WindowsNamedMutex,
    _apply_file_permissions,
    _assert_path_identity,
    _identity_from_stat,
    _prepare_parent,
    _reject_link_chain,
)
from core.native_vault import (
    NativeSecretVault,
    NativeVaultError,
    SecretReference,
)
from core.paths import PrivateDataPathError, private_control_plane_runtime_dir


LEDGER_ANCHOR_FLAG = "ONYX_M2B_LEDGER_ANCHOR_V1"
JOURNAL_FILENAME = "ledger_anchor.v1.journal"
_JOURNAL_MAGIC = b"ONXLAJ1\0"
_FRAME_HEADER = struct.Struct(">8sI")
_MAC_BYTES = 32
_KEY_BYTES = 32
_MAX_FRAME_PAYLOAD = 8192
_MAX_VAULT_STATE = 4096
_MAX_JSON_DEPTH = 16
_MAX_JSON_ITEMS = 256
_MAX_JSON_STRING = 1024
# The active journal is kept small; older generations are immutable,
# content-addressed archives validated by the cold history audit.
_MAX_JOURNAL_BYTES = 1 << 50
_MAX_JOURNAL_FRAMES = 1 << 40
_ACTIVE_JOURNAL_MAX_BYTES = 1024 * 1024
_ACTIVE_JOURNAL_MAX_FRAMES = 512
_MAX_ENCODED_FRAME_BYTES = _FRAME_HEADER.size + _MAX_FRAME_PAYLOAD + _MAC_BYTES
_LOCK_TIMEOUT_SECONDS = 5.0
_MAX_LOCK_TIMEOUT_SECONDS = 30.0
_ZERO_MAC = "0" * 64
_DIGEST = re.compile(r"[0-9a-f]{64}")
_DATABASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_COUNT_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TRANSITIONS = frozenset(
    {
        "bootstrap",
        "checkpoint",
        "prepare",
        "finalize",
        "recover_finalize",
        "recover_rollback",
    }
)
_RECORD_KEYS = frozenset(
    {
        "contract",
        "database_id",
        "entity_counts",
        "event_count",
        "ledger_root",
        "nonce",
        "previous_record_hmac",
        "record_hmac",
        "schema_fingerprint",
        "sequence",
    }
)
_STATE_KEYS = frozenset({"committed", "contract", "database_id", "prepared"})
_PENDING_KEYS = frozenset(
    {
        "contract",
        "database_id",
        "entity_counts",
        "event_count",
        "ledger_root",
        "nonce",
        "schema_fingerprint",
    }
)
_FRAME_KEYS = frozenset({"contract", "frame_sequence", "state", "transition"})
_CHECKPOINT_KEYS = frozenset(
    {
        "archive_bytes",
        "archive_sha256",
        "generation",
        "previous_head_sha256",
        "previous_tail_hmac",
        "previous_tail_sequence",
    }
)
_FRAME_V2_KEYS = _FRAME_KEYS | {"checkpoint"}
_HEAD_KEYS = frozenset(
    {
        "active_first_frame_bytes",
        "active_first_frame_sha256",
        "active_frame_count",
        "active_sha256",
        "archive_chain_sha256",
        "archive_sha256",
        "contract",
        "generation",
        "head_hmac",
        "state",
        "tail_hmac",
        "tail_offset",
        "tail_sequence",
    }
)
_RECORD_DOMAIN = b"ONYX-LEDGER-ANCHOR-RECORD-V1\0"
_FRAME_DOMAIN = b"ONYX-LEDGER-ANCHOR-JOURNAL-FRAME-V1\0"
_HEAD_DOMAIN = b"ONYX-LEDGER-ANCHOR-VAULT-HEAD-V2\0"
_ARCHIVE_CHAIN_DOMAIN = b"ONYX-LEDGER-ANCHOR-ARCHIVE-CHAIN-V1\0"
_THREAD_LOCK = threading.Lock()
_SESSION_LOCAL = threading.local()
_CAPABILITY_SEAL = object()
_TICKET_SEAL = object()
_ANCHOR_CONSTRUCTOR_SEAL = object()
_WRITER_SESSION_SEAL = object()
_ISSUED_OWNER_CAPABILITIES: weakref.WeakKeyDictionary[
    OwnerCapability, bytes
] = weakref.WeakKeyDictionary()
_ISSUED_PREPARED_TICKETS: weakref.WeakKeyDictionary[
    PreparedTicket, tuple[bytes, int, str]
] = weakref.WeakKeyDictionary()


class LedgerAnchorError(RuntimeError):
    """Base error with a message safe for readiness/UI output."""


class LedgerAnchorDisabled(LedgerAnchorError):
    """Raised unless the M2b-a flag is explicitly enabled."""


class LedgerAnchorUnavailable(LedgerAnchorError):
    """Raised until the reviewed M2b-b canonical database port exists."""


class LedgerAnchorContractError(LedgerAnchorError):
    """Raised when a host port or caller violates the anchor contract."""


class LedgerAnchorIntegrityError(LedgerAnchorError):
    """Raised for a forged, corrupt, truncated, or divergent anchor."""


class LedgerAnchorConflict(LedgerAnchorError):
    """Raised for an invalid state-machine transition or stale ticket."""


class LedgerAnchorVaultError(LedgerAnchorError):
    """Raised when the native owner vault is missing or unavailable."""


class LedgerAnchorIOError(LedgerAnchorError):
    """Raised when the fixed private journal cannot be used safely."""


class _JournalDirectoryCapability(Protocol):
    """Narrow bootstrap-only access to one already-pinned journal directory."""

    def open_anchor_file(self, name: str, *, create: bool) -> int: ...

    @classmethod
    def descriptor_identity(cls, descriptor: int) -> tuple[int, ...]: ...


def ledger_anchor_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(LEDGER_ANCHOR_FLAG, "").strip().casefold() in {"1", "true"}


def _ledger_anchor_journal_path() -> Path:
    try:
        return Path(private_control_plane_runtime_dir()) / JOURNAL_FILENAME
    except PrivateDataPathError as exc:
        raise LedgerAnchorIOError("Could not resolve the fixed private anchor path") from exc


def _validate_json(value: object, *, depth: int = 0, budget: list[int] | None = None) -> None:
    if budget is None:
        budget = [0]
    if depth > _MAX_JSON_DEPTH:
        raise LedgerAnchorContractError("Anchor JSON exceeds the nesting limit")
    budget[0] += 1
    if budget[0] > _MAX_JSON_ITEMS:
        raise LedgerAnchorContractError("Anchor JSON exceeds the item limit")
    if value is None or type(value) in {bool, int}:
        return
    if isinstance(value, str):
        if len(value) > _MAX_JSON_STRING or "\x00" in value:
            raise LedgerAnchorContractError("Anchor JSON string is invalid")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, depth=depth + 1, budget=budget)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 80 or "\x00" in key:
                raise LedgerAnchorContractError("Anchor JSON key is invalid")
            _validate_json(item, depth=depth + 1, budget=budget)
        return
    raise LedgerAnchorContractError("Anchor JSON contains an unsupported value")


def _canonical(value: object, *, limit: int = _MAX_FRAME_PAYLOAD) -> bytes:
    _validate_json(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise LedgerAnchorContractError("Anchor JSON could not be encoded") from exc
    if not encoded or len(encoded) > limit:
        raise LedgerAnchorContractError("Anchor JSON exceeds the byte limit")
    return encoded


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LedgerAnchorIntegrityError("Anchor JSON contains a duplicate key")
        result[key] = value
    return result


def _parse_canonical(raw: bytes, *, limit: int) -> dict[str, object]:
    if not isinstance(raw, bytes) or not raw or len(raw) > limit:
        raise LedgerAnchorIntegrityError("Anchor JSON size is invalid")
    try:
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(decoded, object_pairs_hook=_object_pairs)
    except LedgerAnchorIntegrityError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LedgerAnchorIntegrityError("Anchor JSON is malformed") from exc
    if not isinstance(value, dict):
        raise LedgerAnchorIntegrityError("Anchor JSON root must be an object")
    try:
        if _canonical(value, limit=limit) != raw:
            raise LedgerAnchorIntegrityError("Anchor JSON is not canonical")
    except LedgerAnchorContractError as exc:
        raise LedgerAnchorIntegrityError(str(exc)) from exc
    return value


def _counts(value: Mapping[str, int] | object) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, Mapping) or len(value) > 32:
        raise LedgerAnchorContractError("Anchor entity counts are invalid")
    result: list[tuple[str, int]] = []
    for key, count in value.items():
        if not isinstance(key, str) or not _COUNT_NAME.fullmatch(key):
            raise LedgerAnchorContractError("Anchor entity-count name is invalid")
        if type(count) is not int or not 0 <= count <= 2**63 - 1:
            raise LedgerAnchorContractError("Anchor entity count is invalid")
        result.append((key, count))
    result.sort()
    return tuple(result)


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    database_id: str
    schema_fingerprint: str
    ledger_root: str
    event_count: int
    entity_counts: tuple[tuple[str, int], ...]

    def __init__(
        self,
        database_id: str,
        schema_fingerprint: str,
        ledger_root: str,
        event_count: int,
        entity_counts: Mapping[str, int],
    ):
        if not isinstance(database_id, str) or not _DATABASE_ID.fullmatch(database_id):
            raise LedgerAnchorContractError("Anchor database_id is invalid")
        if not isinstance(schema_fingerprint, str) or not _DIGEST.fullmatch(
            schema_fingerprint
        ):
            raise LedgerAnchorContractError("Anchor schema fingerprint is invalid")
        if not isinstance(ledger_root, str) or not _DIGEST.fullmatch(ledger_root):
            raise LedgerAnchorContractError("Anchor ledger root is invalid")
        if type(event_count) is not int or not 0 <= event_count <= 2**63 - 1:
            raise LedgerAnchorContractError("Anchor event count is invalid")
        object.__setattr__(self, "database_id", database_id)
        object.__setattr__(self, "schema_fingerprint", schema_fingerprint)
        object.__setattr__(self, "ledger_root", ledger_root)
        object.__setattr__(self, "event_count", event_count)
        object.__setattr__(self, "entity_counts", _counts(entity_counts))

    def count_map(self) -> dict[str, int]:
        return dict(self.entity_counts)


@runtime_checkable
class LedgerAnchorPort(Protocol):
    """Trusted host-owned view of the current transaction/database snapshot."""

    def snapshot(self) -> LedgerSnapshot:
        ...


@runtime_checkable
class SecretVaultPort(Protocol):
    def get_bytes(self) -> bytes | None:
        ...

    def set_bytes(self, secret: bytes | bytearray) -> None:
        ...

    def delete(self) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class AnchorRecord:
    database_id: str
    schema_fingerprint: str
    ledger_root: str
    event_count: int
    entity_counts: tuple[tuple[str, int], ...]
    sequence: int
    previous_record_hmac: str
    nonce: str
    record_hmac: str

    def snapshot(self) -> LedgerSnapshot:
        return LedgerSnapshot(
            self.database_id,
            self.schema_fingerprint,
            self.ledger_root,
            self.event_count,
            dict(self.entity_counts),
        )

    def base_object(self) -> dict[str, object]:
        return {
            "contract": "AnchorRecord.v1",
            "database_id": self.database_id,
            "entity_counts": dict(self.entity_counts),
            "event_count": self.event_count,
            "ledger_root": self.ledger_root,
            "nonce": self.nonce,
            "previous_record_hmac": self.previous_record_hmac,
            "schema_fingerprint": self.schema_fingerprint,
            "sequence": self.sequence,
        }

    def as_object(self) -> dict[str, object]:
        return {**self.base_object(), "record_hmac": self.record_hmac}


@dataclass(frozen=True, slots=True)
class AnchorStatus:
    database_id: str
    sequence: int
    ledger_root: str
    schema_fingerprint: str
    event_count: int
    prepared: bool


class OwnerCapability:
    __slots__ = ("_instance_token", "_seal", "__weakref__")

    def __init__(self, instance_token: bytes, seal: object):
        if seal is not _CAPABILITY_SEAL:
            raise TypeError("OwnerCapability cannot be constructed directly")
        self._instance_token = instance_token
        self._seal = seal

    def __copy__(self):
        raise TypeError("OwnerCapability cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("OwnerCapability cannot be copied")

    def __reduce__(self):
        raise TypeError("OwnerCapability cannot be serialized")

    def __repr__(self) -> str:
        return "<OwnerCapability sealed>"


class PreparedTicket:
    __slots__ = (
        "_instance_token",
        "_record_hmac",
        "_seal",
        "_sequence",
        "__weakref__",
    )

    def __init__(
        self,
        instance_token: bytes,
        sequence: int,
        record_hmac: str,
        seal: object,
    ):
        if seal is not _TICKET_SEAL:
            raise TypeError("PreparedTicket cannot be constructed directly")
        self._instance_token = instance_token
        self._sequence = sequence
        self._record_hmac = record_hmac
        self._seal = seal

    def __copy__(self):
        raise TypeError("PreparedTicket cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("PreparedTicket cannot be copied")

    def __reduce__(self):
        raise TypeError("PreparedTicket cannot be serialized")

    @property
    def sequence(self) -> int:
        return self._sequence

    def __repr__(self) -> str:
        return f"<PreparedTicket sequence={self._sequence} sealed>"


@dataclass(frozen=True, slots=True)
class _VaultState:
    database_id: str
    committed: AnchorRecord | None
    prepared: AnchorRecord | None

    def as_object(self) -> dict[str, object]:
        return {
            "committed": self.committed.as_object() if self.committed else None,
            "contract": "AnchorVaultState.v1",
            "database_id": self.database_id,
            "prepared": self.prepared.as_object() if self.prepared else None,
        }


@dataclass(frozen=True, slots=True)
class _BootstrapPending:
    snapshot: LedgerSnapshot
    nonce: str

    def as_object(self) -> dict[str, object]:
        return {
            "contract": "AnchorBootstrapPending.v1",
            "database_id": self.snapshot.database_id,
            "entity_counts": self.snapshot.count_map(),
            "event_count": self.snapshot.event_count,
            "ledger_root": self.snapshot.ledger_root,
            "nonce": self.nonce,
            "schema_fingerprint": self.snapshot.schema_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class _JournalFrame:
    frame_sequence: int
    transition: str
    state: _VaultState
    frame_hmac: bytes
    end_offset: int


@dataclass(frozen=True, slots=True)
class _JournalRead:
    frames: tuple[_JournalFrame, ...]
    partial_offset: int | None
    size: int


@dataclass(frozen=True, slots=True)
class _JournalHead:
    state: _VaultState
    generation: int
    archive_sha256: str
    archive_chain_sha256: str
    tail_sequence: int
    tail_hmac: bytes
    tail_offset: int
    active_frame_count: int
    active_sha256: str
    active_first_frame_bytes: int
    active_first_frame_sha256: str

    def base_object(self) -> dict[str, object]:
        return {
            "active_first_frame_bytes": self.active_first_frame_bytes,
            "active_first_frame_sha256": self.active_first_frame_sha256,
            "active_frame_count": self.active_frame_count,
            "active_sha256": self.active_sha256,
            "archive_chain_sha256": self.archive_chain_sha256,
            "archive_sha256": self.archive_sha256,
            "contract": "AnchorVaultHead.v2",
            "generation": self.generation,
            "state": self.state.as_object(),
            "tail_hmac": self.tail_hmac.hex(),
            "tail_offset": self.tail_offset,
            "tail_sequence": self.tail_sequence,
        }


def _head_bytes(head: _JournalHead, key: bytes) -> bytes:
    base = head.base_object()
    digest = hmac.new(key, _HEAD_DOMAIN + _canonical(base), hashlib.sha256).hexdigest()
    return _canonical({**base, "head_hmac": digest}, limit=_MAX_VAULT_STATE)


def _head_from_bytes(raw: bytes, key: bytes) -> _JournalHead:
    value = _parse_canonical(raw, limit=_MAX_VAULT_STATE)
    if set(value) != _HEAD_KEYS or value.get("contract") != "AnchorVaultHead.v2":
        raise LedgerAnchorIntegrityError("Anchor vault head shape is invalid")
    base = {name: item for name, item in value.items() if name != "head_hmac"}
    supplied_hmac = value.get("head_hmac")
    if not isinstance(supplied_hmac, str) or not _DIGEST.fullmatch(supplied_hmac):
        raise LedgerAnchorIntegrityError("Anchor vault head HMAC is invalid")
    expected_hmac = hmac.new(
        key, _HEAD_DOMAIN + _canonical(base), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_hmac, supplied_hmac):
        raise LedgerAnchorIntegrityError("Anchor vault head HMAC is invalid")
    generation = value.get("generation")
    tail_sequence = value.get("tail_sequence")
    tail_offset = value.get("tail_offset")
    active_frame_count = value.get("active_frame_count")
    active_sha256 = value.get("active_sha256")
    first_bytes = value.get("active_first_frame_bytes")
    archive_sha256 = value.get("archive_sha256")
    archive_chain_sha256 = value.get("archive_chain_sha256")
    first_sha256 = value.get("active_first_frame_sha256")
    tail_hmac = value.get("tail_hmac")
    if (
        type(generation) is not int
        or generation < 0
        or type(tail_sequence) is not int
        or tail_sequence < 0
        or type(tail_offset) is not int
        or tail_offset <= 0
        or type(active_frame_count) is not int
        or active_frame_count <= 0
        or not isinstance(active_sha256, str)
        or not _DIGEST.fullmatch(active_sha256)
        or type(first_bytes) is not int
        or first_bytes <= 0
        or not isinstance(archive_sha256, str)
        or not _DIGEST.fullmatch(archive_sha256)
        or not isinstance(archive_chain_sha256, str)
        or not _DIGEST.fullmatch(archive_chain_sha256)
        or not isinstance(first_sha256, str)
        or not _DIGEST.fullmatch(first_sha256)
        or not isinstance(tail_hmac, str)
        or not _DIGEST.fullmatch(tail_hmac)
    ):
        raise LedgerAnchorIntegrityError("Anchor vault head fields are invalid")
    return _JournalHead(
        _state_from_object(value.get("state"), key),
        generation,
        archive_sha256,
        archive_chain_sha256,
        tail_sequence,
        bytes.fromhex(tail_hmac),
        tail_offset,
        active_frame_count,
        active_sha256,
        first_bytes,
        first_sha256,
    )


def _record_for_snapshot(
    key: bytes,
    snapshot: LedgerSnapshot,
    *,
    sequence: int,
    previous_record_hmac: str,
    nonce: str,
) -> AnchorRecord:
    if len(key) != _KEY_BYTES:
        raise LedgerAnchorVaultError("Anchor key has an invalid size")
    if type(sequence) is not int or sequence < 0:
        raise LedgerAnchorContractError("Anchor sequence is invalid")
    if not _DIGEST.fullmatch(previous_record_hmac):
        raise LedgerAnchorContractError("Previous anchor HMAC is invalid")
    if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise LedgerAnchorContractError("Anchor nonce is invalid")
    provisional = AnchorRecord(
        snapshot.database_id,
        snapshot.schema_fingerprint,
        snapshot.ledger_root,
        snapshot.event_count,
        snapshot.entity_counts,
        sequence,
        previous_record_hmac,
        nonce,
        _ZERO_MAC,
    )
    digest = hmac.new(key, _RECORD_DOMAIN + _canonical(provisional.base_object()), hashlib.sha256)
    return AnchorRecord(
        provisional.database_id,
        provisional.schema_fingerprint,
        provisional.ledger_root,
        provisional.event_count,
        provisional.entity_counts,
        provisional.sequence,
        provisional.previous_record_hmac,
        provisional.nonce,
        digest.hexdigest(),
    )


def _record_from_object(value: object, key: bytes) -> AnchorRecord:
    if not isinstance(value, dict) or set(value) != _RECORD_KEYS:
        raise LedgerAnchorIntegrityError("Anchor record shape is invalid")
    try:
        snapshot = LedgerSnapshot(
            value.get("database_id"),
            value.get("schema_fingerprint"),
            value.get("ledger_root"),
            value.get("event_count"),
            value.get("entity_counts"),
        )
    except (TypeError, LedgerAnchorContractError) as exc:
        raise LedgerAnchorIntegrityError(str(exc)) from exc
    sequence = value.get("sequence")
    previous = value.get("previous_record_hmac")
    nonce = value.get("nonce")
    record_hmac = value.get("record_hmac")
    if (
        value.get("contract") != "AnchorRecord.v1"
        or type(sequence) is not int
        or sequence < 0
        or not isinstance(previous, str)
        or not _DIGEST.fullmatch(previous)
        or not isinstance(nonce, str)
        or not re.fullmatch(r"[0-9a-f]{32}", nonce)
        or not isinstance(record_hmac, str)
        or not _DIGEST.fullmatch(record_hmac)
    ):
        raise LedgerAnchorIntegrityError("Anchor record fields are invalid")
    expected = _record_for_snapshot(
        key,
        snapshot,
        sequence=sequence,
        previous_record_hmac=previous,
        nonce=nonce,
    )
    if not hmac.compare_digest(expected.record_hmac, record_hmac):
        raise LedgerAnchorIntegrityError("Anchor record HMAC is invalid")
    return AnchorRecord(
        snapshot.database_id,
        snapshot.schema_fingerprint,
        snapshot.ledger_root,
        snapshot.event_count,
        snapshot.entity_counts,
        sequence,
        previous,
        nonce,
        record_hmac,
    )


def _state_from_object(value: object, key: bytes) -> _VaultState:
    if not isinstance(value, dict) or set(value) != _STATE_KEYS:
        raise LedgerAnchorIntegrityError("Anchor vault-state shape is invalid")
    database_id = value.get("database_id")
    if (
        value.get("contract") != "AnchorVaultState.v1"
        or not isinstance(database_id, str)
        or not _DATABASE_ID.fullmatch(database_id)
    ):
        raise LedgerAnchorIntegrityError("Anchor vault-state fields are invalid")
    committed_value = value.get("committed")
    prepared_value = value.get("prepared")
    committed = (
        _record_from_object(committed_value, key) if committed_value is not None else None
    )
    prepared = (
        _record_from_object(prepared_value, key) if prepared_value is not None else None
    )
    if committed is None and prepared is None:
        raise LedgerAnchorIntegrityError("Anchor vault state is empty")
    if any(
        record.database_id != database_id
        for record in (committed, prepared)
        if record is not None
    ):
        raise LedgerAnchorIntegrityError("Anchor records cross database scope")
    if prepared is not None:
        expected_sequence = 0 if committed is None else committed.sequence + 1
        expected_previous = _ZERO_MAC if committed is None else committed.record_hmac
        if (
            prepared.sequence != expected_sequence
            or prepared.previous_record_hmac != expected_previous
        ):
            raise LedgerAnchorIntegrityError("Prepared anchor does not extend committed state")
    return _VaultState(database_id, committed, prepared)


def _state_bytes(state: _VaultState) -> bytes:
    return _canonical(state.as_object(), limit=_MAX_VAULT_STATE)


def _state_from_bytes(raw: bytes, key: bytes) -> _VaultState:
    return _state_from_object(_parse_canonical(raw, limit=_MAX_VAULT_STATE), key)


def _pending_bytes(pending: _BootstrapPending) -> bytes:
    return _canonical(pending.as_object(), limit=_MAX_VAULT_STATE)


def _pending_from_bytes(raw: bytes) -> _BootstrapPending:
    value = _parse_canonical(raw, limit=_MAX_VAULT_STATE)
    if set(value) != _PENDING_KEYS or value.get("contract") != "AnchorBootstrapPending.v1":
        raise LedgerAnchorIntegrityError("Anchor bootstrap-pending shape is invalid")
    nonce = value.get("nonce")
    if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise LedgerAnchorIntegrityError("Anchor bootstrap-pending nonce is invalid")
    try:
        snapshot = LedgerSnapshot(
            value.get("database_id"),
            value.get("schema_fingerprint"),
            value.get("ledger_root"),
            value.get("event_count"),
            value.get("entity_counts"),
        )
    except (TypeError, LedgerAnchorContractError) as exc:
        raise LedgerAnchorIntegrityError(str(exc)) from exc
    return _BootstrapPending(snapshot, nonce)


def _snapshot_matches(record: AnchorRecord, snapshot: LedgerSnapshot) -> bool:
    return record.snapshot() == snapshot


class _BoundedWindowsMutex(_WindowsNamedMutex):
    def __init__(self, target_path: Path, *, timeout: float = _LOCK_TIMEOUT_SECONDS):
        super().__init__(target_path)
        self.timeout = timeout

    def acquire(self) -> None:
        if os.name != "nt":
            return
        kernel32 = self._kernel32()
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise LedgerAnchorIOError("Could not create the anchor mutex")
        self.handle = int(handle)
        outcome = int(kernel32.WaitForSingleObject(handle, int(self.timeout * 1000)))
        if outcome == 0:
            self.acquired = True
            return
        if outcome == 0x80:
            self.acquired = True
            try:
                self.release()
            except BaseException:
                pass
            raise LedgerAnchorIOError("Anchor mutex was abandoned")
        try:
            self._close_handle()
        except BaseException:
            pass
        if outcome == 0x102:
            raise LedgerAnchorConflict("Timed out waiting for the anchor mutex")
        raise LedgerAnchorIOError("Anchor mutex wait failed")


class _AnchorFileLock:
    def __init__(
        self,
        journal_path: Path,
        *,
        timeout: float = _LOCK_TIMEOUT_SECONDS,
        directory_capability: _JournalDirectoryCapability | None = None,
    ):
        self.journal_path = journal_path
        self.timeout = timeout
        self.directory_capability = directory_capability
        self.lock_path = journal_path.with_suffix(journal_path.suffix + ".lock")
        self.descriptor: int | None = None
        self.mutex: _BoundedWindowsMutex | None = None
        self.os_locked = False

    def __enter__(self) -> "_AnchorFileLock":
        try:
            if os.name == "nt":
                # Keep the historical one-argument constructor contract used
                # by platform/fault adapters, then apply the bounded timeout.
                self.mutex = _BoundedWindowsMutex(self.journal_path)
                self.mutex.timeout = self.timeout
                self.mutex.acquire()
            if self.directory_capability is None:
                _prepare_parent(self.journal_path)
                _reject_link_chain(self.lock_path)
                flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(self.lock_path, flags, 0o600)
            else:
                descriptor = self.directory_capability.open_anchor_file(
                    self.lock_path.name, create=True
                )
            self.descriptor = descriptor
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise LedgerAnchorIOError("Anchor lock is not a regular file")
            if self.directory_capability is None:
                identity = _identity_from_stat(info)
                _assert_path_identity(self.lock_path, identity)
                _apply_file_permissions(descriptor, self.lock_path)
            if info.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name != "nt":
                import fcntl

                deadline = time.monotonic() + self.timeout
                while True:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        self.os_locked = True
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise LedgerAnchorConflict(
                                "Timed out waiting for the anchor file lock"
                            )
                        time.sleep(0.025)
            return self
        except LedgerAnchorError:
            self._cleanup()
            raise
        except (ControlPlaneError, OSError, ImportError) as exc:
            self._cleanup()
            raise LedgerAnchorIOError("Could not acquire the private anchor lock") from exc
        except BaseException:
            self._cleanup()
            raise

    def _cleanup(self) -> None:
        descriptor, self.descriptor = self.descriptor, None
        if descriptor is not None:
            if self.os_locked and os.name != "nt":
                try:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except BaseException:
                    pass
            self.os_locked = False
            try:
                os.close(descriptor)
            except BaseException:
                pass
        mutex, self.mutex = self.mutex, None
        if mutex is not None:
            try:
                mutex.release()
            except BaseException:
                pass

    def __exit__(self, *_exc: object) -> None:
        first: BaseException | None = None
        descriptor, self.descriptor = self.descriptor, None
        if descriptor is not None:
            try:
                if os.name != "nt":
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                    self.os_locked = False
            except (OSError, ImportError) as exc:
                first = exc
            try:
                os.close(descriptor)
            except OSError as exc:
                first = first or exc
        mutex, self.mutex = self.mutex, None
        if mutex is not None:
            try:
                mutex.release()
            except BaseException as exc:
                first = first or exc
        if first is not None:
            raise LedgerAnchorIOError("Could not release the private anchor lock") from first


@runtime_checkable
class _AnchorVaultFacade(Protocol):
    def read_key(self) -> bytes | None: ...

    def write_key(self, value: bytes) -> None: ...

    def read_head(self) -> bytes | None: ...

    def write_head(self, value: bytes) -> None: ...


class _TestingAnchorVaultFacade:
    def __init__(self, key_vault: SecretVaultPort, state_vault: SecretVaultPort):
        if not isinstance(key_vault, SecretVaultPort) or not isinstance(
            state_vault, SecretVaultPort
        ):
            raise TypeError("vaults must implement SecretVaultPort")
        self.__key = key_vault
        self.__head = state_vault

    def read_key(self) -> bytes | None:
        return self.__key.get_bytes()

    def write_key(self, value: bytes) -> None:
        self.__key.set_bytes(value)

    def read_head(self) -> bytes | None:
        return self.__head.get_bytes()

    def write_head(self, value: bytes) -> None:
        self.__head.set_bytes(value)


class _NativeAnchorVaultFacade:
    """Narrow production facade; raw native vault objects never leave it."""

    def __init__(self):
        capability = native_vault._bind_anchor_namespace_owner(self)
        self.__key = NativeSecretVault(
            SecretReference(
                "Onyx.DomainLedgerAnchorKey.v1",
                "owner",
                "Onyx domain-ledger anchor key",
            ),
            capability=capability,
        )
        self.__head = NativeSecretVault(
            SecretReference(
                "Onyx.DomainLedgerAnchorHead.v1",
                "owner",
                "Onyx domain-ledger anchor head",
            ),
            capability=capability,
        )

    def read_key(self) -> bytes | None:
        return self.__key.get_bytes()

    def write_key(self, value: bytes) -> None:
        self.__key.set_bytes(value)

    def read_head(self) -> bytes | None:
        return self.__head.get_bytes()

    def write_head(self, value: bytes) -> None:
        self.__head.set_bytes(value)


class LedgerAnchor:
    """Owner-capability guarded anchor state machine."""

    def __init__(
        self,
        port: LedgerAnchorPort,
        journal_path: Path,
        vault: _AnchorVaultFacade,
        *,
        _seal: object,
    ):
        if _seal is not _ANCHOR_CONSTRUCTOR_SEAL:
            raise TypeError("LedgerAnchor cannot be constructed directly")
        if not isinstance(port, LedgerAnchorPort):
            raise TypeError("port must implement LedgerAnchorPort")
        if not isinstance(vault, _AnchorVaultFacade):
            raise TypeError("vault must implement the private anchor vault facade")
        self._port = port
        self._journal_path = Path(journal_path)
        self.__vault = vault
        self._instance_token = secrets.token_bytes(32)
        self._used_tickets: deque[tuple[int, str]] = deque(maxlen=1024)

    @staticmethod
    def _fault(_point: str) -> None:
        """Deterministic crash-injection seam used only by tests."""

    def _assert_owner(self, owner: OwnerCapability) -> None:
        issued = _ISSUED_OWNER_CAPABILITIES.get(owner) if isinstance(owner, OwnerCapability) else None
        if (
            not isinstance(owner, OwnerCapability)
            or owner._seal is not _CAPABILITY_SEAL
            or issued is None
            or not hmac.compare_digest(issued, self._instance_token)
            or not hmac.compare_digest(owner._instance_token, self._instance_token)
        ):
            raise LedgerAnchorContractError("Owner capability is invalid")

    def _assert_ticket(self, ticket: PreparedTicket) -> None:
        if isinstance(ticket, PreparedTicket) and (
            ticket._sequence,
            ticket._record_hmac,
        ) in self._used_tickets:
            raise LedgerAnchorConflict("Prepared ticket was already consumed")
        issued = (
            _ISSUED_PREPARED_TICKETS.get(ticket)
            if isinstance(ticket, PreparedTicket)
            else None
        )
        if (
            not isinstance(ticket, PreparedTicket)
            or ticket._seal is not _TICKET_SEAL
            or issued != (self._instance_token, ticket._sequence, ticket._record_hmac)
            or not hmac.compare_digest(ticket._instance_token, self._instance_token)
        ):
            raise LedgerAnchorContractError("Prepared ticket is invalid")
        if (ticket._sequence, ticket._record_hmac) in self._used_tickets:
            raise LedgerAnchorConflict("Prepared ticket was already consumed")

    def _snapshot(self) -> LedgerSnapshot:
        try:
            snapshot = self._port.snapshot()
        except LedgerAnchorError:
            raise
        except Exception as exc:
            raise LedgerAnchorContractError("Host anchor port could not provide a snapshot") from exc
        if not isinstance(snapshot, LedgerSnapshot):
            raise LedgerAnchorContractError("Host anchor port returned an invalid snapshot")
        return snapshot

    @contextmanager
    def _locked(
        self,
        *,
        timeout: float = _LOCK_TIMEOUT_SECONDS,
        directory_capability: _JournalDirectoryCapability | None = None,
    ) -> Iterator[None]:
        if getattr(_SESSION_LOCAL, "active", None) is not None:
            raise LedgerAnchorConflict("Nested anchor lock/session use is forbidden")
        if not _THREAD_LOCK.acquire(timeout=timeout):
            raise LedgerAnchorConflict("Timed out waiting for the in-process anchor lock")
        try:
            with _AnchorFileLock(
                self._journal_path,
                timeout=timeout,
                directory_capability=directory_capability,
            ):
                yield
        finally:
            _THREAD_LOCK.release()

    def writer_session(
        self,
        owner: OwnerCapability,
        *,
        timeout: float = _LOCK_TIMEOUT_SECONDS,
    ) -> _LedgerAnchorWriterSession:
        """Create one owner-sealed, thread-bound transition session.

        The returned context manager acquires the process and OS anchor locks
        exactly once.  It exposes no callbacks and may be entered only once.
        """

        self._assert_owner(owner)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < float(timeout) <= _MAX_LOCK_TIMEOUT_SECONDS
        ):
            raise LedgerAnchorContractError("Writer-session timeout is invalid")
        return _LedgerAnchorWriterSession(
            self,
            owner,
            float(timeout),
            _seal=_WRITER_SESSION_SEAL,
        )

    def _open_journal(
        self,
        *,
        create: bool = False,
        directory_capability: _JournalDirectoryCapability | None = None,
    ) -> int:
        descriptor: int | None = None
        identity: tuple[int, ...] | None = None

        def cleanup() -> None:
            nonlocal descriptor, identity
            opened, descriptor = descriptor, None
            identity = None
            if opened is not None:
                try:
                    os.close(opened)
                except BaseException:
                    # Cleanup must never replace the primary exception,
                    # including cancellation-style BaseException objects.
                    pass

        try:
            if directory_capability is None:
                _reject_link_chain(self._journal_path)
                flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
                if create:
                    flags |= os.O_CREAT
                flags |= getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(self._journal_path, flags, 0o600)
            else:
                descriptor = directory_capability.open_anchor_file(
                    self._journal_path.name, create=create
                )
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise LedgerAnchorIOError("Anchor journal is not a regular file")
            if directory_capability is None:
                identity = _identity_from_stat(info)
                _assert_path_identity(self._journal_path, identity)
                _apply_file_permissions(descriptor, self._journal_path)
            else:
                identity = directory_capability.descriptor_identity(descriptor)
            opened, descriptor = descriptor, None
            identity = None
            return opened
        except LedgerAnchorError:
            cleanup()
            raise
        except (ControlPlaneError, OSError) as exc:
            cleanup()
            raise LedgerAnchorIOError("Could not securely open the anchor journal") from exc
        except BaseException:
            cleanup()
            raise

    @staticmethod
    def _read_exact(descriptor: int, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        try:
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except OSError as exc:
            raise LedgerAnchorIOError("Could not stream the anchor journal") from exc
        return b"".join(chunks)

    def _sha256_prefix(self, descriptor: int, length: int) -> str:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
        except OSError as exc:
            raise LedgerAnchorIOError("Could not inspect the anchor journal") from exc
        digest = hashlib.sha256()
        remaining = length
        while remaining:
            chunk = self._read_exact(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise LedgerAnchorIntegrityError("Anchor journal was truncated")
            digest.update(chunk)
            remaining -= len(chunk)
        return digest.hexdigest()

    def _archive_path(self, generation: int, digest: str) -> Path:
        return self._journal_path.with_name(
            f"{self._journal_path.name}.archive.{generation:08d}.{digest}"
        )

    @staticmethod
    def _write_all(descriptor: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise LedgerAnchorIOError("Anchor journal write made no progress")
            view = view[written:]

    def _read_active_bytes(self, descriptor: int) -> bytes:
        try:
            size = os.fstat(descriptor).st_size
            if size > _ACTIVE_JOURNAL_MAX_BYTES:
                raise LedgerAnchorIntegrityError(
                    "Anchor active generation exceeds the hard byte limit"
                )
            os.lseek(descriptor, 0, os.SEEK_SET)
        except OSError as exc:
            raise LedgerAnchorIOError("Could not inspect the anchor journal") from exc
        raw = self._read_exact(descriptor, size)
        if len(raw) != size:
            raise LedgerAnchorIntegrityError("Anchor journal was truncated")
        return raw

    def _read_secure_bounded_file(
        self,
        path: Path,
        *,
        limit: int,
        label: str,
        immutable: bool = False,
    ) -> bytes:
        """Read one owner-only regular file without following links or overallocating."""

        descriptor: int | None = None
        try:
            _reject_link_chain(path)
            before = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise LedgerAnchorIntegrityError(f"{label} is not a private regular file")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            identity = _identity_from_stat(opened)
            if (
                _identity_from_stat(before) != identity
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
            ):
                raise LedgerAnchorIntegrityError(f"{label} identity changed during open")
            _assert_path_identity(path, identity)
            if immutable and os.name != "nt":
                # Archives are created read-only.  A verifier must never make
                # them writable merely by reading them; reject a weakened mode
                # instead of repairing it to the active-file 0600 policy.
                if stat.S_IMODE(opened.st_mode) != 0o400:
                    raise LedgerAnchorIntegrityError(
                        f"{label} immutable permissions are invalid"
                    )
            else:
                _apply_file_permissions(descriptor, path)
            size = int(opened.st_size)
            if size < 0 or size > limit:
                raise LedgerAnchorIntegrityError(f"{label} exceeds its bounded size")
            chunks: list[bytes] = []
            remaining = size
            while remaining:
                chunk = self._read_exact(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    raise LedgerAnchorIntegrityError(f"{label} was truncated")
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            if _identity_from_stat(after) != identity or int(after.st_size) != size:
                raise LedgerAnchorIntegrityError(f"{label} changed during read")
            _assert_path_identity(path, identity)
            return b"".join(chunks)
        except LedgerAnchorError:
            raise
        except (ControlPlaneError, OSError) as exc:
            raise LedgerAnchorIOError(f"Could not securely read {label}") from exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _checkpoint_bytes(
        self,
        key: bytes,
        head: _JournalHead,
        raw_head: bytes,
        archive: bytes,
    ) -> tuple[bytes, _JournalFrame]:
        archive_sha256 = hashlib.sha256(archive).hexdigest()
        sequence = head.tail_sequence + 1
        payload = _canonical(
            {
                "checkpoint": {
                    "archive_bytes": len(archive),
                    "archive_sha256": archive_sha256,
                    "generation": head.generation + 1,
                    "previous_head_sha256": hashlib.sha256(raw_head).hexdigest(),
                    "previous_tail_hmac": head.tail_hmac.hex(),
                    "previous_tail_sequence": head.tail_sequence,
                },
                "contract": "AnchorJournalCheckpoint.v2",
                "frame_sequence": sequence,
                "state": head.state.as_object(),
                "transition": "checkpoint",
            }
        )
        length = struct.pack(">I", len(payload))
        frame_hmac = hmac.new(
            key, _FRAME_DOMAIN + head.tail_hmac + length + payload, hashlib.sha256
        ).digest()
        raw = _FRAME_HEADER.pack(_JOURNAL_MAGIC, len(payload)) + payload + frame_hmac
        return raw, _JournalFrame(
            sequence, "checkpoint", head.state, frame_hmac, len(raw)
        )

    def _adopt_successor(
        self,
        descriptor: int,
        key: bytes,
        raw_head: bytes,
        head: _JournalHead,
    ) -> _JournalHead | None:
        active = self._read_active_bytes(descriptor)
        if len(active) < _FRAME_HEADER.size + _MAC_BYTES:
            return None
        magic, payload_length = _FRAME_HEADER.unpack(active[: _FRAME_HEADER.size])
        expected_size = _FRAME_HEADER.size + payload_length + _MAC_BYTES
        if (
            magic != _JOURNAL_MAGIC
            or payload_length <= 0
            or payload_length > _MAX_FRAME_PAYLOAD
            or len(active) != expected_size
        ):
            return None
        payload = active[_FRAME_HEADER.size : _FRAME_HEADER.size + payload_length]
        frame_hmac = active[-_MAC_BYTES:]
        expected_hmac = hmac.new(
            key,
            _FRAME_DOMAIN
            + head.tail_hmac
            + struct.pack(">I", payload_length)
            + payload,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected_hmac, frame_hmac):
            return None
        value = _parse_canonical(payload, limit=_MAX_FRAME_PAYLOAD)
        if (
            set(value) != _FRAME_V2_KEYS
            or value.get("contract") != "AnchorJournalCheckpoint.v2"
            or value.get("transition") != "checkpoint"
            or value.get("frame_sequence") != head.tail_sequence + 1
        ):
            return None
        state = _state_from_object(value.get("state"), key)
        if not self._same_state(state, head.state):
            return None
        checkpoint = value.get("checkpoint")
        if not isinstance(checkpoint, dict) or set(checkpoint) != _CHECKPOINT_KEYS:
            return None
        archive_sha256 = checkpoint.get("archive_sha256")
        archive_bytes = checkpoint.get("archive_bytes")
        if (
            checkpoint.get("generation") != head.generation + 1
            or checkpoint.get("previous_head_sha256")
            != hashlib.sha256(raw_head).hexdigest()
            or checkpoint.get("previous_tail_hmac") != head.tail_hmac.hex()
            or checkpoint.get("previous_tail_sequence") != head.tail_sequence
            or type(archive_bytes) is not int
            or archive_bytes <= 0
            or not isinstance(archive_sha256, str)
            or not _DIGEST.fullmatch(archive_sha256)
        ):
            return None
        archive_path = self._archive_path(head.generation, archive_sha256)
        try:
            archive = self._read_secure_bounded_file(
                archive_path,
                limit=_ACTIVE_JOURNAL_MAX_BYTES,
                label="anchor successor archive",
                immutable=True,
            )
        except OSError as exc:
            raise LedgerAnchorIntegrityError(
                "Anchor successor is missing its immutable archive"
            ) from exc
        if len(archive) != archive_bytes or not hmac.compare_digest(
            hashlib.sha256(archive).hexdigest(), archive_sha256
        ):
            raise LedgerAnchorIntegrityError("Anchor successor archive is invalid")
        if len(archive) != head.tail_offset or not hmac.compare_digest(
            hashlib.sha256(archive).hexdigest(), head.active_sha256
        ):
            raise LedgerAnchorIntegrityError("Anchor successor archive tail is invalid")
        chain = hashlib.sha256(
            _ARCHIVE_CHAIN_DOMAIN
            + bytes.fromhex(head.archive_chain_sha256)
            + struct.pack(">Q", head.generation)
            + bytes.fromhex(archive_sha256)
        ).hexdigest()
        digest = hashlib.sha256(active).hexdigest()
        successor = _JournalHead(
            state,
            head.generation + 1,
            archive_sha256,
            chain,
            head.tail_sequence + 1,
            frame_hmac,
            len(active),
            1,
            digest,
            len(active),
            digest,
        )
        self._save_head(_head_bytes(successor, key))
        return successor

    @staticmethod
    def _windows_move_replace(source: Path, target: Path) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move = kernel32.MoveFileExW
        move.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
        move.restype = ctypes.c_int
        # MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
        if not move(os.fspath(source), os.fspath(target), 0x1 | 0x8):
            error = ctypes.get_last_error()
            raise OSError(error, "MoveFileExW replace/write-through failed")

    @staticmethod
    def _windows_flush_directory(path: Path) -> bool:
        """Best-effort directory flush; Windows/filesystems may reject it."""

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateFileW
        create.argtypes = (
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        )
        create.restype = ctypes.c_void_p
        handle = create(
            os.fspath(path),
            0x00000001,  # FILE_LIST_DIRECTORY
            0x1 | 0x2 | 0x4,  # read/write/delete sharing
            None,
            3,  # OPEN_EXISTING
            0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
            None,
        )
        invalid = ctypes.c_void_p(-1).value
        if handle in (None, invalid):
            return False
        try:
            flush = kernel32.FlushFileBuffers
            flush.argtypes = (ctypes.c_void_p,)
            flush.restype = ctypes.c_int
            return bool(flush(handle))
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))

    def _fsync_parent(self) -> bool:
        if os.name == "nt":
            return self._windows_flush_directory(self._journal_path.parent)
        descriptor = os.open(self._journal_path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True

    def _atomic_replace(self, source: Path, target: Path) -> bool:
        if os.name == "nt":
            self._windows_move_replace(source, target)
        else:
            os.replace(source, target)
        return self._fsync_parent()

    @staticmethod
    def _validate_transition(
        previous: _JournalFrame | None,
        transition: str,
        state: _VaultState,
    ) -> None:
        if previous is None:
            if (
                transition != "bootstrap"
                or state.committed is None
                or state.prepared is not None
                or state.committed.sequence != 0
                or state.committed.previous_record_hmac != _ZERO_MAC
            ):
                raise LedgerAnchorIntegrityError("Anchor journal genesis is invalid")
            return
        prior = previous.state
        if transition == "bootstrap" or prior.database_id != state.database_id:
            raise LedgerAnchorIntegrityError("Anchor journal transition scope is invalid")
        if transition == "checkpoint":
            valid = state == prior
        elif transition == "prepare":
            valid = (
                prior.committed is not None
                and prior.prepared is None
                and state.prepared is not None
                and state.committed == prior.committed
            )
        elif transition in {"finalize", "recover_finalize"}:
            valid = (
                prior.committed is not None
                and prior.prepared is not None
                and state.prepared is None
                and state.committed == prior.prepared
            )
        else:  # recover_rollback
            valid = (
                transition == "recover_rollback"
                and prior.committed is not None
                and prior.prepared is not None
                and state.prepared is None
                and state.committed == prior.committed
            )
        if not valid:
            raise LedgerAnchorIntegrityError("Anchor journal state transition is invalid")

    def _read_journal(self, descriptor: int, key: bytes) -> _JournalRead:
        try:
            size = os.fstat(descriptor).st_size
            if size > _MAX_JOURNAL_BYTES:
                raise LedgerAnchorIntegrityError("Anchor journal exceeds the byte limit")
        except LedgerAnchorError:
            raise
        except OSError as exc:
            raise LedgerAnchorIOError("Could not inspect the anchor journal") from exc

        raw_head = self._load_head_raw(required=False)
        head: _JournalHead | None = None
        if raw_head is not None:
            value = _parse_canonical(raw_head, limit=_MAX_VAULT_STATE)
            if value.get("contract") == "AnchorVaultHead.v2":
                head = _head_from_bytes(raw_head, key)
                # At most one bounded append may exist beyond the authenticated
                # head after a crash.  Permit that suffix for deterministic
                # recovery, but reject arbitrary oversized growth before scan.
                if size > _ACTIVE_JOURNAL_MAX_BYTES + _MAX_ENCODED_FRAME_BYTES:
                    raise LedgerAnchorIntegrityError(
                        "Anchor active generation exceeds its recovery bound"
                    )

        # A V2 vault head authenticates the already-sealed prefix. Hot paths
        # verify a bounded generation identity and stream only the suffix that
        # can exist after a journal fsync but before the vault write.
        frames: list[_JournalFrame] = []
        if head is None:
            frame_count = 0
            offset = 0
            previous_hmac = b"\0" * _MAC_BYTES
        else:
            identity_matches = (
                size >= head.active_first_frame_bytes
                and head.active_first_frame_bytes > 0
            )
            if identity_matches:
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    candidate_first = self._read_exact(
                        descriptor, head.active_first_frame_bytes
                    )
                except OSError as exc:
                    raise LedgerAnchorIOError(
                        "Could not inspect the anchor journal"
                    ) from exc
                identity_matches = hmac.compare_digest(
                    hashlib.sha256(candidate_first).hexdigest(),
                    head.active_first_frame_sha256,
                )
            if not identity_matches:
                adopted = self._adopt_successor(descriptor, key, raw_head, head)
                if adopted is None:
                    raise LedgerAnchorIntegrityError(
                        "Anchor journal was truncated, rolled back, or replaced"
                    )
                head = adopted
                size = os.fstat(descriptor).st_size
            if size < head.tail_offset or head.active_first_frame_bytes > size:
                raise LedgerAnchorIntegrityError("Anchor journal was truncated or rolled back")
            if not hmac.compare_digest(
                self._sha256_prefix(descriptor, head.tail_offset), head.active_sha256
            ):
                raise LedgerAnchorIntegrityError(
                    "Anchor journal transition or sealed prefix is invalid"
                )
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                first = self._read_exact(descriptor, head.active_first_frame_bytes)
            except OSError as exc:
                raise LedgerAnchorIOError("Could not inspect the anchor journal") from exc
            if not hmac.compare_digest(
                hashlib.sha256(first).hexdigest(), head.active_first_frame_sha256
            ):
                raise LedgerAnchorIntegrityError("Anchor journal generation identity is invalid")
            frames.append(
                _JournalFrame(
                    head.tail_sequence,
                    "checkpoint",
                    head.state,
                    head.tail_hmac,
                    head.tail_offset,
                )
            )
            frame_count = head.tail_sequence + 1
            offset = head.tail_offset
            previous_hmac = head.tail_hmac
        try:
            os.lseek(descriptor, offset, os.SEEK_SET)
        except OSError as exc:
            raise LedgerAnchorIOError("Could not inspect the anchor journal") from exc

        first_frame_end = 0
        while offset < size:
            if frame_count >= _MAX_JOURNAL_FRAMES:
                raise LedgerAnchorIntegrityError("Anchor journal exceeds the frame limit")
            start = offset
            header = self._read_exact(descriptor, _FRAME_HEADER.size)
            if len(header) < _FRAME_HEADER.size:
                return _JournalRead(tuple(frames), start, size)
            magic, payload_length = _FRAME_HEADER.unpack(header)
            if magic != _JOURNAL_MAGIC or payload_length == 0 or payload_length > _MAX_FRAME_PAYLOAD:
                raise LedgerAnchorIntegrityError("Anchor journal frame header is invalid")
            offset += _FRAME_HEADER.size
            body = self._read_exact(descriptor, payload_length + _MAC_BYTES)
            if len(body) < payload_length + _MAC_BYTES:
                return _JournalRead(tuple(frames), start, size)
            payload = body[:payload_length]
            frame_hmac = body[payload_length:]
            frame_end = offset + payload_length + _MAC_BYTES
            length_bytes = struct.pack(">I", payload_length)
            expected = hmac.new(
                key,
                _FRAME_DOMAIN + previous_hmac + length_bytes + payload,
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(expected, frame_hmac):
                raise LedgerAnchorIntegrityError("Anchor journal frame HMAC is invalid")
            value = _parse_canonical(payload, limit=_MAX_FRAME_PAYLOAD)
            contract = value.get("contract")
            expected_keys = (
                _FRAME_V2_KEYS if contract == "AnchorJournalCheckpoint.v2" else _FRAME_KEYS
            )
            if set(value) != expected_keys:
                raise LedgerAnchorIntegrityError("Anchor journal payload shape is invalid")
            frame_sequence = value.get("frame_sequence")
            transition = value.get("transition")
            if (
                contract not in {"AnchorJournalFrame.v1", "AnchorJournalCheckpoint.v2"}
                or type(frame_sequence) is not int
                or frame_sequence != frame_count
                or not isinstance(transition, str)
                or transition not in _TRANSITIONS
                or (contract == "AnchorJournalCheckpoint.v2") != (transition == "checkpoint")
            ):
                raise LedgerAnchorIntegrityError("Anchor journal payload fields are invalid")
            if contract == "AnchorJournalCheckpoint.v2":
                checkpoint = value.get("checkpoint")
                if not isinstance(checkpoint, dict) or set(checkpoint) != _CHECKPOINT_KEYS:
                    raise LedgerAnchorIntegrityError("Anchor journal checkpoint shape is invalid")
            state = _state_from_object(value.get("state"), key)
            self._validate_transition(frames[-1] if frames else None, transition, state)
            frames.append(_JournalFrame(frame_sequence, transition, state, frame_hmac, frame_end))
            if len(frames) > 2:
                del frames[0]
            frame_count += 1
            previous_hmac = frame_hmac
            offset = frame_end
            if first_frame_end == 0:
                first_frame_end = frame_end

        result = _JournalRead(tuple(frames), None, size)
        if head is None and raw_head is not None and frames:
            value = _parse_canonical(raw_head, limit=_MAX_VAULT_STATE)
            if value.get("contract") == "AnchorVaultState.v1":
                legacy_state = _state_from_bytes(raw_head, key)
                latest = frames[-1]
                if not self._same_state(latest.state, legacy_state):
                    raise LedgerAnchorIntegrityError("Anchor journal and vault state diverge")
                if first_frame_end <= 0:
                    raise LedgerAnchorIntegrityError("Anchor journal is empty")
                os.lseek(descriptor, 0, os.SEEK_SET)
                first = self._read_exact(descriptor, first_frame_end)
                upgraded = _JournalHead(
                    legacy_state,
                    0,
                    _ZERO_MAC,
                    _ZERO_MAC,
                    latest.frame_sequence,
                    latest.frame_hmac,
                    latest.end_offset,
                    latest.frame_sequence + 1,
                    self._sha256_prefix(descriptor, latest.end_offset),
                    first_frame_end,
                    hashlib.sha256(first).hexdigest(),
                )
                self._save_head(_head_bytes(upgraded, key))
        return result

    def _append_frame(
        self,
        descriptor: int,
        key: bytes,
        frames: tuple[_JournalFrame, ...],
        transition: str,
        state: _VaultState,
    ) -> _JournalFrame:
        if transition not in _TRANSITIONS:
            raise LedgerAnchorContractError("Anchor journal transition is invalid")
        self._validate_transition(frames[-1] if frames else None, transition, state)
        next_sequence = frames[-1].frame_sequence + 1 if frames else 0
        payload = _canonical(
            {
                "contract": "AnchorJournalFrame.v1",
                "frame_sequence": next_sequence,
                "state": state.as_object(),
                "transition": transition,
            }
        )
        if next_sequence >= _MAX_JOURNAL_FRAMES:
            raise LedgerAnchorIntegrityError("Anchor journal exceeds the frame limit")
        previous = frames[-1].frame_hmac if frames else b"\0" * _MAC_BYTES
        length_bytes = struct.pack(">I", len(payload))
        frame_hmac = hmac.new(
            key, _FRAME_DOMAIN + previous + length_bytes + payload, hashlib.sha256
        ).digest()
        frame = _FRAME_HEADER.pack(_JOURNAL_MAGIC, len(payload)) + payload + frame_hmac
        try:
            current_size = os.fstat(descriptor).st_size
        except OSError as exc:
            raise LedgerAnchorIOError("Could not inspect the anchor journal") from exc
        raw_head = self._load_head_raw(required=False)
        active_frame_count = 0
        if raw_head is not None:
            head_value = _parse_canonical(raw_head, limit=_MAX_VAULT_STATE)
            if head_value.get("contract") == "AnchorVaultHead.v2":
                active_frame_count = _head_from_bytes(raw_head, key).active_frame_count
            elif frames:
                # A legacy v1 head can only describe generation zero.
                active_frame_count = frames[-1].frame_sequence + 1
        if (
            active_frame_count + 1 > _ACTIVE_JOURNAL_MAX_FRAMES
            or current_size + len(frame) > _ACTIVE_JOURNAL_MAX_BYTES
        ):
            raise LedgerAnchorIntegrityError(
                "Anchor active generation exceeds its hard cap"
            )
        if current_size + len(frame) > _MAX_JOURNAL_BYTES:
            raise LedgerAnchorIntegrityError("Anchor journal exceeds the byte limit")
        self._fault("before_journal_append")
        try:
            os.lseek(descriptor, 0, os.SEEK_END)
            view = memoryview(frame)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise LedgerAnchorIOError("Anchor journal append made no progress")
                view = view[written:]
            os.fsync(descriptor)
        except LedgerAnchorError:
            raise
        except OSError as exc:
            raise LedgerAnchorIOError("Could not append the anchor journal") from exc
        self._fault("after_journal_fsync")
        return _JournalFrame(
            next_sequence,
            transition,
            state,
            frame_hmac,
            os.lseek(descriptor, 0, os.SEEK_END),
        )

    @staticmethod
    def _truncate(descriptor: int, offset: int) -> None:
        try:
            os.ftruncate(descriptor, offset)
            os.fsync(descriptor)
        except OSError as exc:
            raise LedgerAnchorIOError("Could not repair a trailing partial journal frame") from exc

    def _load_key(self, *, required: bool = True) -> bytes | None:
        try:
            key = self.__vault.read_key()
        except NativeVaultError as exc:
            raise LedgerAnchorVaultError("Anchor key vault is unavailable") from exc
        except Exception as exc:
            raise LedgerAnchorVaultError("Anchor key vault could not be read") from exc
        if key is None:
            if required:
                raise LedgerAnchorVaultError("Anchor key is missing")
            return None
        if not isinstance(key, bytes) or len(key) != _KEY_BYTES:
            raise LedgerAnchorVaultError("Anchor key has an invalid size")
        return key

    def _load_state(self, key: bytes, *, required: bool = True) -> _VaultState | None:
        raw = self._load_head_raw(required=required)
        if raw is None:
            return None
        value = _parse_canonical(raw, limit=_MAX_VAULT_STATE)
        if value.get("contract") == "AnchorVaultHead.v2":
            return _head_from_bytes(raw, key).state
        return _state_from_bytes(raw, key)

    def _load_head_raw(self, *, required: bool = True) -> bytes | None:
        try:
            raw = self.__vault.read_head()
        except NativeVaultError as exc:
            raise LedgerAnchorVaultError("Anchor head vault is unavailable") from exc
        except Exception as exc:
            raise LedgerAnchorVaultError("Anchor head vault could not be read") from exc
        if raw is None:
            if required:
                raise LedgerAnchorVaultError("Anchor head is missing")
            return None
        if not isinstance(raw, bytes):
            raise LedgerAnchorVaultError("Anchor head has an invalid representation")
        return raw

    def _save_key(self, key: bytes) -> None:
        if len(key) != _KEY_BYTES:
            raise LedgerAnchorContractError("Anchor key size is invalid")
        try:
            self.__vault.write_key(key)
            saved = self.__vault.read_key()
        except NativeVaultError as exc:
            raise LedgerAnchorVaultError("Anchor key vault write failed") from exc
        except Exception as exc:
            raise LedgerAnchorVaultError("Anchor key vault verification failed") from exc
        if not isinstance(saved, bytes) or not hmac.compare_digest(saved, key):
            raise LedgerAnchorVaultError("Anchor key vault verification failed")
        self._fault("after_key_saved")

    def _save_state(
        self,
        state: _VaultState,
        frame: _JournalFrame,
        descriptor: int,
        *,
        initial_first_frame_bytes: int | None = None,
        initial_first_frame_sha256: str | None = None,
    ) -> None:
        raw = self._load_head_raw(required=False)
        existing: _JournalHead | None = None
        if raw is not None:
            value = _parse_canonical(raw, limit=_MAX_VAULT_STATE)
            if value.get("contract") == "AnchorVaultHead.v2":
                key = self._load_key()
                existing = _head_from_bytes(raw, key)
        if existing is None:
            if (
                initial_first_frame_bytes is None
                or initial_first_frame_sha256 is None
            ):
                raise LedgerAnchorIntegrityError("Initial journal checkpoint is incomplete")
            generation = 0
            archive_sha256 = _ZERO_MAC
            archive_chain_sha256 = _ZERO_MAC
            active_frame_count = frame.frame_sequence + 1
            first_bytes = initial_first_frame_bytes
            first_sha256 = initial_first_frame_sha256
        else:
            generation = existing.generation
            archive_sha256 = existing.archive_sha256
            archive_chain_sha256 = existing.archive_chain_sha256
            active_frame_count = existing.active_frame_count + 1
            first_bytes = existing.active_first_frame_bytes
            first_sha256 = existing.active_first_frame_sha256
        key = self._load_key()
        head = _JournalHead(
            state,
            generation,
            archive_sha256,
            archive_chain_sha256,
            frame.frame_sequence,
            frame.frame_hmac,
            frame.end_offset,
            active_frame_count,
            self._sha256_prefix(descriptor, frame.end_offset),
            first_bytes,
            first_sha256,
        )
        self._save_head(_head_bytes(head, key))

    def _maybe_rotate(self, key: bytes, *, required_frames: int = 2) -> None:
        if type(required_frames) is not int or required_frames not in {1, 2}:
            raise LedgerAnchorContractError("Anchor rotation reservation is invalid")
        raw_head = self._load_head_raw()
        head = _head_from_bytes(raw_head, key)
        if (
            head.active_frame_count + required_frames <= _ACTIVE_JOURNAL_MAX_FRAMES
            and head.tail_offset + required_frames * _MAX_ENCODED_FRAME_BYTES
            <= _ACTIVE_JOURNAL_MAX_BYTES
        ):
            return
        descriptor = self._open_journal()
        temp_path = self._journal_path.with_name(
            f".{self._journal_path.name}.generation-{head.generation + 1}.tmp"
        )
        temp_descriptor: int | None = None
        try:
            active = self._read_active_bytes(descriptor)
            if len(active) != head.tail_offset or not hmac.compare_digest(
                hashlib.sha256(active).hexdigest(), head.active_sha256
            ):
                raise LedgerAnchorIntegrityError(
                    "Anchor journal changed before checkpoint rotation"
                )
            archive_sha256 = hashlib.sha256(active).hexdigest()
            archive_path = self._archive_path(head.generation, archive_sha256)
            try:
                archive_descriptor = os.open(
                    archive_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                    0o400,
                )
            except FileExistsError:
                if self._read_secure_bounded_file(
                    archive_path,
                    limit=_ACTIVE_JOURNAL_MAX_BYTES,
                    label="anchor archive collision",
                    immutable=True,
                ) != active:
                    raise LedgerAnchorIntegrityError("Anchor archive collision is invalid")
            else:
                try:
                    self._write_all(archive_descriptor, active)
                    os.fsync(archive_descriptor)
                finally:
                    os.close(archive_descriptor)
            self._fsync_parent()
            self._fault("after_archive_fsync")

            checkpoint_raw, checkpoint = self._checkpoint_bytes(
                key, head, raw_head, active
            )
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
            )
            try:
                temp_descriptor = os.open(temp_path, flags, 0o600)
            except FileExistsError:
                existing = self._read_secure_bounded_file(
                    temp_path,
                    limit=_MAX_ENCODED_FRAME_BYTES,
                    label="anchor checkpoint temporary file",
                )
                if existing != checkpoint_raw:
                    raise LedgerAnchorIntegrityError(
                        "Anchor checkpoint temporary-file collision is invalid"
                    )
            else:
                self._write_all(temp_descriptor, checkpoint_raw)
                os.fsync(temp_descriptor)
                os.close(temp_descriptor)
                temp_descriptor = None
            self._fault("after_checkpoint_temp_fsync")
            os.close(descriptor)
            descriptor = -1
            self._atomic_replace(temp_path, self._journal_path)
            self._fault("after_checkpoint_replace")

            chain = hashlib.sha256(
                _ARCHIVE_CHAIN_DOMAIN
                + bytes.fromhex(head.archive_chain_sha256)
                + struct.pack(">Q", head.generation)
                + bytes.fromhex(archive_sha256)
            ).hexdigest()
            successor = _JournalHead(
                head.state,
                head.generation + 1,
                archive_sha256,
                chain,
                checkpoint.frame_sequence,
                checkpoint.frame_hmac,
                checkpoint.end_offset,
                1,
                hashlib.sha256(checkpoint_raw).hexdigest(),
                len(checkpoint_raw),
                hashlib.sha256(checkpoint_raw).hexdigest(),
            )
            self._save_head(_head_bytes(successor, key))
        except LedgerAnchorError:
            raise
        except OSError as exc:
            raise LedgerAnchorIOError("Could not rotate the anchor journal") from exc
        finally:
            if temp_descriptor is not None:
                try:
                    os.close(temp_descriptor)
                except OSError:
                    pass
            if descriptor >= 0:
                os.close(descriptor)

    def _save_pending(self, pending: _BootstrapPending) -> None:
        self._save_head(_pending_bytes(pending))

    def _save_head(self, encoded: bytes) -> None:
        self._fault("before_vault_write")
        try:
            self.__vault.write_head(encoded)
            saved = self.__vault.read_head()
        except NativeVaultError as exc:
            raise LedgerAnchorVaultError("Anchor head vault write failed") from exc
        except Exception as exc:
            raise LedgerAnchorVaultError("Anchor head vault verification failed") from exc
        if not isinstance(saved, bytes) or not hmac.compare_digest(saved, encoded):
            raise LedgerAnchorVaultError("Anchor head vault verification failed")
        self._fault("after_vault_write")

    def _revoke_tickets(self) -> None:
        for ticket, issued in list(_ISSUED_PREPARED_TICKETS.items()):
            if hmac.compare_digest(issued[0], self._instance_token):
                _ISSUED_PREPARED_TICKETS.pop(ticket, None)

    @staticmethod
    def _status(state: _VaultState) -> AnchorStatus:
        record = state.prepared or state.committed
        if record is None:
            raise LedgerAnchorIntegrityError("Anchor state has no record")
        return AnchorStatus(
            state.database_id,
            record.sequence,
            record.ledger_root,
            record.schema_fingerprint,
            record.event_count,
            state.prepared is not None,
        )

    @staticmethod
    def _same_state(left: _VaultState, right: _VaultState) -> bool:
        return hmac.compare_digest(_state_bytes(left), _state_bytes(right))

    def _stable_locked(
        self, descriptor: int, key: bytes
    ) -> tuple[_VaultState, _JournalRead, LedgerSnapshot]:
        state = self._load_state(key)
        journal = self._read_journal(descriptor, key)
        if journal.partial_offset is not None:
            raise LedgerAnchorIntegrityError("Anchor journal has a trailing partial frame")
        if not journal.frames:
            raise LedgerAnchorIntegrityError("Anchor journal is empty")
        if not self._same_state(journal.frames[-1].state, state):
            raise LedgerAnchorIntegrityError("Anchor journal and vault state diverge")
        if state.committed is None or state.prepared is not None:
            raise LedgerAnchorConflict("Anchor has a prepared transition; recovery is required")
        snapshot = self._snapshot()
        if not _snapshot_matches(state.committed, snapshot):
            raise LedgerAnchorIntegrityError("Host database snapshot diverges from the anchor")
        return state, journal, snapshot

    def _bootstrap_opened(self, descriptor: int) -> AnchorStatus:
        snapshot = self._snapshot()
        key = self._load_key(required=False)
        raw_state = self._load_head_raw(required=False)
        if key is not None and raw_state is not None:
            raise LedgerAnchorConflict("Anchor is already bootstrapped")
        if key is not None or raw_state is not None or os.fstat(descriptor).st_size:
            raise LedgerAnchorIntegrityError(
                "Anchor bootstrap artifacts are incomplete or inconsistent"
            )
        pending = _BootstrapPending(snapshot, secrets.token_hex(16))
        # The durable pending descriptor is deliberately first. It binds
        # every later artifact to an exact snapshot and nonce.
        self._save_pending(pending)
        self._fault("after_bootstrap_pending")
        key = secrets.token_bytes(_KEY_BYTES)
        self._save_key(key)
        record = _record_for_snapshot(
            key,
            snapshot,
            sequence=0,
            previous_record_hmac=_ZERO_MAC,
            nonce=pending.nonce,
        )
        new_state = _VaultState(snapshot.database_id, record, None)
        appended = self._append_frame(descriptor, key, (), "bootstrap", new_state)
        os.lseek(descriptor, 0, os.SEEK_SET)
        first = self._read_exact(descriptor, appended.end_offset)
        self._save_state(
            new_state,
            appended,
            descriptor,
            initial_first_frame_bytes=appended.end_offset,
            initial_first_frame_sha256=hashlib.sha256(first).hexdigest(),
        )
        return self._status(new_state)

    @staticmethod
    def _close_bootstrap_descriptor(descriptor: int) -> None:
        try:
            os.close(descriptor)
        except OSError as exc:
            raise LedgerAnchorIOError("Could not close the anchor journal") from exc

    def bootstrap(self, owner: OwnerCapability) -> AnchorStatus:
        """Explicitly create the first key/head; never called by open_default."""
        self._assert_owner(owner)
        with self._locked():
            descriptor = self._open_journal(create=True)
            try:
                return self._bootstrap_opened(descriptor)
            finally:
                self._close_bootstrap_descriptor(descriptor)

    def _bootstrap_with_directory_capability(
        self,
        owner: OwnerCapability,
        directory_capability: _JournalDirectoryCapability,
        journal_opened: Callable[[tuple[int, ...]], None],
    ) -> AnchorStatus:
        """Bootstrap relative to a caller-pinned directory capability."""

        self._assert_owner(owner)
        with self._locked(directory_capability=directory_capability):
            descriptor = self._open_journal(
                create=True, directory_capability=directory_capability
            )
            try:
                journal_opened(directory_capability.descriptor_identity(descriptor))
                self._fault("after_capability_journal_open_before_pending")
                return self._bootstrap_opened(descriptor)
            finally:
                self._close_bootstrap_descriptor(descriptor)

    def _recover_bootstrap_pending(
        self, descriptor: int, pending: _BootstrapPending
    ) -> AnchorStatus:
        snapshot = self._snapshot()
        if snapshot != pending.snapshot:
            raise LedgerAnchorIntegrityError(
                "Bootstrap pending state does not match the host database"
            )
        key = self._load_key(required=False)
        try:
            size = os.fstat(descriptor).st_size
        except OSError as exc:
            raise LedgerAnchorIOError("Could not inspect the anchor journal") from exc
        if key is None:
            if size:
                raise LedgerAnchorIntegrityError(
                    "Bootstrap journal exists without its pending key"
                )
            key = secrets.token_bytes(_KEY_BYTES)
            self._save_key(key)

        record = _record_for_snapshot(
            key,
            pending.snapshot,
            sequence=0,
            previous_record_hmac=_ZERO_MAC,
            nonce=pending.nonce,
        )
        committed = _VaultState(pending.snapshot.database_id, record, None)
        journal = self._read_journal(descriptor, key)
        if journal.partial_offset is not None:
            if journal.frames:
                latest = journal.frames[-1]
                if (
                    latest.frame_sequence != 0
                    or latest.transition != "bootstrap"
                    or not self._same_state(latest.state, committed)
                ):
                    raise LedgerAnchorIntegrityError(
                        "Partial bootstrap journal does not match pending state"
                    )
                self._truncate(descriptor, latest.end_offset)
                journal = _JournalRead(journal.frames, None, latest.end_offset)
            else:
                self._truncate(descriptor, 0)
                journal = _JournalRead((), None, 0)
        if not journal.frames:
            appended = self._append_frame(
                descriptor, key, (), "bootstrap", committed
            )
            journal = _JournalRead((appended,), None, appended.end_offset)
        latest = journal.frames[-1]
        if (
            latest.frame_sequence != 0
            or latest.transition != "bootstrap"
            or not self._same_state(latest.state, committed)
        ):
            raise LedgerAnchorIntegrityError(
                "Bootstrap journal does not match pending state"
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        first = self._read_exact(descriptor, latest.end_offset)
        self._save_state(
            committed,
            latest,
            descriptor,
            initial_first_frame_bytes=latest.end_offset,
            initial_first_frame_sha256=hashlib.sha256(first).hexdigest(),
        )
        self._revoke_tickets()
        return self._status(committed)

    def _verify_locked_operation(self) -> AnchorStatus:
        descriptor = self._open_journal()
        try:
            key = self._load_key()
            state, _journal, _snapshot = self._stable_locked(descriptor, key)
            return self._status(state)
        finally:
            os.close(descriptor)

    def verify(self, owner: OwnerCapability) -> AnchorStatus:
        self._assert_owner(owner)
        with self._locked():
            return self._verify_locked_operation()

    def _verify_history_locked(self) -> AnchorStatus:
        key = self._load_key()
        raw_head = self._load_head_raw()
        value = _parse_canonical(raw_head, limit=_MAX_VAULT_STATE)
        if value.get("contract") != "AnchorVaultHead.v2":
            descriptor = self._open_journal()
            try:
                self._read_journal(descriptor, key)
            finally:
                os.close(descriptor)
            raw_head = self._load_head_raw()
        head = _head_from_bytes(raw_head, key)

        active = self._read_secure_bounded_file(
            self._journal_path,
            limit=_ACTIVE_JOURNAL_MAX_BYTES,
            label="anchor active generation",
        )
        selected: dict[int, tuple[Path, bytes]] = {}
        successor = active
        for generation in reversed(range(head.generation)):
            if len(successor) < _FRAME_HEADER.size + _MAC_BYTES:
                raise LedgerAnchorIntegrityError(
                    "Anchor history checkpoint generation is incomplete"
                )
            magic, payload_length = _FRAME_HEADER.unpack(
                successor[: _FRAME_HEADER.size]
            )
            end = _FRAME_HEADER.size + payload_length
            if (
                magic != _JOURNAL_MAGIC
                or payload_length <= 0
                or payload_length > _MAX_FRAME_PAYLOAD
                or end + _MAC_BYTES > len(successor)
            ):
                raise LedgerAnchorIntegrityError(
                    "Anchor history checkpoint generation is invalid"
                )
            checkpoint_frame = _parse_canonical(
                successor[_FRAME_HEADER.size : end], limit=_MAX_FRAME_PAYLOAD
            )
            checkpoint = checkpoint_frame.get("checkpoint")
            digest = (
                checkpoint.get("archive_sha256")
                if isinstance(checkpoint, dict)
                else None
            )
            if (
                checkpoint_frame.get("contract") != "AnchorJournalCheckpoint.v2"
                or checkpoint_frame.get("transition") != "checkpoint"
                or not isinstance(checkpoint, dict)
                or set(checkpoint) != _CHECKPOINT_KEYS
                or checkpoint.get("generation") != generation + 1
                or not isinstance(digest, str)
                or not _DIGEST.fullmatch(digest)
            ):
                raise LedgerAnchorIntegrityError(
                    "Anchor history checkpoint archive link is invalid"
                )
            path = self._archive_path(generation, digest)
            try:
                raw = self._read_secure_bounded_file(
                    path,
                    limit=_ACTIVE_JOURNAL_MAX_BYTES,
                    label="anchor archive generation",
                    immutable=True,
                )
            except OSError as exc:
                raise LedgerAnchorIntegrityError(
                    "Anchor archive generation is missing"
                ) from exc
            if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), digest):
                raise LedgerAnchorIntegrityError(
                    "Anchor archive content address is invalid"
                )
            selected[generation] = (path, raw)
            successor = raw
        files: list[tuple[int, Path, bytes]] = [
            (generation, *selected[generation])
            for generation in range(head.generation)
        ]
        files.append((head.generation, self._journal_path, active))

        previous: _JournalFrame | None = None
        previous_file: bytes | None = None
        previous_file_digest = _ZERO_MAC
        expected_sequence = 0
        archive_chain = _ZERO_MAC
        last_archive_digest = _ZERO_MAC
        active_frame_count = 0
        for generation, path, raw in files:
            if not raw:
                raise LedgerAnchorIntegrityError("Anchor history generation is empty")
            offset = 0
            file_frame_count = 0
            prior_tail = previous
            while offset < len(raw):
                start = offset
                if len(raw) - offset < _FRAME_HEADER.size:
                    raise LedgerAnchorIntegrityError(
                        "Anchor history has a partial frame"
                    )
                magic, payload_length = _FRAME_HEADER.unpack(
                    raw[offset : offset + _FRAME_HEADER.size]
                )
                offset += _FRAME_HEADER.size
                end = offset + payload_length + _MAC_BYTES
                if (
                    magic != _JOURNAL_MAGIC
                    or payload_length <= 0
                    or payload_length > _MAX_FRAME_PAYLOAD
                    or end > len(raw)
                ):
                    raise LedgerAnchorIntegrityError(
                        "Anchor history frame header is invalid"
                    )
                payload = raw[offset : offset + payload_length]
                frame_hmac = raw[offset + payload_length : end]
                prior_hmac = previous.frame_hmac if previous else b"\0" * _MAC_BYTES
                expected_hmac = hmac.new(
                    key,
                    _FRAME_DOMAIN
                    + prior_hmac
                    + struct.pack(">I", payload_length)
                    + payload,
                    hashlib.sha256,
                ).digest()
                if not hmac.compare_digest(expected_hmac, frame_hmac):
                    raise LedgerAnchorIntegrityError(
                        "Anchor history frame HMAC is invalid"
                    )
                frame_value = _parse_canonical(payload, limit=_MAX_FRAME_PAYLOAD)
                contract = frame_value.get("contract")
                keys = (
                    _FRAME_V2_KEYS
                    if contract == "AnchorJournalCheckpoint.v2"
                    else _FRAME_KEYS
                )
                transition = frame_value.get("transition")
                if (
                    set(frame_value) != keys
                    or contract
                    not in {"AnchorJournalFrame.v1", "AnchorJournalCheckpoint.v2"}
                    or frame_value.get("frame_sequence") != expected_sequence
                    or not isinstance(transition, str)
                    or transition not in _TRANSITIONS
                ):
                    raise LedgerAnchorIntegrityError(
                        "Anchor history frame fields are invalid"
                    )
                state = _state_from_object(frame_value.get("state"), key)
                self._validate_transition(previous, transition, state)
                frame = _JournalFrame(
                    expected_sequence, transition, state, frame_hmac, end
                )
                if file_frame_count == 0 and generation > 0:
                    checkpoint = frame_value.get("checkpoint")
                    if (
                        contract != "AnchorJournalCheckpoint.v2"
                        or transition != "checkpoint"
                        or not isinstance(checkpoint, dict)
                        or set(checkpoint) != _CHECKPOINT_KEYS
                        or checkpoint.get("generation") != generation
                        or checkpoint.get("archive_bytes") != len(previous_file or b"")
                        or checkpoint.get("archive_sha256")
                        != previous_file_digest
                        or prior_tail is None
                        or checkpoint.get("previous_tail_sequence")
                        != prior_tail.frame_sequence
                        or checkpoint.get("previous_tail_hmac")
                        != prior_tail.frame_hmac.hex()
                    ):
                        raise LedgerAnchorIntegrityError(
                            "Anchor history checkpoint link is invalid"
                        )
                elif file_frame_count == 0 and generation == 0:
                    if transition != "bootstrap":
                        raise LedgerAnchorIntegrityError(
                            "Anchor history genesis is invalid"
                        )
                previous = frame
                expected_sequence += 1
                file_frame_count += 1
                offset = end
                if offset <= start:
                    raise LedgerAnchorIntegrityError(
                        "Anchor history frame made no progress"
                    )
            digest = hashlib.sha256(raw).hexdigest()
            if generation < head.generation:
                if not path.name.endswith(digest):
                    raise LedgerAnchorIntegrityError(
                        "Anchor archive filename is not content-addressed"
                    )
                archive_chain = hashlib.sha256(
                    _ARCHIVE_CHAIN_DOMAIN
                    + bytes.fromhex(archive_chain)
                    + struct.pack(">Q", generation)
                    + bytes.fromhex(digest)
                ).hexdigest()
                last_archive_digest = digest
            else:
                active_frame_count = file_frame_count
            previous_file = raw
            previous_file_digest = digest

        if previous is None or not self._same_state(previous.state, head.state):
            raise LedgerAnchorIntegrityError("Anchor history and vault state diverge")
        if (
            previous.frame_sequence != head.tail_sequence
            or not hmac.compare_digest(previous.frame_hmac, head.tail_hmac)
            or len(active) != head.tail_offset
            or hashlib.sha256(active).hexdigest() != head.active_sha256
            or active_frame_count != head.active_frame_count
            or archive_chain != head.archive_chain_sha256
            or last_archive_digest != head.archive_sha256
        ):
            raise LedgerAnchorIntegrityError("Anchor history tail is invalid")
        return self._status(head.state)

    def verify_history(self, owner: OwnerCapability) -> AnchorStatus:
        """Cold O(N) audit of every immutable archive and the active generation."""

        self._assert_owner(owner)
        with self._locked():
            return self._verify_history_locked()

    def _prepare_locked_operation(self) -> PreparedTicket:
        key = self._load_key()
        self._maybe_rotate(key, required_frames=2)
        descriptor = self._open_journal()
        try:
            state = self._load_state(key)
            journal = self._read_journal(descriptor, key)
            if journal.partial_offset is not None or not journal.frames:
                raise LedgerAnchorIntegrityError("Anchor journal is incomplete")
            if not self._same_state(journal.frames[-1].state, state):
                raise LedgerAnchorIntegrityError("Anchor journal and vault state diverge")
            if state.committed is None or state.prepared is not None:
                raise LedgerAnchorConflict(
                    "Anchor has a prepared transition; recovery is required"
                )
            candidate = self._snapshot()
            if _snapshot_matches(state.committed, candidate):
                raise LedgerAnchorConflict("Candidate snapshot does not change the ledger")
            committed = state.committed
            if committed is None or candidate.database_id != committed.database_id:
                raise LedgerAnchorConflict("Candidate snapshot changes database identity")
            prepared = _record_for_snapshot(
                key,
                candidate,
                sequence=committed.sequence + 1,
                previous_record_hmac=committed.record_hmac,
                nonce=secrets.token_hex(16),
            )
            new_state = _VaultState(state.database_id, committed, prepared)
            appended = self._append_frame(
                descriptor, key, journal.frames, "prepare", new_state
            )
            self._save_state(new_state, appended, descriptor)
            ticket = PreparedTicket(
                self._instance_token,
                prepared.sequence,
                prepared.record_hmac,
                _TICKET_SEAL,
            )
            _ISSUED_PREPARED_TICKETS[ticket] = (
                self._instance_token,
                prepared.sequence,
                prepared.record_hmac,
            )
            return ticket
        finally:
            os.close(descriptor)

    def prepare(self, owner: OwnerCapability) -> PreparedTicket:
        """Seal the port's candidate snapshot before the trusted host commits it."""
        self._assert_owner(owner)
        with self._locked():
            return self._prepare_locked_operation()

    def _finalize_locked_operation(self, ticket: PreparedTicket) -> AnchorStatus:
        self._assert_ticket(ticket)
        key = self._load_key()
        self._maybe_rotate(key, required_frames=1)
        descriptor = self._open_journal()
        status: AnchorStatus | None = None
        try:
            state = self._load_state(key)
            journal = self._read_journal(descriptor, key)
            if journal.partial_offset is not None or not journal.frames:
                raise LedgerAnchorIntegrityError("Anchor journal is incomplete")
            if not self._same_state(journal.frames[-1].state, state):
                raise LedgerAnchorIntegrityError("Anchor journal and vault state diverge")
            prepared = state.prepared
            if state.committed is None or prepared is None:
                raise LedgerAnchorConflict("No prepared anchor is available")
            if (
                ticket._sequence != prepared.sequence
                or not hmac.compare_digest(ticket._record_hmac, prepared.record_hmac)
            ):
                raise LedgerAnchorConflict("Prepared ticket is stale")
            snapshot = self._snapshot()
            if not _snapshot_matches(prepared, snapshot):
                raise LedgerAnchorConflict(
                    "Host database did not commit the prepared snapshot"
                )
            final_state = _VaultState(state.database_id, prepared, None)
            appended = self._append_frame(
                descriptor, key, journal.frames, "finalize", final_state
            )
            self._fault("before_finalize_vault")
            self._save_state(final_state, appended, descriptor)
            self._used_tickets.append((ticket._sequence, ticket._record_hmac))
            _ISSUED_PREPARED_TICKETS.pop(ticket, None)
            status = self._status(final_state)
        finally:
            os.close(descriptor)
        if status is None:
            raise LedgerAnchorIntegrityError("Anchor finalize did not produce a status")
        self._maybe_rotate(key, required_frames=2)
        return status

    def finalize(
        self, owner: OwnerCapability, ticket: PreparedTicket
    ) -> AnchorStatus:
        """Promote an exact prepared snapshot after the trusted host commits it."""
        self._assert_owner(owner)
        self._assert_ticket(ticket)
        with self._locked():
            return self._finalize_locked_operation(ticket)

    def _recover_locked_operation(self) -> AnchorStatus:
        raw_head = self._load_head_raw()
        value = _parse_canonical(raw_head, limit=_MAX_VAULT_STATE)
        pending = (
            _pending_from_bytes(raw_head)
            if value.get("contract") == "AnchorBootstrapPending.v1"
            else None
        )
        key: bytes | None = None
        if pending is None:
            key = self._load_key()
        descriptor = self._open_journal(create=pending is not None)
        try:
            if pending is not None:
                return self._recover_bootstrap_pending(descriptor, pending)
            if key is None:  # pragma: no cover - pending branch returns above
                raise LedgerAnchorIntegrityError("Anchor recovery key is unavailable")
            state = self._load_state(key)
            journal = self._read_journal(descriptor, key)
            if not journal.frames:
                raise LedgerAnchorIntegrityError("Anchor journal is empty")
            snapshot = self._snapshot()
            if journal.partial_offset is not None:
                if not self._same_state(journal.frames[-1].state, state):
                    raise LedgerAnchorIntegrityError(
                        "Partial journal cannot be reconciled with the vault"
                    )
                comparable = state.prepared or state.committed
                if comparable is None or not (
                    _snapshot_matches(comparable, snapshot)
                    or (
                        state.committed is not None
                        and _snapshot_matches(state.committed, snapshot)
                    )
                ):
                    raise LedgerAnchorIntegrityError(
                        "Partial journal cannot be reconciled with the host database"
                    )
                self._truncate(descriptor, journal.partial_offset)
                journal = _JournalRead(journal.frames, None, journal.partial_offset)

            latest = journal.frames[-1].state
            if not self._same_state(latest, state):
                previous_matches = len(journal.frames) > 1 and self._same_state(
                    journal.frames[-2].state, state
                )
                if not previous_matches:
                    raise LedgerAnchorIntegrityError(
                        "Anchor journal is more than one transition from the vault"
                    )
                state = latest
                # Seal the single authenticated journal-ahead transition before
                # any capacity rotation.  Otherwise a later save could skip a
                # frame in active_frame_count, and rotation would inspect an
                # unsealed suffix rather than the authenticated head.
                self._save_state(state, journal.frames[-1], descriptor)

            committed, prepared = state.committed, state.prepared
            if committed is None:
                raise LedgerAnchorIntegrityError(
                    "Incomplete bootstrap requires explicit bootstrap"
                )
            if prepared is None:
                if not _snapshot_matches(committed, snapshot):
                    raise LedgerAnchorIntegrityError(
                        "Host database snapshot diverges from committed anchor"
                    )
                if not self._same_state(latest, self._load_state(key)):
                    self._save_state(latest, journal.frames[-1], descriptor)
                self._revoke_tickets()
                return self._status(latest)

            # A prepared state needs one resolution frame.  Reconcile/truncate
            # first, then rotate the exact sealed generation if the reservation
            # does not fit.  This ordering permits recovery of a partial suffix
            # at the hard boundary without ever archiving unauthenticated bytes.
            os.close(descriptor)
            descriptor = -1
            self._maybe_rotate(key, required_frames=1)
            descriptor = self._open_journal()
            state = self._load_state(key)
            journal = self._read_journal(descriptor, key)
            if journal.partial_offset is not None or not journal.frames:
                raise LedgerAnchorIntegrityError(
                    "Anchor journal is incomplete after recovery rotation"
                )
            if not self._same_state(journal.frames[-1].state, state):
                raise LedgerAnchorIntegrityError(
                    "Anchor journal and vault diverged during recovery rotation"
                )
            committed, prepared = state.committed, state.prepared
            snapshot = self._snapshot()
            if committed is None or prepared is None:
                raise LedgerAnchorIntegrityError(
                    "Prepared anchor disappeared during recovery rotation"
                )

            if _snapshot_matches(committed, snapshot):
                resolved = _VaultState(state.database_id, committed, None)
                transition = "recover_rollback"
            elif _snapshot_matches(prepared, snapshot):
                resolved = _VaultState(state.database_id, prepared, None)
                transition = "recover_finalize"
            else:
                raise LedgerAnchorIntegrityError(
                    "Prepared anchor matches neither durable database state"
                )
            appended = self._append_frame(
                descriptor, key, journal.frames, transition, resolved
            )
            journal = _JournalRead(
                (*journal.frames, appended), None, appended.end_offset
            )
            del journal
            self._save_state(resolved, appended, descriptor)
            self._revoke_tickets()
            return self._status(resolved)
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def recover(self, owner: OwnerCapability) -> AnchorStatus:
        """Resolve only deterministic one-transition crash states, otherwise fail."""
        self._assert_owner(owner)
        with self._locked():
            status = self._recover_locked_operation()
            self._maybe_rotate(self._load_key(), required_frames=2)
            return status


class _LedgerAnchorWriterSession:
    """Single-use transition surface while one anchor lock is held."""

    __slots__ = (
        "_anchor",
        "_owner",
        "_timeout",
        "_lock_context",
        "_thread_id",
        "_state",
        "_ticket",
        "_entered",
        "_closed",
    )

    def __init__(
        self,
        anchor: LedgerAnchor,
        owner: OwnerCapability,
        timeout: float,
        *,
        _seal: object,
    ):
        if _seal is not _WRITER_SESSION_SEAL:
            raise TypeError("Anchor writer session cannot be constructed directly")
        self._anchor = anchor
        self._owner = owner
        self._timeout = timeout
        self._lock_context = None
        self._thread_id: int | None = None
        self._state = "new"
        self._ticket: PreparedTicket | None = None
        self._entered = False
        self._closed = False

    def __copy__(self):
        raise TypeError("Anchor writer session cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("Anchor writer session cannot be copied")

    def __reduce__(self):
        raise TypeError("Anchor writer session cannot be serialized")

    def __repr__(self) -> str:
        state = "closed" if self._closed else self._state
        return f"<LedgerAnchorWriterSession {state}>"

    def __enter__(self) -> _LedgerAnchorWriterSession:
        if self._entered or self._closed:
            raise LedgerAnchorConflict("Anchor writer session is single-use")
        if getattr(_SESSION_LOCAL, "active", None) is not None:
            raise LedgerAnchorConflict("Nested anchor writer sessions are forbidden")
        self._anchor._assert_owner(self._owner)
        self._entered = True
        self._thread_id = threading.get_ident()
        lock_context = self._anchor._locked(timeout=self._timeout)
        self._lock_context = lock_context
        try:
            lock_context.__enter__()
            _SESSION_LOCAL.active = self
            self._state = "entered"
            return self
        except BaseException:
            self._closed = True
            self._state = "closed"
            self._lock_context = None
            self._thread_id = None
            raise

    def _assert_active(self) -> None:
        if (
            not self._entered
            or self._closed
            or self._state in {"new", "closed"}
        ):
            raise LedgerAnchorConflict("Anchor writer session is not active")
        if self._thread_id != threading.get_ident():
            raise LedgerAnchorContractError(
                "Anchor writer session cannot cross thread boundaries"
            )
        if getattr(_SESSION_LOCAL, "active", None) is not self:
            raise LedgerAnchorConflict("Anchor writer session ownership is invalid")
        self._anchor._assert_owner(self._owner)

    def verify_baseline(self) -> AnchorStatus:
        self._assert_active()
        if self._state not in {"entered", "verified"}:
            raise LedgerAnchorConflict("Anchor baseline verification is out of order")
        status = self._anchor._verify_locked_operation()
        self._state = "verified"
        return status

    def verify_committed(self) -> AnchorStatus:
        """Verify the post-transition committed snapshot under the held lock."""

        self._assert_active()
        if self._state not in {"finalized", "recovered"}:
            raise LedgerAnchorConflict("Committed anchor verification is out of order")
        return self._anchor._verify_locked_operation()

    def prepare_candidate(self) -> PreparedTicket:
        self._assert_active()
        if self._state != "verified" or self._ticket is not None:
            raise LedgerAnchorConflict("Anchor candidate preparation is out of order")
        ticket = self._anchor._prepare_locked_operation()
        self._ticket = ticket
        self._state = "prepared"
        return ticket

    def finalize_prepared(self, ticket: PreparedTicket) -> AnchorStatus:
        self._assert_active()
        if self._state != "prepared" or self._ticket is not ticket:
            raise LedgerAnchorConflict("Prepared anchor ticket is not session-owned")
        status = self._anchor._finalize_locked_operation(ticket)
        self._ticket = None
        self._state = "finalized"
        return status

    def recover(self) -> AnchorStatus:
        self._assert_active()
        if self._state not in {"entered", "verified", "prepared"}:
            raise LedgerAnchorConflict("Anchor recovery is out of order")
        status = self._anchor._recover_locked_operation()
        self._anchor._maybe_rotate(
            self._anchor._load_key(), required_frames=2
        )
        self._ticket = None
        self._state = "recovered"
        return status

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self._closed:
            raise LedgerAnchorConflict("Anchor writer session is already closed")
        if self._thread_id != threading.get_ident():
            raise LedgerAnchorContractError(
                "Anchor writer session cannot be closed from another thread"
            )
        primary = exc
        recovery_error: BaseException | None = None
        release_error: BaseException | None = None
        try:
            if self._state == "prepared":
                try:
                    self._anchor._recover_locked_operation()
                    self._anchor._maybe_rotate(
                        self._anchor._load_key(), required_frames=2
                    )
                    self._ticket = None
                    self._state = "recovered"
                except BaseException as error:
                    recovery_error = error
        finally:
            if getattr(_SESSION_LOCAL, "active", None) is self:
                _SESSION_LOCAL.active = None
            lock_context, self._lock_context = self._lock_context, None
            if lock_context is not None:
                try:
                    lock_context.__exit__(exc_type, exc, traceback)
                except BaseException as error:
                    release_error = error
            self._closed = True
            self._state = "closed"
            self._thread_id = None
        if primary is not None:
            return False
        if recovery_error is not None:
            raise recovery_error
        if release_error is not None:
            raise release_error
        return False


def _canonical_port() -> LedgerAnchorPort:
    raise LedgerAnchorUnavailable(
        "The canonical M2b-b database anchor port is not implemented"
    )


def _make_production_opener(port_factory, vault_factory, path_resolver):
    """Freeze reviewed dependencies in a closure, outside mutable object slots."""

    def open_anchor() -> LedgerAnchor:
        return LedgerAnchor(
            port_factory(),
            path_resolver(),
            vault_factory(),
            _seal=_ANCHOR_CONSTRUCTOR_SEAL,
        )

    return open_anchor


_PRODUCTION_OPEN = _make_production_opener(
    _canonical_port, _NativeAnchorVaultFacade, _ledger_anchor_journal_path
)


def open_default() -> LedgerAnchor:
    """Open only the future canonical production port; no injection is accepted."""
    if not ledger_anchor_enabled():
        raise LedgerAnchorDisabled(
            f"{LEDGER_ANCHOR_FLAG} is disabled; M2b-a is not part of runtime"
        )
    return _PRODUCTION_OPEN()


def _open_for_testing(
    port: LedgerAnchorPort,
    *,
    journal_path: Path,
    key_vault: SecretVaultPort,
    state_vault: SecretVaultPort,
) -> tuple[LedgerAnchor, OwnerCapability]:
    """Test-only host factory; production callers must use open_default."""
    anchor = LedgerAnchor(
        port,
        journal_path,
        _TestingAnchorVaultFacade(key_vault, state_vault),
        _seal=_ANCHOR_CONSTRUCTOR_SEAL,
    )
    owner = OwnerCapability(anchor._instance_token, _CAPABILITY_SEAL)
    _ISSUED_OWNER_CAPABILITIES[owner] = anchor._instance_token
    return anchor, owner


__all__ = [
    "LEDGER_ANCHOR_FLAG",
    "LedgerAnchorConflict",
    "LedgerAnchorContractError",
    "LedgerAnchorDisabled",
    "LedgerAnchorError",
    "LedgerAnchorIOError",
    "LedgerAnchorIntegrityError",
    "LedgerAnchorUnavailable",
    "LedgerAnchorVaultError",
    "ledger_anchor_enabled",
    "open_default",
]
