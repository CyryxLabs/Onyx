"""Owner Profile V8: 63-bit chain sequence and lease-only journal access.

V8 preserves the V7 authenticated journal format and capacity/lease protocol,
while decoupling monotonic chain sequence from retained record cardinality.
Compaction bounds bytes and records only; sequence continues up to signed
63-bit maximum.  Every journal read and write requires the active host lease.
Diagnostics after lease acquisition or release failure use cached state only.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import core.owner_profile_v1 as v1
import core.owner_profile_v6 as v6
import core.owner_profile_v7 as v7
from core import native_vault


MAX_CHAIN_SEQUENCE = (1 << 63) - 1
PROFILE_SCHEMA_VERSION = 8
JOURNAL_SCHEMA = v7.JOURNAL_SCHEMA
JOURNAL_FILENAME = "owner-profile-v8.journal.json"
MAX_JOURNAL_BYTES = v7.MAX_JOURNAL_BYTES
MAX_JOURNAL_RECORDS = v7.MAX_JOURNAL_RECORDS
LEASE_TIMEOUT_SECONDS = v7.LEASE_TIMEOUT_SECONDS
GENESIS_MAC = v7.GENESIS_MAC

FALLBACK_ADDRESS = v7.FALLBACK_ADDRESS
FALLBACK_LANGUAGE = v7.FALLBACK_LANGUAGE
FALLBACK_TRANSLATION_POLICY = v7.FALLBACK_TRANSLATION_POLICY
FIRST_CONTACT_QUESTION = v7.FIRST_CONTACT_QUESTION
InvalidDisplayName = v7.InvalidDisplayName
JournalEntry = v7.JournalEntry
JournalState = v7.JournalState
JournalIntegrityError = v7.JournalIntegrityError
OwnerProfileError = v7.OwnerProfileError
OwnerProfileSnapshot = v7.OwnerProfileSnapshot
OwnerProfileState = v7.OwnerProfileState
OwnerProfileFailure = v7.OwnerProfileFailure
OwnerProfileTransactionError = v7.OwnerProfileTransactionError
StageDiagnostic = v7.StageDiagnostic
HostTransactionLease = v7.HostTransactionLease
HostLeaseError = v7.HostLeaseError
HostLeaseConflict = v7.HostLeaseConflict
WindowsHostTransactionLease = v7.WindowsHostTransactionLease
normalize_display_name = v7.normalize_display_name


class ChainHeadError(OwnerProfileError):
    """Base class for V8 63-bit chain-head failures."""


class ChainHeadUnavailable(ChainHeadError):
    """The required chain-head store is missing, malformed, or unavailable."""


class ChainHeadConflict(ChainHeadError):
    """The monotonic chain-head CAS or journal binding diverged."""


@dataclass(frozen=True, slots=True)
class ChainHead:
    version: int
    owner_profile_id: str
    sequence: int
    head_mac: str


@runtime_checkable
class ChainHeadStore(Protocol):
    def load(self, owner_profile_id: str) -> ChainHead | None: ...

    def compare_and_set(
        self,
        owner_profile_id: str,
        expected: ChainHead | None,
        desired: ChainHead,
    ) -> bool: ...


def _validate_head(value: object, owner_profile_id: str) -> ChainHead:
    if type(value) is not ChainHead:
        raise ChainHeadUnavailable("Owner chain head has an invalid representation")
    if type(value.version) is not int or value.version != v6.CHAIN_HEAD_VERSION:
        raise ChainHeadUnavailable("Owner chain head version is invalid")
    if value.owner_profile_id != owner_profile_id:
        raise ChainHeadUnavailable("Owner chain head profile binding is invalid")
    if (
        type(value.sequence) is not int
        or value.sequence < 0
        or value.sequence > MAX_CHAIN_SEQUENCE
    ):
        raise ChainHeadUnavailable("Owner chain head sequence is invalid")
    if type(value.head_mac) is not str or not v6._LOWER_HEX_64.fullmatch(
        value.head_mac
    ):
        raise ChainHeadUnavailable("Owner chain head authenticator is invalid")
    if value.sequence == 0 and value.head_mac != GENESIS_MAC:
        raise ChainHeadUnavailable("Owner chain head genesis is invalid")
    if value.sequence > 0 and value.head_mac == GENESIS_MAC:
        raise ChainHeadUnavailable("Owner chain head authenticator is invalid")
    return value


def genesis_head(owner_profile_id: str) -> ChainHead:
    return ChainHead(
        v6.CHAIN_HEAD_VERSION,
        v6._identifier(owner_profile_id, "owner_profile_id"),
        0,
        GENESIS_MAC,
    )


def _same_head(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    try:
        left_encoded = v6._canonical(
            {
                "version": left.version,
                "owner_profile_id": left.owner_profile_id,
                "sequence": left.sequence,
                "head_mac": left.head_mac,
            }
        )
        right_encoded = v6._canonical(
            {
                "version": right.version,
                "owner_profile_id": right.owner_profile_id,
                "sequence": right.sequence,
                "head_mac": right.head_mac,
            }
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return hmac.compare_digest(left_encoded, right_encoded)


def _head_for(owner_profile_id: str, entry: JournalEntry) -> ChainHead:
    if entry.state not in {JournalState.COMMITTED, JournalState.COMPENSATED}:
        raise ChainHeadError(
            "Only a terminal journal record can advance the chain head"
        )
    if type(entry.sequence) is not int or not 1 <= entry.sequence <= MAX_CHAIN_SEQUENCE:
        raise ChainHeadError("Terminal journal sequence is outside the 63-bit range")
    return ChainHead(v6.CHAIN_HEAD_VERSION, owner_profile_id, entry.sequence, entry.mac)


def _validate_transition(
    expected: ChainHead | None, desired: ChainHead, owner_profile_id: str
) -> None:
    if expected is None:
        if not _same_head(desired, genesis_head(owner_profile_id)):
            raise ChainHeadConflict("Owner chain-head initialization must be genesis")
        return
    if expected.sequence > MAX_CHAIN_SEQUENCE - 2:
        raise ChainHeadConflict("Owner chain-head terminal sequence would overflow")
    if desired.sequence != expected.sequence + 2:
        raise ChainHeadConflict("Owner chain-head terminal increment is invalid")
    if hmac.compare_digest(desired.head_mac, expected.head_mac):
        raise ChainHeadConflict(
            "Owner chain-head transition did not change authenticator"
        )


class WindowsCredentialChainHeadStore:
    """V8 Windows Credential Manager CAS with 63-bit sequence validation."""

    def __init__(
        self,
        *,
        timeout_seconds: float = LEASE_TIMEOUT_SECONDS,
        host_lease: WindowsHostTransactionLease | None = None,
    ) -> None:
        if platform.system() != "Windows":
            raise ChainHeadUnavailable(
                "Windows Credential Manager is unavailable on this host"
            )
        if type(timeout_seconds) not in {int, float} or isinstance(
            timeout_seconds, bool
        ):
            raise TypeError("timeout_seconds must be numeric")
        timeout = float(timeout_seconds)
        if not 0.05 <= timeout <= 30.0:
            raise ValueError("timeout_seconds is outside the bounded range")
        self._timeout_seconds = timeout
        self._host_lease = host_lease or WindowsHostTransactionLease()

    @staticmethod
    def _reference(owner_profile_id: str) -> native_vault.SecretReference:
        profile = v6._identifier(owner_profile_id, "owner_profile_id")
        account = "owner-" + hashlib.sha256(profile.encode("ascii")).hexdigest()[:32]
        return native_vault.SecretReference(
            v6.WINDOWS_HEAD_SERVICE,
            account,
            "Onyx owner-profile monotonic chain head",
        )

    @staticmethod
    def _encode(head: ChainHead) -> bytes:
        return v6._canonical(
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
        if type(value) is not dict or frozenset(value) != v6._HEAD_FIELDS:
            raise ChainHeadUnavailable("Windows chain head fields are invalid")
        return _validate_head(
            ChainHead(
                value["version"],
                value["owner_profile_id"],
                value["sequence"],
                value["head_mac"],
            ),
            owner_profile_id,
        )

    def load(self, owner_profile_id: str) -> ChainHead | None:
        reference = self._reference(owner_profile_id)
        try:
            raw = native_vault.windows_get(reference)
        except native_vault.NativeVaultError as exc:
            raise ChainHeadUnavailable(
                "Windows chain-head store is unavailable"
            ) from exc
        return None if raw is None else self._decode(raw, owner_profile_id)

    def compare_and_set(
        self,
        owner_profile_id: str,
        expected: ChainHead | None,
        desired: ChainHead,
    ) -> bool:
        profile = v6._identifier(owner_profile_id, "owner_profile_id")
        if expected is not None:
            _validate_head(expected, profile)
        _validate_head(desired, profile)
        _validate_transition(expected, desired, profile)
        reference = self._reference(profile)
        with self._host_lease.hold(profile, timeout_seconds=self._timeout_seconds):
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


class AuthenticatedJournalBackend(v7.AuthenticatedJournalBackend):
    """Lease-only V7 journal whose base sequence spans the full 63-bit range."""

    def __init__(self, *args: Any, state_observer: Any, **kwargs: Any) -> None:
        if not callable(state_observer):
            raise TypeError("state_observer is required")
        self._state_observer = state_observer
        super().__init__(*args, **kwargs)

    def _safe_file(self) -> os.stat_result:
        self._require_lease()
        return super()._safe_file()

    def _read_raw(self) -> dict[str, Any]:
        self._require_lease()
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
                encoded = handle.read(self.max_journal_bytes + 1)
        except JournalIntegrityError:
            raise
        except OSError as exc:
            raise JournalIntegrityError("Owner journal is unreadable") from exc
        if len(encoded) > self.max_journal_bytes:
            raise JournalIntegrityError("Owner journal exceeds the byte limit")
        try:
            value = json.loads(encoded.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise JournalIntegrityError("Owner journal is unreadable") from exc
        if type(value) is not dict or frozenset(value) != v7._ENVELOPE_FIELDS:
            raise JournalIntegrityError("Owner journal envelope is invalid")
        if value["schema"] != JOURNAL_SCHEMA or type(value["records"]) is not list:
            raise JournalIntegrityError("Owner journal schema is invalid")
        if len(value["records"]) > self.max_journal_records:
            raise JournalIntegrityError("Owner journal record count is invalid")
        base = value["base"]
        if type(base) is not dict or frozenset(base) != v7._BASE_FIELDS:
            raise JournalIntegrityError("Owner journal base fields are invalid")
        if (
            type(base["version"]) is not int
            or base["version"] != v7.PROFILE_SCHEMA_VERSION
        ):
            raise JournalIntegrityError("Owner journal base version is invalid")
        if base["owner_profile_id"] != self.owner_profile_id:
            raise JournalIntegrityError("Owner journal base profile binding is invalid")
        if base["runtime_instance"] != self.runtime_instance:
            raise JournalIntegrityError("Owner journal base runtime binding is invalid")
        if (
            type(base["sequence"]) is not int
            or base["sequence"] < 0
            or base["sequence"] > MAX_CHAIN_SEQUENCE
        ):
            raise JournalIntegrityError("Owner journal base sequence is invalid")
        if type(base["head_mac"]) is not str or not v6._LOWER_HEX_64.fullmatch(
            base["head_mac"]
        ):
            raise JournalIntegrityError("Owner journal base authenticator is invalid")
        if base["sequence"] == 0 and base["head_mac"] != GENESIS_MAC:
            raise JournalIntegrityError("Owner journal base genesis is invalid")
        if base["sequence"] > 0 and base["head_mac"] == GENESIS_MAC:
            raise JournalIntegrityError("Owner journal base authenticator is invalid")
        if base["sequence"] + len(value["records"]) > MAX_CHAIN_SEQUENCE:
            raise JournalIntegrityError(
                "Owner journal retained sequence exceeds 63-bit range"
            )
        return value

    def read_snapshot(self) -> tuple[ChainHead, list[JournalEntry], dict[str, Any]]:
        self._require_lease()
        raw = self._read_raw()
        base = raw["base"]
        base_head = _validate_head(
            ChainHead(
                v6.CHAIN_HEAD_VERSION,
                self.owner_profile_id,
                base["sequence"],
                base["head_mac"],
            ),
            self.owner_profile_id,
        )
        records: list[JournalEntry] = []
        previous_mac = base_head.head_mac
        for offset, item in enumerate(raw["records"], start=1):
            entry = self._validate_record(
                item,
                sequence=base_head.sequence + offset,
                previous_mac=previous_mac,
                previous=records[-1] if records else None,
            )
            records.append(entry)
            previous_mac = entry.mac
        state = records[-1].state.value if records else "EMPTY"
        self._state_observer(state)
        return base_head, records, raw

    def read_all(self) -> list[JournalEntry]:
        self._require_lease()
        return self.read_snapshot()[1]

    def bootstrap_empty(self) -> None:
        self._require_lease()
        return super().bootstrap_empty()

    def _atomic_write(
        self, payload: dict[str, Any], *, expected: os.stat_result | None
    ) -> None:
        self._require_lease()
        return super()._atomic_write(payload, expected=expected)

    def compact_terminal_history(self, current_anchor: ChainHead) -> bool:
        self._require_lease()
        return super().compact_terminal_history(current_anchor)

    def pair_required_bytes(self, prepared: JournalEntry) -> int:
        self._require_lease()
        return super().pair_required_bytes(prepared)

    def append_prepared(
        self, entry: JournalEntry, *, current_anchor: ChainHead
    ) -> JournalEntry:
        self._require_lease()
        if type(entry.sequence) is not int or entry.sequence < 1:
            raise JournalIntegrityError("Owner journal PREPARED sequence is invalid")
        if entry.sequence >= MAX_CHAIN_SEQUENCE:
            raise JournalIntegrityError(
                "Owner journal terminal sequence would exceed 63-bit range"
            )
        if current_anchor.sequence != entry.sequence - 1:
            raise ChainHeadConflict(
                "PREPARED must increment the anchored sequence exactly"
            )
        return super().append_prepared(entry, current_anchor=current_anchor)

    def append_terminal(self, entry: JournalEntry) -> JournalEntry:
        self._require_lease()
        if (
            type(entry.sequence) is not int
            or entry.sequence < 2
            or entry.sequence > MAX_CHAIN_SEQUENCE
        ):
            raise JournalIntegrityError("Owner journal terminal sequence is invalid")
        return super().append_terminal(entry)


class OwnerProfileAuthority(v7.OwnerProfileAuthority):
    """V8 authority with cached diagnostics and 63-bit monotonic chain state."""

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
        transaction_lease: HostTransactionLease,
        lease_timeout_seconds: float = LEASE_TIMEOUT_SECONDS,
        _journal_max_bytes: int = MAX_JOURNAL_BYTES,
        _journal_max_records: int = MAX_JOURNAL_RECORDS,
    ) -> None:
        if not isinstance(chain_head_store, ChainHeadStore):
            raise TypeError("chain_head_store must implement the V8 CAS protocol")
        super().__init__(
            config_path=config_path,
            memory=memory,
            journal_path=journal_path,
            journal_key=journal_key,
            owner_profile_id=owner_profile_id,
            runtime_instance=runtime_instance,
            chain_head_store=chain_head_store,
            transaction_lease=transaction_lease,
            lease_timeout_seconds=lease_timeout_seconds,
            _journal_max_bytes=_journal_max_bytes,
            _journal_max_records=_journal_max_records,
        )
        self._cached_journal_state = "unavailable"
        self._journal = AuthenticatedJournalBackend(
            Path(journal_path).resolve(strict=False),
            key=journal_key,
            owner_profile_id=self._owner_profile_id,
            runtime_instance=runtime_instance,
            lease_held=self._lease_is_held,
            state_observer=self._cache_journal_state,
            max_journal_bytes=_journal_max_bytes,
            max_journal_records=_journal_max_records,
        )

    def _cache_journal_state(self, state: str) -> None:
        if self._lease_is_held() and type(state) is str:
            self._cached_journal_state = state

    def _latch(
        self,
        operation: str,
        stage: str,
        error: Exception,
        recovery: tuple[tuple[str, Exception], ...] = (),
        *,
        journal_state: JournalState | str | None = None,
        decision: JournalState | None = None,
        divergence: bool = True,
    ) -> None:
        root = self._root_cause(error)
        self._degraded_latched = True
        if isinstance(journal_state, JournalState):
            rendered_state = journal_state.value
        elif type(journal_state) is str:
            rendered_state = journal_state
        else:
            rendered_state = None
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
            rendered_state,
            decision.value if decision else None,
            divergence,
        )

    def _diagnostic_journal_state(self) -> JournalState | str:
        if not self._lease_is_held():
            return self._cached_journal_state
        try:
            records = self._journal.read_all()
        except Exception:
            return "unavailable"
        if not records:
            self._cached_journal_state = "EMPTY"
            return "EMPTY"
        self._cached_journal_state = records[-1].state.value
        return records[-1].state

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

    def _advance_anchor(self, expected: ChainHead, desired: object) -> None:
        normalized = _validate_head(
            ChainHead(
                desired.version,
                desired.owner_profile_id,
                desired.sequence,
                desired.head_mac,
            ),
            self._owner_profile_id,
        )
        expected = _validate_head(expected, self._owner_profile_id)
        _validate_transition(expected, normalized, self._owner_profile_id)
        try:
            advanced = self._chain_head_store.compare_and_set(
                self._owner_profile_id, expected, normalized
            )
        except Exception as exc:
            try:
                observed = self._load_anchor(required=True)
            except Exception:
                raise ChainHeadUnavailable("Owner chain-head CAS failed") from exc
            if _same_head(observed, normalized):
                return
            raise ChainHeadUnavailable("Owner chain-head CAS failed") from exc
        if advanced:
            observed = self._load_anchor(required=True)
            if _same_head(observed, normalized):
                return
            raise ChainHeadConflict("Owner chain-head CAS readback diverged")
        observed = self._load_anchor(required=True)
        if _same_head(observed, normalized):
            return
        raise ChainHeadConflict("Owner chain-head CAS conflict")

    def _terminal_before(
        self, records: list[JournalEntry], end: int
    ) -> JournalEntry | None:
        for entry in reversed(records[:end]):
            if entry.state in {JournalState.COMMITTED, JournalState.COMPENSATED}:
                return entry
        return None

    def _consistency(self) -> v6._Consistency:
        if not self._lease_is_held():
            raise HostLeaseError(
                "Consistency verification requires the host-wide lease"
            )
        base, records, _raw = self._journal.read_snapshot()
        anchor = self._load_anchor(required=True)
        assert anchor is not None
        if not records:
            if not _same_head(anchor, base):
                raise ChainHeadConflict(
                    "Owner journal snapshot base and chain head diverge"
                )
            return v6._Consistency(anchor, None, base, None)
        latest = records[-1]
        previous = self._terminal_before(records, len(records) - 1)
        baseline = (
            base if previous is None else _head_for(self._owner_profile_id, previous)
        )
        if latest.state is JournalState.PREPARED:
            if not _same_head(anchor, baseline):
                raise ChainHeadConflict(
                    "Pending owner journal does not extend current chain head"
                )
            return v6._Consistency(anchor, latest, baseline, latest)
        desired = _head_for(self._owner_profile_id, latest)
        if _same_head(anchor, desired):
            return v6._Consistency(anchor, latest, desired, None)
        if _same_head(anchor, baseline):
            self._advance_anchor(baseline, desired)
            return v6._Consistency(desired, latest, desired, None)
        if anchor.sequence > latest.sequence:
            raise ChainHeadConflict("Owner journal is rolled back behind chain head")
        if anchor.sequence < baseline.sequence:
            raise ChainHeadConflict("Owner chain head is stale")
        raise ChainHeadConflict("Owner journal and chain head mismatch")

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
        transaction_lease: HostTransactionLease,
    ) -> "OwnerProfileAuthority":
        authority = cls(
            config_path=config_path,
            memory=memory,
            journal_path=journal_path,
            journal_key=journal_key,
            owner_profile_id=owner_profile_id,
            runtime_instance=runtime_instance,
            chain_head_store=chain_head_store,
            transaction_lease=transaction_lease,
        )
        with authority._hold_transaction_lease():
            authority._journal.bootstrap_empty()
            observed = authority._load_anchor(required=False)
            genesis = genesis_head(authority._owner_profile_id)
            if observed is None:
                try:
                    stored = chain_head_store.compare_and_set(
                        authority._owner_profile_id, None, genesis
                    )
                except Exception as exc:
                    raise ChainHeadUnavailable(
                        "Owner chain-head bootstrap failed"
                    ) from exc
                if not stored:
                    observed = authority._load_anchor(required=True)
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
        transaction_lease: HostTransactionLease,
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
            transaction_lease=transaction_lease,
        )


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
    "HostLeaseConflict",
    "HostLeaseError",
    "HostTransactionLease",
    "InvalidDisplayName",
    "JournalEntry",
    "JournalIntegrityError",
    "JournalState",
    "MAX_CHAIN_SEQUENCE",
    "OwnerProfileAuthority",
    "OwnerProfileError",
    "OwnerProfileFailure",
    "OwnerProfileSnapshot",
    "OwnerProfileState",
    "OwnerProfileTransactionError",
    "StageDiagnostic",
    "WindowsCredentialChainHeadStore",
    "WindowsHostTransactionLease",
    "genesis_head",
    "normalize_display_name",
]
