"""Owner Profile V6: rollback-resistant owner identity authority.

V6 is an isolated, default-off candidate.  It adds a required monotonic
``ChainHeadStore`` to the authenticated file journal.  The chain head is
separate from the journal, configuration, and semantic memory.  No file-only
fallback exists for live authority.

The production Windows adapter stores the head in the current user's Windows
Credential Manager (whose credential blob protection is provided by Windows)
and serializes cooperating writers with a named kernel mutex.  Keychain and
Secret Service implementations can satisfy the same explicit CAS protocol in
later platform-specific work; they are not emulated here.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import stat
import tempfile
import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import core.owner_profile_v1 as v1
import core.owner_profile_v2 as v2
from core import native_vault


PROFILE_SCHEMA_VERSION = 6
JOURNAL_SCHEMA = "onyx.owner-profile-journal.v6"
CHAIN_HEAD_VERSION = 1
JOURNAL_FILENAME = "owner-profile-v6.journal.json"
MAX_JOURNAL_BYTES = 2_500_000
MAX_JOURNAL_RECORDS = 4096
GENESIS_MAC = "0" * 64
WINDOWS_HEAD_SERVICE = "Onyx.OwnerProfileChainHead.v1"
RESERVED_MEMORY_JOURNAL_KEYS = frozenset(
    {
        "owner_profile_v3_recovery",
        "owner_profile_v4_journal",
        "owner_profile_v5_journal",
        "owner_profile_v6_journal",
    }
)

FALLBACK_ADDRESS = v1.FALLBACK_ADDRESS
FALLBACK_LANGUAGE = v1.FALLBACK_LANGUAGE
FALLBACK_TRANSLATION_POLICY = v1.FALLBACK_TRANSLATION_POLICY
FIRST_CONTACT_QUESTION = v1.FIRST_CONTACT_QUESTION
InvalidDisplayName = v1.InvalidDisplayName
OwnerProfileError = v1.OwnerProfileError
OwnerProfileSnapshot = v1.OwnerProfileSnapshot
OwnerProfileState = v1.OwnerProfileState
normalize_display_name = v1.normalize_display_name

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_LOWER_HEX_64 = re.compile(r"[0-9a-f]{64}")
_ENVELOPE_FIELDS = frozenset({"schema", "records"})
_RECORD_FIELDS = frozenset(
    {
        "version",
        "owner_profile_id",
        "runtime_instance",
        "sequence",
        "operation",
        "prior_name",
        "target_name",
        "decision_state",
        "nonce",
        "previous_mac",
        "mac",
    }
)
_MAC_FIELDS = tuple(sorted(_RECORD_FIELDS - {"mac"}))
_HEAD_FIELDS = frozenset({"version", "owner_profile_id", "sequence", "head_mac"})


class JournalState(str, Enum):
    PREPARED = "PREPARED"
    COMMITTED = "COMMITTED"
    COMPENSATED = "COMPENSATED"


@dataclass(frozen=True, slots=True)
class JournalEntry:
    sequence: int
    state: JournalState
    operation: str
    prior_name: str | None
    target_name: str | None
    nonce: str
    mac: str = ""


@dataclass(frozen=True, slots=True)
class ChainHead:
    version: int
    owner_profile_id: str
    sequence: int
    head_mac: str


@dataclass(frozen=True, slots=True)
class StageDiagnostic:
    stage: str
    error_type: str


@dataclass(frozen=True, slots=True)
class OwnerProfileFailure:
    operation: str
    stage: str
    original_error_type: str
    recovery: tuple[StageDiagnostic, ...] = ()
    journal_state: str | None = None
    decision: str | None = None
    divergence_possible: bool = True


class OwnerProfileTransactionError(OwnerProfileError):
    def __init__(
        self,
        operation: str,
        operation_error: Exception,
        root_error: Exception,
        recovery_errors: tuple[tuple[str, Exception], ...],
        decision: JournalState | None,
    ) -> None:
        self.operation = operation
        self.operation_error = operation_error
        self.original_error = root_error
        self.recovery_errors = recovery_errors
        self.decision = decision
        suffix = (
            f"; decision={decision.value}"
            if decision is not None
            else "; decision pending"
        )
        super().__init__(f"Owner profile {operation} failed{suffix}")


class JournalIntegrityError(OwnerProfileError):
    """The journal is malformed, unauthenticated, stale, or divergent."""


class ChainHeadError(OwnerProfileError):
    """Base class for safe monotonic-chain-head failures."""


class ChainHeadUnavailable(ChainHeadError):
    """The required host chain-head store is missing or unavailable."""


class ChainHeadConflict(ChainHeadError):
    """A compare-and-set lost to another writer or observed divergence."""


@runtime_checkable
class ChainHeadStore(Protocol):
    """Required host transaction port; implementations must provide real CAS."""

    def load(self, owner_profile_id: str) -> ChainHead | None: ...

    def compare_and_set(
        self,
        owner_profile_id: str,
        expected: ChainHead | None,
        desired: ChainHead,
    ) -> bool: ...


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise TypeError(f"{label} must be a bounded host identifier")
    return value


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", errors="strict")


def _name(value: object, *, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str:
        raise JournalIntegrityError("Owner journal contains an invalid display name")
    try:
        normalized = normalize_display_name(value)
    except InvalidDisplayName as exc:
        raise JournalIntegrityError(
            "Owner journal contains an invalid display name"
        ) from exc
    if normalized is None or normalized != value:
        raise JournalIntegrityError(
            "Owner journal contains a non-canonical display name"
        )
    return normalized


def _validate_head(value: object, owner_profile_id: str) -> ChainHead:
    if type(value) is not ChainHead:
        raise ChainHeadUnavailable("Owner chain head has an invalid representation")
    if type(value.version) is not int or value.version != CHAIN_HEAD_VERSION:
        raise ChainHeadUnavailable("Owner chain head version is invalid")
    if value.owner_profile_id != owner_profile_id:
        raise ChainHeadUnavailable("Owner chain head profile binding is invalid")
    if (
        type(value.sequence) is not int
        or value.sequence < 0
        or value.sequence > MAX_JOURNAL_RECORDS
    ):
        raise ChainHeadUnavailable("Owner chain head sequence is invalid")
    if type(value.head_mac) is not str or not _LOWER_HEX_64.fullmatch(value.head_mac):
        raise ChainHeadUnavailable("Owner chain head authenticator is invalid")
    if value.sequence == 0 and value.head_mac != GENESIS_MAC:
        raise ChainHeadUnavailable("Owner chain head genesis is invalid")
    if value.sequence > 0 and value.head_mac == GENESIS_MAC:
        raise ChainHeadUnavailable("Owner chain head authenticator is invalid")
    return value


def genesis_head(owner_profile_id: str) -> ChainHead:
    return ChainHead(
        CHAIN_HEAD_VERSION,
        _identifier(owner_profile_id, "owner_profile_id"),
        0,
        GENESIS_MAC,
    )


def _head_for(owner_profile_id: str, entry: JournalEntry) -> ChainHead:
    if entry.state not in {JournalState.COMMITTED, JournalState.COMPENSATED}:
        raise ChainHeadError(
            "Only a terminal journal record can advance the chain head"
        )
    return ChainHead(CHAIN_HEAD_VERSION, owner_profile_id, entry.sequence, entry.mac)


def _same_head(left: ChainHead | None, right: ChainHead | None) -> bool:
    if left is None or right is None:
        return left is right
    try:
        left_bytes = _canonical(
            {
                "version": left.version,
                "owner_profile_id": left.owner_profile_id,
                "sequence": left.sequence,
                "head_mac": left.head_mac,
            }
        )
        right_bytes = _canonical(
            {
                "version": right.version,
                "owner_profile_id": right.owner_profile_id,
                "sequence": right.sequence,
                "head_mac": right.head_mac,
            }
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return hmac.compare_digest(left_bytes, right_bytes)


def _validate_head_transition(
    expected: ChainHead | None, desired: ChainHead, owner_profile_id: str
) -> None:
    if expected is None:
        if not _same_head(desired, genesis_head(owner_profile_id)):
            raise ChainHeadConflict("Owner chain-head initialization must be genesis")
        return
    if desired.sequence != expected.sequence + 2:
        raise ChainHeadConflict("Owner chain-head transition is not monotonic")
    if hmac.compare_digest(desired.head_mac, expected.head_mac):
        raise ChainHeadConflict(
            "Owner chain-head transition did not change its authenticator"
        )


class _WindowsNamedMutex(AbstractContextManager["_WindowsNamedMutex"]):
    def __init__(self, owner_profile_id: str, *, timeout_seconds: float = 5.0) -> None:
        digest = hashlib.sha256(owner_profile_id.encode("ascii")).hexdigest()
        self.name = f"Local\\CyryxLabs.Onyx.OwnerProfileChainHead.{digest}"
        self.timeout_seconds = timeout_seconds
        self._handle: int | None = None

    @staticmethod
    def _kernel32():
        try:
            return ctypes.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError) as exc:
            raise ChainHeadUnavailable(
                "Windows chain-head mutex is unavailable"
            ) from exc

    def __enter__(self) -> "_WindowsNamedMutex":
        kernel32 = self._kernel32()
        kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_bool,
            ctypes.c_wchar_p,
        )
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ChainHeadUnavailable("Windows chain-head mutex could not be created")
        self._handle = int(handle)
        outcome = int(
            kernel32.WaitForSingleObject(handle, int(self.timeout_seconds * 1000))
        )
        if outcome == 0:
            return self
        self._close()
        if outcome == 0x102:
            raise ChainHeadConflict("Windows chain-head CAS timed out")
        if outcome == 0x80:
            raise ChainHeadUnavailable("Windows chain-head mutex was abandoned")
        raise ChainHeadUnavailable("Windows chain-head mutex wait failed")

    def _close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        kernel32 = self._kernel32()
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool
        kernel32.CloseHandle(handle)

    def __exit__(self, *_exc: object) -> None:
        handle = self._handle
        if handle is None:
            return
        kernel32 = self._kernel32()
        kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
        kernel32.ReleaseMutex.restype = ctypes.c_bool
        try:
            if not kernel32.ReleaseMutex(handle):
                raise ChainHeadUnavailable("Windows chain-head mutex release failed")
        finally:
            self._close()


class WindowsCredentialChainHeadStore:
    """Windows Credential Manager-backed CAS store with no file fallback."""

    _process_lock = threading.RLock()

    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        if platform.system() != "Windows":
            raise ChainHeadUnavailable(
                "Windows Credential Manager is unavailable on this host"
            )
        if type(timeout_seconds) not in {int, float} or isinstance(
            timeout_seconds, bool
        ):
            raise TypeError("timeout_seconds must be numeric")
        if not 0.05 <= float(timeout_seconds) <= 30.0:
            raise ValueError("timeout_seconds is outside the bounded range")
        self._timeout_seconds = float(timeout_seconds)

    @staticmethod
    def _reference(owner_profile_id: str) -> native_vault.SecretReference:
        profile = _identifier(owner_profile_id, "owner_profile_id")
        account = "owner-" + hashlib.sha256(profile.encode("ascii")).hexdigest()[:32]
        return native_vault.SecretReference(
            WINDOWS_HEAD_SERVICE,
            account,
            "Onyx owner-profile monotonic chain head",
        )

    @staticmethod
    def _encode(head: ChainHead) -> bytes:
        return _canonical(
            {
                "version": head.version,
                "owner_profile_id": head.owner_profile_id,
                "sequence": head.sequence,
                "head_mac": head.head_mac,
            }
        )

    @staticmethod
    def _decode(raw: bytes, owner_profile_id: str) -> ChainHead:
        if type(raw) is not bytes or not raw or len(raw) > 2048:
            raise ChainHeadUnavailable(
                "Windows chain head has an invalid representation"
            )
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ChainHeadUnavailable("Windows chain head is unreadable") from exc
        if type(value) is not dict or frozenset(value) != _HEAD_FIELDS:
            raise ChainHeadUnavailable("Windows chain head fields are invalid")
        head = ChainHead(
            value["version"],
            value["owner_profile_id"],
            value["sequence"],
            value["head_mac"],
        )
        return _validate_head(head, owner_profile_id)

    def load(self, owner_profile_id: str) -> ChainHead | None:
        reference = self._reference(owner_profile_id)
        try:
            raw = native_vault.windows_get(reference)
        except native_vault.NativeVaultError as exc:
            raise ChainHeadUnavailable(
                "Windows chain-head store is unavailable"
            ) from exc
        if raw is None:
            return None
        return self._decode(raw, owner_profile_id)

    def compare_and_set(
        self,
        owner_profile_id: str,
        expected: ChainHead | None,
        desired: ChainHead,
    ) -> bool:
        profile = _identifier(owner_profile_id, "owner_profile_id")
        if expected is not None:
            _validate_head(expected, profile)
        _validate_head(desired, profile)
        _validate_head_transition(expected, desired, profile)
        reference = self._reference(profile)
        with (
            self._process_lock,
            _WindowsNamedMutex(profile, timeout_seconds=self._timeout_seconds),
        ):
            observed = self.load(profile)
            if not _same_head(observed, expected):
                return False
            encoded = self._encode(desired)
            try:
                native_vault.windows_set(reference, encoded)
                readback = native_vault.windows_get(reference)
            except native_vault.NativeVaultError as exc:
                raise ChainHeadUnavailable("Windows chain-head CAS failed") from exc
            if readback is None or not hmac.compare_digest(readback, encoded):
                raise ChainHeadUnavailable("Windows chain-head CAS readback failed")
            return True


class AuthenticatedJournalBackend:
    """Bounded authenticated append-chain; monotonicity comes from ChainHeadStore."""

    def __init__(
        self,
        path: Path | str,
        *,
        key: bytes,
        owner_profile_id: str,
        runtime_instance: str,
    ) -> None:
        if type(key) is not bytes or len(key) != 32:
            raise TypeError("journal key must be exact bytes of length 32")
        self.path = Path(path)
        if not self.path.is_absolute():
            raise TypeError("journal path must be absolute")
        self._key = bytes(key)
        self.owner_profile_id = _identifier(owner_profile_id, "owner_profile_id")
        self.runtime_instance = _identifier(runtime_instance, "runtime_instance")

    def _mac(self, raw: dict[str, Any]) -> str:
        return hmac.new(
            self._key,
            _canonical({field: raw[field] for field in _MAC_FIELDS}),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size)

    def _safe_file(self) -> os.stat_result:
        try:
            info = self.path.lstat()
        except OSError as exc:
            raise JournalIntegrityError("Owner journal path is unavailable") from exc
        attributes = getattr(info, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            self.path.is_symlink()
            or attributes & reparse
            or not stat.S_ISREG(info.st_mode)
        ):
            raise JournalIntegrityError("Owner journal must be a regular non-link file")
        if info.st_size > MAX_JOURNAL_BYTES:
            raise JournalIntegrityError("Owner journal exceeds the byte limit")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
            raise JournalIntegrityError("Owner journal permissions are not private")
        return info

    def _read_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            raise JournalIntegrityError("Owner journal is missing")
        before = self._safe_file()
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags)
            with os.fdopen(fd, "rb") as handle:
                opened = os.fstat(handle.fileno())
                if self._identity(opened) != self._identity(before):
                    raise JournalIntegrityError("Owner journal changed while opening")
                raw = handle.read(MAX_JOURNAL_BYTES + 1)
        except JournalIntegrityError:
            raise
        except OSError as exc:
            raise JournalIntegrityError("Owner journal is unreadable") from exc
        if len(raw) > MAX_JOURNAL_BYTES:
            raise JournalIntegrityError("Owner journal exceeds the byte limit")
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise JournalIntegrityError("Owner journal is unreadable") from exc
        if type(value) is not dict or frozenset(value) != _ENVELOPE_FIELDS:
            raise JournalIntegrityError("Owner journal envelope is invalid")
        if value["schema"] != JOURNAL_SCHEMA or type(value["records"]) is not list:
            raise JournalIntegrityError("Owner journal schema is invalid")
        if len(value["records"]) > MAX_JOURNAL_RECORDS:
            raise JournalIntegrityError("Owner journal record count is invalid")
        return value

    def _validate_record(
        self,
        raw: object,
        *,
        sequence: int,
        previous_mac: str,
        previous: JournalEntry | None,
    ) -> JournalEntry:
        if type(raw) is not dict or frozenset(raw) != _RECORD_FIELDS:
            raise JournalIntegrityError("Owner journal record fields are invalid")
        if type(raw["version"]) is not int or raw["version"] != PROFILE_SCHEMA_VERSION:
            raise JournalIntegrityError("Owner journal version is invalid")
        if raw["owner_profile_id"] != self.owner_profile_id:
            raise JournalIntegrityError("Owner journal profile binding is invalid")
        if raw["runtime_instance"] != self.runtime_instance:
            raise JournalIntegrityError("Owner journal runtime binding is invalid")
        if type(raw["sequence"]) is not int or raw["sequence"] != sequence:
            raise JournalIntegrityError("Owner journal sequence is invalid")
        if type(raw["operation"]) is not str or raw["operation"] not in {
            "set",
            "forget",
        }:
            raise JournalIntegrityError("Owner journal operation is invalid")
        if type(raw["decision_state"]) is not str:
            raise JournalIntegrityError("Owner journal state is invalid")
        try:
            state = JournalState(raw["decision_state"])
        except ValueError as exc:
            raise JournalIntegrityError("Owner journal state is invalid") from exc
        prior = _name(raw["prior_name"], nullable=True)
        target = _name(raw["target_name"], nullable=True)
        if (raw["operation"] == "set") != (target is not None):
            raise JournalIntegrityError("Owner journal target is invalid")
        if type(raw["nonce"]) is not str or not _LOWER_HEX_64.fullmatch(raw["nonce"]):
            raise JournalIntegrityError("Owner journal nonce is invalid")
        if type(raw["previous_mac"]) is not str or raw["previous_mac"] != previous_mac:
            raise JournalIntegrityError("Owner journal predecessor is invalid")
        if type(raw["mac"]) is not str or not _LOWER_HEX_64.fullmatch(raw["mac"]):
            raise JournalIntegrityError("Owner journal authenticator is invalid")
        if not hmac.compare_digest(self._mac(raw), raw["mac"]):
            raise JournalIntegrityError("Owner journal authentication failed")
        entry = JournalEntry(
            raw["sequence"],
            state,
            raw["operation"],
            prior,
            target,
            raw["nonce"],
            raw["mac"],
        )
        if previous is None:
            if entry.state is not JournalState.PREPARED:
                raise JournalIntegrityError("Owner journal starts without preparation")
        elif previous.state is JournalState.PREPARED:
            if entry.state not in {JournalState.COMMITTED, JournalState.COMPENSATED}:
                raise JournalIntegrityError("Owner journal transition is invalid")
            if (
                entry.operation,
                entry.prior_name,
                entry.target_name,
                entry.nonce,
            ) != (
                previous.operation,
                previous.prior_name,
                previous.target_name,
                previous.nonce,
            ):
                raise JournalIntegrityError("Owner journal decision binding is invalid")
        elif entry.state is not JournalState.PREPARED:
            raise JournalIntegrityError("Owner journal transaction boundary is invalid")
        return entry

    def read_all(self) -> list[JournalEntry]:
        records = self._read_raw()["records"]
        result: list[JournalEntry] = []
        previous_mac = GENESIS_MAC
        for sequence, raw in enumerate(records, start=1):
            entry = self._validate_record(
                raw,
                sequence=sequence,
                previous_mac=previous_mac,
                previous=result[-1] if result else None,
            )
            result.append(entry)
            previous_mac = entry.mac
        return result

    def bootstrap_empty(self) -> None:
        if self.path.exists():
            if self.read_all():
                raise JournalIntegrityError("Owner journal is not empty")
            return
        self._atomic_write({"schema": JOURNAL_SCHEMA, "records": []}, expected=None)

    def _raw_record(self, entry: JournalEntry, previous_mac: str) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "version": PROFILE_SCHEMA_VERSION,
            "owner_profile_id": self.owner_profile_id,
            "runtime_instance": self.runtime_instance,
            "sequence": entry.sequence,
            "operation": entry.operation,
            "prior_name": entry.prior_name,
            "target_name": entry.target_name,
            "decision_state": entry.state.value,
            "nonce": entry.nonce,
            "previous_mac": previous_mac,
        }
        raw["mac"] = self._mac(raw)
        return raw

    def _atomic_write(
        self, payload: dict[str, Any], *, expected: os.stat_result | None
    ) -> None:
        encoded = _canonical(payload) + b"\n"
        if len(encoded) > MAX_JOURNAL_BYTES:
            raise JournalIntegrityError("Owner journal exceeds the byte limit")
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if parent.is_symlink() or not parent.is_dir():
            raise JournalIntegrityError("Owner journal directory is invalid")
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=parent
        )
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if expected is None:
                if self.path.exists():
                    raise ChainHeadConflict(
                        "Owner journal appeared during initialization"
                    )
            else:
                current = self._safe_file()
                if self._identity(current) != self._identity(expected):
                    raise ChainHeadConflict("Owner journal changed during update")
            os.replace(temporary, self.path)
            if os.name != "nt":
                os.chmod(self.path, 0o600)
                directory_fd = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def append(self, entry: JournalEntry) -> JournalEntry:
        if type(entry) is not JournalEntry:
            raise TypeError("journal entry must be an exact JournalEntry")
        if type(entry.state) is not JournalState:
            raise JournalIntegrityError("Owner journal append state is invalid")
        if type(entry.operation) is not str or entry.operation not in {"set", "forget"}:
            raise JournalIntegrityError("Owner journal append operation is invalid")
        _name(entry.prior_name, nullable=True)
        _name(entry.target_name, nullable=True)
        if (entry.operation == "set") != (entry.target_name is not None):
            raise JournalIntegrityError("Owner journal append target is invalid")
        if type(entry.sequence) is not int or entry.sequence < 1:
            raise JournalIntegrityError("Owner journal append sequence is invalid")
        if type(entry.nonce) is not str or not _LOWER_HEX_64.fullmatch(entry.nonce):
            raise JournalIntegrityError("Owner journal append nonce is invalid")
        expected = self._safe_file()
        current_raw = self._read_raw()
        records = self.read_all()
        latest = records[-1] if records else None
        if entry.sequence != len(records) + 1:
            raise JournalIntegrityError("Owner journal append sequence is stale")
        if latest is None or latest.state is not JournalState.PREPARED:
            if entry.state is not JournalState.PREPARED:
                raise JournalIntegrityError("Owner journal decision lacks preparation")
        else:
            if entry.state not in {JournalState.COMMITTED, JournalState.COMPENSATED}:
                raise JournalIntegrityError("Owner journal preparation is unresolved")
            if (
                entry.operation,
                entry.prior_name,
                entry.target_name,
                entry.nonce,
            ) != (
                latest.operation,
                latest.prior_name,
                latest.target_name,
                latest.nonce,
            ):
                raise JournalIntegrityError(
                    "Owner journal decision does not match preparation"
                )
        if len(records) >= MAX_JOURNAL_RECORDS:
            raise JournalIntegrityError("Owner journal capacity is exhausted")
        raw = self._raw_record(entry, latest.mac if latest else GENESIS_MAC)
        payload = {"schema": JOURNAL_SCHEMA, "records": [*current_raw["records"], raw]}
        self._atomic_write(payload, expected=expected)
        observed = self.read_all()[-1]
        if (
            observed.sequence,
            observed.state,
            observed.operation,
            observed.prior_name,
            observed.target_name,
            observed.nonce,
        ) != (
            entry.sequence,
            entry.state,
            entry.operation,
            entry.prior_name,
            entry.target_name,
            entry.nonce,
        ):
            raise JournalIntegrityError("Owner journal append readback failed")
        return observed


@dataclass(frozen=True, slots=True)
class _Consistency:
    anchor: ChainHead
    latest: JournalEntry | None
    baseline: ChainHead
    pending: JournalEntry | None


class OwnerProfileAuthority(v2.OwnerProfileAuthority):
    """Rollback-resistant owner profile authority with sticky fail-closed state."""

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        memory: v1.PreferenceMemory,
        journal_path: Path | str,
        journal_key: bytes,
        owner_profile_id: str,
        runtime_instance: str,
        chain_head_store: ChainHeadStore,
    ) -> None:
        if not isinstance(chain_head_store, ChainHeadStore):
            raise TypeError(
                "chain_head_store must implement the sanctioned CAS protocol"
            )
        super().__init__(config_path=config_path, memory=memory)
        journal_resolved = Path(journal_path).resolve(strict=False)
        if journal_resolved == self._config_path.resolve(strict=False):
            raise TypeError("journal path must be separate from owner settings")
        memory_path = getattr(memory, "path", None)
        if memory_path is None:
            memory_path = getattr(getattr(memory, "delegate", None), "path", None)
        if memory_path is not None and journal_resolved == Path(memory_path).resolve(
            strict=False
        ):
            raise TypeError("journal path must be separate from semantic memory")
        self._owner_profile_id = _identifier(owner_profile_id, "owner_profile_id")
        self._journal = AuthenticatedJournalBackend(
            journal_resolved,
            key=journal_key,
            owner_profile_id=self._owner_profile_id,
            runtime_instance=runtime_instance,
        )
        self._chain_head_store = chain_head_store
        self._last_failure: OwnerProfileFailure | None = None
        self._last_cleanup_failure: StageDiagnostic | None = None

    @classmethod
    def bootstrap(
        cls,
        *,
        config_path: Path,
        memory: v1.PreferenceMemory,
        journal_path: Path,
        journal_key: bytes,
        owner_profile_id: str,
        runtime_instance: str,
        chain_head_store: ChainHeadStore,
    ) -> "OwnerProfileAuthority":
        """Explicit first-install provisioning; ordinary reconcile never bootstraps."""

        authority = cls(
            config_path=config_path,
            memory=memory,
            journal_path=journal_path,
            journal_key=journal_key,
            owner_profile_id=owner_profile_id,
            runtime_instance=runtime_instance,
            chain_head_store=chain_head_store,
        )
        authority._journal.bootstrap_empty()
        observed = authority._load_anchor(required=False)
        genesis = genesis_head(authority._owner_profile_id)
        if observed is None:
            try:
                stored = chain_head_store.compare_and_set(
                    authority._owner_profile_id, None, genesis
                )
            except Exception as exc:
                raise ChainHeadUnavailable("Owner chain-head bootstrap failed") from exc
            if not stored:
                observed = authority._load_anchor(required=True)
        else:
            _validate_head(observed, authority._owner_profile_id)
        observed = authority._load_anchor(required=True)
        if not _same_head(observed, genesis):
            raise ChainHeadConflict(
                "Owner chain-head bootstrap found non-genesis state"
            )
        return authority

    @classmethod
    def from_existing_stores(
        cls,
        *,
        journal_key: bytes,
        owner_profile_id: str,
        runtime_instance: str,
        chain_head_store: ChainHeadStore,
        journal_path: Path | None = None,
    ) -> "OwnerProfileAuthority":
        from core.paths import runtime_dir
        from memory.memory_manager import get_store

        return cls(
            config_path=v1.config_file(),
            memory=get_store(),
            journal_path=journal_path or (runtime_dir() / JOURNAL_FILENAME),
            journal_key=journal_key,
            owner_profile_id=owner_profile_id,
            runtime_instance=runtime_instance,
            chain_head_store=chain_head_store,
        )

    @property
    def last_failure(self) -> OwnerProfileFailure | None:
        return self._last_failure

    @property
    def last_cleanup_failure(self) -> StageDiagnostic | None:
        return self._last_cleanup_failure

    @property
    def journal_backend(self) -> AuthenticatedJournalBackend:
        return self._journal

    def _latch(
        self,
        operation: str,
        stage: str,
        error: Exception,
        recovery: tuple[tuple[str, Exception], ...] = (),
        *,
        journal_state: JournalState | None = None,
        decision: JournalState | None = None,
        divergence: bool = True,
    ) -> None:
        root = self._root_cause(error)
        self._degraded_latched = True
        self._last_failure = OwnerProfileFailure(
            operation,
            stage,
            self._error_type(root),
            tuple(
                StageDiagnostic(
                    item_stage, self._error_type(self._root_cause(item_error))
                )
                for item_stage, item_error in recovery
            ),
            journal_state.value if journal_state else None,
            decision.value if decision else None,
            divergence,
        )

    def _load_anchor(self, *, required: bool) -> ChainHead | None:
        try:
            value = self._chain_head_store.load(self._owner_profile_id)
        except Exception as exc:
            raise ChainHeadUnavailable("Owner chain-head store is unavailable") from exc
        if value is None:
            if required:
                raise ChainHeadUnavailable("Owner chain head is missing")
            return None
        return _validate_head(value, self._owner_profile_id)

    def _semantic_state(self) -> str | None:
        try:
            records = self._memory.list(kind="semantic", limit=None)
        except Exception as exc:
            raise OwnerProfileError("Owner preference memory is unavailable") from exc
        if any(
            record.category == v1.OWNER_MEMORY_CATEGORY
            and record.key in RESERVED_MEMORY_JOURNAL_KEYS
            for record in records
        ):
            raise JournalIntegrityError(
                "A journal-like semantic memory record was rejected"
            )
        owners = [
            record
            for record in records
            if record.category == v1.OWNER_MEMORY_CATEGORY
            and record.key == v1.OWNER_MEMORY_KEY
        ]
        if not owners:
            return None
        try:
            return normalize_display_name(owners[0].content)
        except InvalidDisplayName:
            return None

    def _terminal_before(
        self, records: list[JournalEntry], end: int
    ) -> JournalEntry | None:
        for entry in reversed(records[:end]):
            if entry.state in {JournalState.COMMITTED, JournalState.COMPENSATED}:
                return entry
        return None

    def _expected_baseline(
        self, records: list[JournalEntry], latest_index: int
    ) -> ChainHead:
        previous = self._terminal_before(records, latest_index)
        return (
            genesis_head(self._owner_profile_id)
            if previous is None
            else _head_for(self._owner_profile_id, previous)
        )

    def _advance_anchor(self, expected: ChainHead, desired: ChainHead) -> None:
        _validate_head_transition(expected, desired, self._owner_profile_id)
        try:
            advanced = self._chain_head_store.compare_and_set(
                self._owner_profile_id, expected, desired
            )
        except Exception as exc:
            try:
                observed = self._load_anchor(required=True)
            except Exception:
                raise ChainHeadUnavailable("Owner chain-head CAS failed") from exc
            if _same_head(observed, desired):
                return
            raise ChainHeadUnavailable("Owner chain-head CAS failed") from exc
        if advanced:
            observed = self._load_anchor(required=True)
            if _same_head(observed, desired):
                return
            raise ChainHeadConflict("Owner chain-head CAS readback diverged")
        observed = self._load_anchor(required=True)
        if _same_head(observed, desired):
            return
        raise ChainHeadConflict("Owner chain-head CAS conflict")

    def _consistency(self) -> _Consistency:
        records = self._journal.read_all()
        anchor = self._load_anchor(required=True)
        assert anchor is not None
        if not records:
            genesis = genesis_head(self._owner_profile_id)
            if not _same_head(anchor, genesis):
                raise ChainHeadConflict(
                    "Owner journal and chain head diverge at genesis"
                )
            return _Consistency(anchor, None, genesis, None)
        latest = records[-1]
        latest_index = len(records) - 1
        baseline = self._expected_baseline(records, latest_index)
        if latest.state is JournalState.PREPARED:
            if not _same_head(anchor, baseline):
                raise ChainHeadConflict(
                    "Pending owner journal does not extend the current chain head"
                )
            return _Consistency(anchor, latest, baseline, latest)
        desired = _head_for(self._owner_profile_id, latest)
        if _same_head(anchor, desired):
            return _Consistency(anchor, latest, desired, None)
        if _same_head(anchor, baseline):
            self._advance_anchor(baseline, desired)
            return _Consistency(desired, latest, desired, None)
        if anchor.sequence > latest.sequence:
            raise ChainHeadConflict(
                "Owner journal is rolled back behind the chain head"
            )
        if anchor.sequence < baseline.sequence:
            raise ChainHeadConflict("Owner chain head is stale")
        raise ChainHeadConflict("Owner journal and chain head mismatch")

    def _write_owner_value(self, value: str | None) -> list[tuple[str, Exception]]:
        failures: list[tuple[str, Exception]] = []
        try:
            self._write_config(value or "")
        except Exception as exc:
            failures.append(("write-config", self._root_cause(exc)))
        try:
            self._clear_memory() if value is None else self._write_memory(value)
        except Exception as exc:
            failures.append(("write-memory", self._root_cause(exc)))
        return failures

    def _verify_owner_value(
        self, value: str | None
    ) -> tuple[bool, list[tuple[str, Exception]]]:
        failures: list[tuple[str, Exception]] = []
        config_ok = memory_ok = False
        try:
            data, _raw = self._read_config()
            try:
                config_ok = (
                    normalize_display_name(data.get(v1.OWNER_CONFIG_KEY)) == value
                )
            except InvalidDisplayName:
                config_ok = value is None
        except Exception as exc:
            failures.append(("readback-config", self._root_cause(exc)))
        try:
            memory_ok = self._memory_name() == value
        except Exception as exc:
            failures.append(("readback-memory", self._root_cause(exc)))
        if not config_ok and not any(
            stage == "readback-config" for stage, _ in failures
        ):
            failures.append(
                ("readback-config", OwnerProfileError("Owner config mismatch"))
            )
        if not memory_ok and not any(
            stage == "readback-memory" for stage, _ in failures
        ):
            failures.append(
                ("readback-memory", OwnerProfileError("Owner memory mismatch"))
            )
        return config_ok and memory_ok, failures

    def _drive_value(
        self, value: str | None, *, prefix: str
    ) -> tuple[bool, tuple[tuple[str, Exception], ...]]:
        failures = [
            (f"{prefix}-{stage}", error)
            for stage, error in self._write_owner_value(value)
        ]
        verified, readback = self._verify_owner_value(value)
        failures.extend((f"{prefix}-{stage}", error) for stage, error in readback)
        return verified, tuple(failures)

    def _append_decision(
        self, prepared: JournalEntry, state: JournalState
    ) -> JournalEntry:
        decided = JournalEntry(
            prepared.sequence + 1,
            state,
            prepared.operation,
            prepared.prior_name,
            prepared.target_name,
            prepared.nonce,
        )
        write_error: Exception | None = None
        try:
            return self._journal.append(decided)
        except Exception as exc:
            write_error = exc
        records = self._journal.read_all()
        observed = records[-1] if records else None
        if observed is not None and (
            observed.sequence,
            observed.state,
            observed.operation,
            observed.prior_name,
            observed.target_name,
            observed.nonce,
        ) == (
            decided.sequence,
            decided.state,
            decided.operation,
            decided.prior_name,
            decided.target_name,
            decided.nonce,
        ):
            return observed
        raise write_error

    def _recover_pending(
        self, consistency: _Consistency
    ) -> tuple[str | None, tuple[tuple[str, Exception], ...]]:
        prepared = consistency.pending
        if prepared is None:
            raise OwnerProfileError("No pending owner transaction exists")
        verified, recovery = self._drive_value(prepared.prior_name, prefix="compensate")
        if not verified:
            raise OwnerProfileTransactionError(
                prepared.operation,
                OwnerProfileError("Owner compensation failed"),
                OwnerProfileError("Owner compensation failed"),
                recovery,
                None,
            )
        decided = self._append_decision(prepared, JournalState.COMPENSATED)
        desired = _head_for(self._owner_profile_id, decided)
        self._advance_anchor(consistency.baseline, desired)
        return prepared.prior_name, recovery

    def reconcile(self) -> OwnerProfileSnapshot:
        with v1._PROCESS_LOCK:
            if self._degraded_latched:
                return self._publish(self._snapshot.display_name, reconciled=False)
            chosen = self._snapshot.display_name
            recovery: tuple[tuple[str, Exception], ...] = ()
            stage = "verify-semantic-projection"
            try:
                memory_name = self._semantic_state()
                stage = "verify-journal-anchor"
                consistency = self._consistency()
                if consistency.pending is not None:
                    stage = "recover-prepared"
                    chosen, recovery = self._recover_pending(consistency)
                    self._degraded_latched = False
                    self._last_failure = None
                    return self._publish(chosen, reconciled=True)
                if consistency.latest is None:
                    stage = "read-genesis-config"
                    data, raw = self._read_config()
                    try:
                        config_name = normalize_display_name(
                            data.get(v1.OWNER_CONFIG_KEY)
                        )
                    except InvalidDisplayName:
                        config_name = None
                    chosen = config_name or memory_name
                    if config_name != memory_name:
                        raise ChainHeadConflict(
                            "Unanchored owner projection drift requires explicit provisioning"
                        )
                    if chosen is None and raw is not v1._MISSING and raw != "":
                        raise ChainHeadConflict(
                            "Unanchored owner placeholder cannot be rewritten"
                        )
                else:
                    chosen = (
                        consistency.latest.target_name
                        if consistency.latest.state is JournalState.COMMITTED
                        else consistency.latest.prior_name
                    )
                    stage = "verify-anchored-projections"
                    data, _raw = self._read_config()
                    try:
                        config_name = normalize_display_name(
                            data.get(v1.OWNER_CONFIG_KEY)
                        )
                    except InvalidDisplayName:
                        config_name = None
                    if config_name != chosen or memory_name != chosen:
                        stage = "repair-anchored-projections"
                        verified, recovery = self._drive_value(chosen, prefix="repair")
                        if not verified:
                            raise OwnerProfileError("Owner projection repair failed")
            except Exception as exc:
                self._latch("reconcile", stage, exc, recovery)
                return self._publish(chosen, reconciled=False)
            self._degraded_latched = False
            self._last_failure = None
            return self._publish(chosen, reconciled=True)

    def _capture_prior(self) -> tuple[str | None, _Consistency]:
        snapshot = self.reconcile()
        if snapshot.state is OwnerProfileState.DEGRADED:
            raise OwnerProfileError("Owner profile requires reconciliation")
        consistency = self._consistency()
        if consistency.pending is not None:
            raise ChainHeadConflict("Owner profile has a pending transaction")
        verified, failures = self._verify_owner_value(snapshot.display_name)
        if not verified:
            error = OwnerProfileError("Owner prior-state verification failed")
            self._latch("prepare", "verify-prior", error, tuple(failures))
            self._publish(snapshot.display_name, reconciled=False)
            raise error
        return snapshot.display_name, consistency

    def _abort_precommit(
        self,
        prepared: JournalEntry,
        baseline: ChainHead,
        operation_error: Exception,
        operation_stage: str,
    ) -> None:
        root = self._root_cause(operation_error)
        verified, recovery = self._drive_value(prepared.prior_name, prefix="compensate")
        decision: JournalState | None = None
        if verified:
            try:
                decided = self._append_decision(prepared, JournalState.COMPENSATED)
                self._advance_anchor(
                    baseline, _head_for(self._owner_profile_id, decided)
                )
                decision = JournalState.COMPENSATED
            except Exception as exc:
                recovery += (("decision-compensated", self._root_cause(exc)),)
        self._latch(
            prepared.operation,
            operation_stage,
            root,
            recovery,
            journal_state=JournalState.PREPARED,
            decision=decision,
            divergence=decision is None,
        )
        self._publish(prepared.prior_name, reconciled=False)
        raise OwnerProfileTransactionError(
            prepared.operation, operation_error, root, recovery, decision
        ) from operation_error

    def _apply(self, operation: str, target: str | None) -> OwnerProfileSnapshot:
        with v1._PROCESS_LOCK:
            prior, consistency = self._capture_prior()
            latest_sequence = consistency.latest.sequence if consistency.latest else 0
            prepared = JournalEntry(
                latest_sequence + 1,
                JournalState.PREPARED,
                operation,
                prior,
                target,
                secrets.token_hex(32),
            )
            try:
                prepared = self._journal.append(prepared)
            except Exception as exc:
                self._latch(operation, "prepare-journal", exc)
                self._publish(prior, reconciled=False)
                raise
            failures = self._write_owner_value(target)
            if failures:
                self._abort_precommit(
                    prepared, consistency.baseline, failures[0][1], failures[0][0]
                )
            verified, failures = self._verify_owner_value(target)
            if not verified:
                error = (
                    failures[0][1]
                    if failures
                    else OwnerProfileError("Target verification failed")
                )
                self._abort_precommit(
                    prepared,
                    consistency.baseline,
                    error,
                    failures[0][0] if failures else "verify-target",
                )
            try:
                committed = self._append_decision(prepared, JournalState.COMMITTED)
                self._advance_anchor(
                    consistency.baseline, _head_for(self._owner_profile_id, committed)
                )
            except Exception as exc:
                self._latch(
                    operation,
                    "advance-chain-head",
                    exc,
                    journal_state=JournalState.COMMITTED,
                    divergence=True,
                )
                self._publish(target, reconciled=False)
                raise OwnerProfileTransactionError(
                    operation, exc, self._root_cause(exc), (), None
                ) from exc
            self._degraded_latched = False
            self._last_failure = None
            self._contact_prompted = operation != "forget"
            return self._publish(target, reconciled=True)

    def set_name(self, value: object) -> OwnerProfileSnapshot:
        name = normalize_display_name(value)
        if name is None:
            raise InvalidDisplayName("A real display name is required")
        return self._apply("set", name)

    def correct_name(self, value: object) -> OwnerProfileSnapshot:
        return self.set_name(value)

    def forget_name(self) -> OwnerProfileSnapshot:
        return self._apply("forget", None)


__all__ = [
    "AuthenticatedJournalBackend",
    "ChainHead",
    "ChainHeadConflict",
    "ChainHeadError",
    "ChainHeadStore",
    "ChainHeadUnavailable",
    "FALLBACK_ADDRESS",
    "FALLBACK_LANGUAGE",
    "FALLBACK_TRANSLATION_POLICY",
    "FIRST_CONTACT_QUESTION",
    "InvalidDisplayName",
    "JournalEntry",
    "JournalIntegrityError",
    "JournalState",
    "OwnerProfileAuthority",
    "OwnerProfileError",
    "OwnerProfileFailure",
    "OwnerProfileSnapshot",
    "OwnerProfileState",
    "OwnerProfileTransactionError",
    "StageDiagnostic",
    "WindowsCredentialChainHeadStore",
    "genesis_head",
    "normalize_display_name",
]
