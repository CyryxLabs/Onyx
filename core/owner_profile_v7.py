"""Owner Profile V7: pair-reserved journal under a host-wide transaction lease.

V7 preserves the V6 chain-head CAS and adds two invariants:

* a PREPARED record is admitted only when the exact canonical PREPARED plus
  the larger of its COMMITTED/COMPENSATED terminal records is guaranteed to
  fit, including JSON delimiters and the trailing newline; and
* reconcile, crash recovery, and the complete journal -> projections ->
  terminal -> chain-head CAS transaction execute under one required host-wide
  reentrant lease.

The candidate is isolated and default-off.  It does not wire or restart Onyx.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import platform
import stat
import tempfile
import threading
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol, runtime_checkable

import core.owner_profile_v1 as v1
import core.owner_profile_v6 as v6


PROFILE_SCHEMA_VERSION = 7
JOURNAL_SCHEMA = "onyx.owner-profile-journal.v7"
JOURNAL_FILENAME = "owner-profile-v7.journal.json"
MAX_JOURNAL_BYTES = v6.MAX_JOURNAL_BYTES
MAX_JOURNAL_RECORDS = v6.MAX_JOURNAL_RECORDS
LEASE_TIMEOUT_SECONDS = 5.0
GENESIS_MAC = v6.GENESIS_MAC

FALLBACK_ADDRESS = v6.FALLBACK_ADDRESS
FALLBACK_LANGUAGE = v6.FALLBACK_LANGUAGE
FALLBACK_TRANSLATION_POLICY = v6.FALLBACK_TRANSLATION_POLICY
FIRST_CONTACT_QUESTION = v6.FIRST_CONTACT_QUESTION
InvalidDisplayName = v6.InvalidDisplayName
JournalEntry = v6.JournalEntry
JournalState = v6.JournalState
ChainHead = v6.ChainHead
ChainHeadStore = v6.ChainHeadStore
ChainHeadError = v6.ChainHeadError
ChainHeadConflict = v6.ChainHeadConflict
ChainHeadUnavailable = v6.ChainHeadUnavailable
JournalIntegrityError = v6.JournalIntegrityError
OwnerProfileError = v6.OwnerProfileError
OwnerProfileSnapshot = v6.OwnerProfileSnapshot
OwnerProfileState = v6.OwnerProfileState
OwnerProfileFailure = v6.OwnerProfileFailure
OwnerProfileTransactionError = v6.OwnerProfileTransactionError
StageDiagnostic = v6.StageDiagnostic
genesis_head = v6.genesis_head
normalize_display_name = v6.normalize_display_name

_BASE_FIELDS = frozenset(
    {"version", "owner_profile_id", "runtime_instance", "sequence", "head_mac"}
)
_ENVELOPE_FIELDS = frozenset({"schema", "base", "records"})
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


class HostLeaseError(OwnerProfileError):
    """The required host-wide transaction lease could not be held."""


class HostLeaseConflict(HostLeaseError):
    """The bounded lease wait expired or another session cannot be excluded."""


@runtime_checkable
class HostTransactionLease(Protocol):
    """Host-wide, cross-session, reentrant transaction exclusion contract."""

    @property
    def cross_session_guaranteed(self) -> bool: ...

    def hold(
        self, owner_profile_id: str, *, timeout_seconds: float
    ) -> AbstractContextManager[object]: ...


class _GlobalWindowsMutex(AbstractContextManager["_GlobalWindowsMutex"]):
    """Global Windows mutex; never silently degrades to Local session scope."""

    def __init__(self, owner_profile_id: str, *, timeout_seconds: float) -> None:
        digest = hashlib.sha256(owner_profile_id.encode("ascii")).hexdigest()
        self.name = f"Global\\CyryxLabs.Onyx.OwnerProfileTransaction.{digest}"
        self.timeout_seconds = timeout_seconds
        self._handle: int | None = None

    @staticmethod
    def _kernel32():
        try:
            return ctypes.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError) as exc:
            raise HostLeaseError("Windows global owner lease is unavailable") from exc

    def __enter__(self) -> "_GlobalWindowsMutex":
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
            error = ctypes.get_last_error()
            # A Local\\ fallback would falsely claim exclusion across Windows
            # sessions.  Refuse the operation instead.
            raise HostLeaseError(
                "Windows global owner lease could not be created"
            ) from OSError(error, "global mutex unavailable")
        self._handle = int(handle)
        outcome = int(
            kernel32.WaitForSingleObject(handle, int(self.timeout_seconds * 1000))
        )
        if outcome == 0:
            return self
        self._close()
        if outcome == 0x102:
            raise HostLeaseConflict("Windows global owner lease timed out")
        if outcome == 0x80:
            raise HostLeaseError("Windows global owner lease was abandoned")
        raise HostLeaseError("Windows global owner lease wait failed")

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
                raise HostLeaseError("Windows global owner lease release failed")
        finally:
            self._close()


class WindowsHostTransactionLease:
    """Concrete cross-session Windows lease with bounded, reentrant waits."""

    _process_lock = threading.RLock()

    def __init__(self) -> None:
        if platform.system() != "Windows":
            raise HostLeaseError(
                "Windows global owner lease is unavailable on this host"
            )

    @property
    def cross_session_guaranteed(self) -> bool:
        return True

    @contextmanager
    def hold(
        self, owner_profile_id: str, *, timeout_seconds: float
    ) -> Iterator[object]:
        profile = v6._identifier(owner_profile_id, "owner_profile_id")
        if type(timeout_seconds) not in {int, float} or isinstance(
            timeout_seconds, bool
        ):
            raise TypeError("timeout_seconds must be numeric")
        timeout = float(timeout_seconds)
        if not 0.05 <= timeout <= 30.0:
            raise ValueError("timeout_seconds is outside the bounded range")
        acquired = self._process_lock.acquire(timeout=timeout)
        if not acquired:
            raise HostLeaseConflict("In-process owner transaction lease timed out")
        try:
            with _GlobalWindowsMutex(profile, timeout_seconds=timeout):
                yield self
        finally:
            self._process_lock.release()


class WindowsCredentialChainHeadStore(v6.WindowsCredentialChainHeadStore):
    """V7 Windows CAS adapter serialized across all local Windows sessions."""

    def __init__(
        self,
        *,
        timeout_seconds: float = LEASE_TIMEOUT_SECONDS,
        host_lease: WindowsHostTransactionLease | None = None,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self._v7_timeout_seconds = float(timeout_seconds)
        self._v7_host_lease = host_lease or WindowsHostTransactionLease()

    def compare_and_set(
        self,
        owner_profile_id: str,
        expected: ChainHead | None,
        desired: ChainHead,
    ) -> bool:
        with self._v7_host_lease.hold(
            owner_profile_id, timeout_seconds=self._v7_timeout_seconds
        ):
            return super().compare_and_set(owner_profile_id, expected, desired)


class AuthenticatedJournalBackend:
    """V7 journal with terminal snapshot compaction and exact pair admission."""

    def __init__(
        self,
        path: Path | str,
        *,
        key: bytes,
        owner_profile_id: str,
        runtime_instance: str,
        lease_held: Any,
        max_journal_bytes: int = MAX_JOURNAL_BYTES,
        max_journal_records: int = MAX_JOURNAL_RECORDS,
    ) -> None:
        if type(key) is not bytes or len(key) != 32:
            raise TypeError("journal key must be exact bytes of length 32")
        self.path = Path(path)
        if not self.path.is_absolute():
            raise TypeError("journal path must be absolute")
        self._key = bytes(key)
        self.owner_profile_id = v6._identifier(owner_profile_id, "owner_profile_id")
        self.runtime_instance = v6._identifier(runtime_instance, "runtime_instance")
        if not callable(lease_held):
            raise TypeError("lease_held assertion is required")
        self._lease_held = lease_held
        if (
            type(max_journal_bytes) is not int
            or not 512 <= max_journal_bytes <= MAX_JOURNAL_BYTES
        ):
            raise ValueError("max_journal_bytes is outside the bounded range")
        if (
            type(max_journal_records) is not int
            or not 2 <= max_journal_records <= MAX_JOURNAL_RECORDS
        ):
            raise ValueError("max_journal_records is outside the bounded range")
        self.max_journal_bytes = max_journal_bytes
        self.max_journal_records = max_journal_records

    def _require_lease(self) -> None:
        try:
            held = self._lease_held()
        except Exception as exc:
            raise HostLeaseError("Owner transaction lease assertion failed") from exc
        if held is not True:
            raise HostLeaseError("Owner journal mutation requires the host-wide lease")

    def _base(self, sequence: int, head_mac: str) -> dict[str, Any]:
        return {
            "version": PROFILE_SCHEMA_VERSION,
            "owner_profile_id": self.owner_profile_id,
            "runtime_instance": self.runtime_instance,
            "sequence": sequence,
            "head_mac": head_mac,
        }

    def _mac(self, raw: dict[str, Any]) -> str:
        return hmac.new(
            self._key,
            v6._canonical({field: raw[field] for field in _MAC_FIELDS}),
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
        if info.st_size > self.max_journal_bytes:
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
        if type(value) is not dict or frozenset(value) != _ENVELOPE_FIELDS:
            raise JournalIntegrityError("Owner journal envelope is invalid")
        if value["schema"] != JOURNAL_SCHEMA or type(value["records"]) is not list:
            raise JournalIntegrityError("Owner journal schema is invalid")
        if len(value["records"]) > self.max_journal_records:
            raise JournalIntegrityError("Owner journal record count is invalid")
        base = value["base"]
        if type(base) is not dict or frozenset(base) != _BASE_FIELDS:
            raise JournalIntegrityError("Owner journal base fields are invalid")
        if (
            type(base["version"]) is not int
            or base["version"] != PROFILE_SCHEMA_VERSION
        ):
            raise JournalIntegrityError("Owner journal base version is invalid")
        if base["owner_profile_id"] != self.owner_profile_id:
            raise JournalIntegrityError("Owner journal base profile binding is invalid")
        if base["runtime_instance"] != self.runtime_instance:
            raise JournalIntegrityError("Owner journal base runtime binding is invalid")
        if (
            type(base["sequence"]) is not int
            or not 0 <= base["sequence"] <= MAX_JOURNAL_RECORDS
        ):
            raise JournalIntegrityError("Owner journal base sequence is invalid")
        if type(base["head_mac"]) is not str or not v6._LOWER_HEX_64.fullmatch(
            base["head_mac"]
        ):
            raise JournalIntegrityError("Owner journal base authenticator is invalid")
        if base["sequence"] == 0 and base["head_mac"] != GENESIS_MAC:
            raise JournalIntegrityError("Owner journal base genesis is invalid")
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
        prior = v6._name(raw["prior_name"], nullable=True)
        target = v6._name(raw["target_name"], nullable=True)
        if (raw["operation"] == "set") != (target is not None):
            raise JournalIntegrityError("Owner journal target is invalid")
        if type(raw["nonce"]) is not str or not v6._LOWER_HEX_64.fullmatch(
            raw["nonce"]
        ):
            raise JournalIntegrityError("Owner journal nonce is invalid")
        if type(raw["previous_mac"]) is not str or raw["previous_mac"] != previous_mac:
            raise JournalIntegrityError("Owner journal predecessor is invalid")
        if type(raw["mac"]) is not str or not v6._LOWER_HEX_64.fullmatch(raw["mac"]):
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
                raise JournalIntegrityError(
                    "Owner journal snapshot starts without preparation"
                )
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

    def read_snapshot(self) -> tuple[ChainHead, list[JournalEntry], dict[str, Any]]:
        raw = self._read_raw()
        base = raw["base"]
        base_head = ChainHead(
            v6.CHAIN_HEAD_VERSION,
            self.owner_profile_id,
            base["sequence"],
            base["head_mac"],
        )
        v6._validate_head(base_head, self.owner_profile_id)
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
        return base_head, records, raw

    def read_all(self) -> list[JournalEntry]:
        return self.read_snapshot()[1]

    @staticmethod
    def _encoded_size(payload: dict[str, Any]) -> int:
        return len(v6._canonical(payload)) + 1

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
        self._require_lease()
        encoded = v6._canonical(payload) + b"\n"
        if len(encoded) > self.max_journal_bytes:
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

    def bootstrap_empty(self) -> None:
        self._require_lease()
        if self.path.exists():
            base, records, _raw = self.read_snapshot()
            if records or not v6._same_head(base, genesis_head(self.owner_profile_id)):
                raise JournalIntegrityError("Owner journal is not empty genesis")
            return
        payload = {
            "schema": JOURNAL_SCHEMA,
            "base": self._base(0, GENESIS_MAC),
            "records": [],
        }
        self._atomic_write(payload, expected=None)

    def compact_terminal_history(self, current_anchor: ChainHead) -> bool:
        """Retain only the latest fully terminalized pair; never compact PREPARED."""

        self._require_lease()
        base, records, raw = self.read_snapshot()
        if not records:
            return False
        latest = records[-1]
        if latest.state is JournalState.PREPARED:
            return False
        if not v6._same_head(
            current_anchor, v6._head_for(self.owner_profile_id, latest)
        ):
            raise ChainHeadConflict(
                "Compaction requires the exact anchored terminal record"
            )
        if len(records) <= 2:
            return False
        prepared = records[-2]
        if prepared.state is not JournalState.PREPARED:
            raise JournalIntegrityError("Terminal journal snapshot lacks preparation")
        raw_prepared, raw_terminal = raw["records"][-2:]
        compacted = {
            "schema": JOURNAL_SCHEMA,
            "base": self._base(prepared.sequence - 1, raw_prepared["previous_mac"]),
            "records": [raw_prepared, raw_terminal],
        }
        expected = self._safe_file()
        self._atomic_write(compacted, expected=expected)
        observed_base, observed_records, _ = self.read_snapshot()
        if observed_base.sequence != prepared.sequence - 1 or observed_records != [
            prepared,
            latest,
        ]:
            raise JournalIntegrityError("Owner journal compaction readback failed")
        return True

    def _validate_append(self, entry: JournalEntry) -> None:
        if type(entry) is not JournalEntry:
            raise TypeError("journal entry must be an exact JournalEntry")
        if type(entry.state) is not JournalState:
            raise JournalIntegrityError("Owner journal append state is invalid")
        if type(entry.operation) is not str or entry.operation not in {"set", "forget"}:
            raise JournalIntegrityError("Owner journal append operation is invalid")
        v6._name(entry.prior_name, nullable=True)
        v6._name(entry.target_name, nullable=True)
        if (entry.operation == "set") != (entry.target_name is not None):
            raise JournalIntegrityError("Owner journal append target is invalid")
        if type(entry.sequence) is not int or entry.sequence < 1:
            raise JournalIntegrityError("Owner journal append sequence is invalid")
        if type(entry.nonce) is not str or not v6._LOWER_HEX_64.fullmatch(entry.nonce):
            raise JournalIntegrityError("Owner journal append nonce is invalid")

    def pair_required_bytes(self, prepared: JournalEntry) -> int:
        """Exact worst-case post-terminal canonical envelope size."""

        self._validate_append(prepared)
        if prepared.state is not JournalState.PREPARED:
            raise JournalIntegrityError("Pair admission requires PREPARED state")
        base, records, raw = self.read_snapshot()
        previous_mac = records[-1].mac if records else base.head_mac
        raw_prepared = self._raw_record(prepared, previous_mac)
        prepared_mac = raw_prepared["mac"]
        candidates = []
        for state in (JournalState.COMMITTED, JournalState.COMPENSATED):
            terminal = JournalEntry(
                prepared.sequence + 1,
                state,
                prepared.operation,
                prepared.prior_name,
                prepared.target_name,
                prepared.nonce,
            )
            raw_terminal = self._raw_record(terminal, prepared_mac)
            candidates.append(
                self._encoded_size(
                    {
                        "schema": JOURNAL_SCHEMA,
                        "base": raw["base"],
                        "records": [*raw["records"], raw_prepared, raw_terminal],
                    }
                )
            )
        return max(candidates)

    def append_prepared(
        self, entry: JournalEntry, *, current_anchor: ChainHead
    ) -> JournalEntry:
        self._require_lease()
        self._validate_append(entry)
        if entry.state is not JournalState.PREPARED:
            raise JournalIntegrityError("Pair admission requires PREPARED state")
        base, records, raw = self.read_snapshot()
        if records and records[-1].state is JournalState.PREPARED:
            raise JournalIntegrityError("Owner journal preparation is unresolved")
        next_sequence = (records[-1].sequence if records else base.sequence) + 1
        if entry.sequence != next_sequence:
            raise JournalIntegrityError("Owner journal append sequence is stale")
        if not v6._same_head(
            current_anchor,
            v6._head_for(self.owner_profile_id, records[-1]) if records else base,
        ):
            raise ChainHeadConflict(
                "Pair admission requires the current anchored terminal"
            )

        required = self.pair_required_bytes(entry)
        required_records = len(records) + 2
        if (
            required > self.max_journal_bytes
            or required_records > self.max_journal_records
        ):
            if not self.compact_terminal_history(current_anchor):
                raise JournalIntegrityError(
                    "Owner journal cannot reserve PREPARED and terminal pair"
                )
            base, records, raw = self.read_snapshot()
            required = self.pair_required_bytes(entry)
            required_records = len(records) + 2
        if (
            required > self.max_journal_bytes
            or required_records > self.max_journal_records
        ):
            raise JournalIntegrityError(
                "Owner journal cannot reserve PREPARED and terminal pair"
            )

        expected = self._safe_file()
        previous_mac = records[-1].mac if records else base.head_mac
        raw_prepared = self._raw_record(entry, previous_mac)
        payload = {
            "schema": JOURNAL_SCHEMA,
            "base": raw["base"],
            "records": [*raw["records"], raw_prepared],
        }
        self._atomic_write(payload, expected=expected)
        observed = self.read_snapshot()[1][-1]
        if (
            observed.state is not JournalState.PREPARED
            or observed.sequence != entry.sequence
        ):
            raise JournalIntegrityError("Owner journal preparation readback failed")
        return observed

    def append_terminal(self, entry: JournalEntry) -> JournalEntry:
        self._require_lease()
        self._validate_append(entry)
        if entry.state not in {JournalState.COMMITTED, JournalState.COMPENSATED}:
            raise JournalIntegrityError("Terminal append requires a terminal state")
        base, records, raw = self.read_snapshot()
        if not records or records[-1].state is not JournalState.PREPARED:
            raise JournalIntegrityError("Owner journal decision lacks preparation")
        prepared = records[-1]
        if entry.sequence != prepared.sequence + 1:
            raise JournalIntegrityError("Owner journal terminal sequence is stale")
        if (
            entry.operation,
            entry.prior_name,
            entry.target_name,
            entry.nonce,
        ) != (
            prepared.operation,
            prepared.prior_name,
            prepared.target_name,
            prepared.nonce,
        ):
            raise JournalIntegrityError(
                "Owner journal terminal does not match preparation"
            )
        raw_terminal = self._raw_record(entry, prepared.mac)
        payload = {
            "schema": JOURNAL_SCHEMA,
            "base": raw["base"],
            "records": [*raw["records"], raw_terminal],
        }
        if self._encoded_size(payload) > self.max_journal_bytes:
            raise JournalIntegrityError("Reserved terminal capacity invariant failed")
        if len(payload["records"]) > self.max_journal_records:
            raise JournalIntegrityError("Reserved terminal record invariant failed")
        expected = self._safe_file()
        self._atomic_write(payload, expected=expected)
        observed = self.read_snapshot()[1][-1]
        if observed.state is not entry.state or observed.sequence != entry.sequence:
            raise JournalIntegrityError("Owner journal terminal readback failed")
        return observed


class OwnerProfileAuthority(v6.OwnerProfileAuthority):
    """V7 authority holding one host-wide lease over every authority transition."""

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
        if not isinstance(transaction_lease, HostTransactionLease):
            raise TypeError(
                "transaction_lease must implement the host-wide lease protocol"
            )
        if transaction_lease.cross_session_guaranteed is not True:
            raise TypeError("transaction_lease must guarantee cross-session exclusion")
        if type(lease_timeout_seconds) not in {int, float} or isinstance(
            lease_timeout_seconds, bool
        ):
            raise TypeError("lease_timeout_seconds must be numeric")
        timeout = float(lease_timeout_seconds)
        if not 0.05 <= timeout <= 30.0:
            raise ValueError("lease_timeout_seconds is outside the bounded range")
        super().__init__(
            config_path=config_path,
            memory=memory,
            journal_path=journal_path,
            journal_key=journal_key,
            owner_profile_id=owner_profile_id,
            runtime_instance=runtime_instance,
            chain_head_store=chain_head_store,
        )
        self._transaction_lease = transaction_lease
        self._lease_timeout_seconds = timeout
        self._lease_local = threading.local()
        self._journal = AuthenticatedJournalBackend(
            Path(journal_path).resolve(strict=False),
            key=journal_key,
            owner_profile_id=self._owner_profile_id,
            runtime_instance=runtime_instance,
            lease_held=self._lease_is_held,
            max_journal_bytes=_journal_max_bytes,
            max_journal_records=_journal_max_records,
        )

    def _lease_is_held(self) -> bool:
        return getattr(self._lease_local, "depth", 0) > 0

    @contextmanager
    def _hold_transaction_lease(self) -> Iterator[None]:
        try:
            manager = self._transaction_lease.hold(
                self._owner_profile_id, timeout_seconds=self._lease_timeout_seconds
            )
            manager.__enter__()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise HostLeaseError("Owner host-wide transaction lease failed") from exc
        self._lease_local.depth = getattr(self._lease_local, "depth", 0) + 1
        try:
            yield
        except BaseException as body_error:
            self._lease_local.depth -= 1
            try:
                manager.__exit__(type(body_error), body_error, body_error.__traceback__)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                raise HostLeaseError(
                    "Owner host-wide transaction lease release failed"
                ) from exc
            raise
        else:
            self._lease_local.depth -= 1
            try:
                manager.__exit__(None, None, None)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                raise HostLeaseError(
                    "Owner host-wide transaction lease release failed"
                ) from exc

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
            if not v6._same_head(observed, genesis):
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
            if not v6._same_head(anchor, base):
                raise ChainHeadConflict(
                    "Owner journal snapshot base and chain head diverge"
                )
            return v6._Consistency(anchor, None, base, None)
        latest = records[-1]
        previous = self._terminal_before(records, len(records) - 1)
        baseline = (
            base if previous is None else v6._head_for(self._owner_profile_id, previous)
        )
        if latest.state is JournalState.PREPARED:
            if not v6._same_head(anchor, baseline):
                raise ChainHeadConflict(
                    "Pending owner journal does not extend current chain head"
                )
            return v6._Consistency(anchor, latest, baseline, latest)
        desired = v6._head_for(self._owner_profile_id, latest)
        if v6._same_head(anchor, desired):
            return v6._Consistency(anchor, latest, desired, None)
        if v6._same_head(anchor, baseline):
            self._advance_anchor(baseline, desired)
            return v6._Consistency(desired, latest, desired, None)
        if anchor.sequence > latest.sequence:
            raise ChainHeadConflict("Owner journal is rolled back behind chain head")
        if anchor.sequence < baseline.sequence:
            raise ChainHeadConflict("Owner chain head is stale")
        raise ChainHeadConflict("Owner journal and chain head mismatch")

    def _diagnostic_journal_state(self) -> JournalState | None:
        try:
            records = self._journal.read_all()
        except Exception:
            return None
        return records[-1].state if records else None

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
            return self._journal.append_terminal(decided)
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

    def reconcile(self) -> OwnerProfileSnapshot:
        if self._degraded_latched:
            return self._publish(self._snapshot.display_name, reconciled=False)
        try:
            with self._hold_transaction_lease():
                return super().reconcile()
        except Exception as exc:
            self._latch(
                "reconcile",
                "host-transaction-lease",
                exc,
                journal_state=self._diagnostic_journal_state(),
            )
            return self._publish(self._snapshot.display_name, reconciled=False)

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
            except Exception as exc:
                recovery += (("compensate-journal", self._root_cause(exc)),)
            else:
                try:
                    self._advance_anchor(
                        baseline, v6._head_for(self._owner_profile_id, decided)
                    )
                    decision = JournalState.COMPENSATED
                except Exception as exc:
                    recovery += (("compensate-chain-head", self._root_cause(exc)),)
        actual = self._diagnostic_journal_state()
        self._latch(
            prepared.operation,
            operation_stage,
            root,
            recovery,
            journal_state=actual,
            decision=decision,
            divergence=decision is None,
        )
        self._publish(prepared.prior_name, reconciled=False)
        raise OwnerProfileTransactionError(
            prepared.operation, operation_error, root, recovery, decision
        ) from operation_error

    def _apply_locked(self, operation: str, target: str | None) -> OwnerProfileSnapshot:
        prior, consistency = self._capture_prior()
        latest_sequence = (
            consistency.latest.sequence
            if consistency.latest is not None
            else consistency.baseline.sequence
        )
        prepared = JournalEntry(
            latest_sequence + 1,
            JournalState.PREPARED,
            operation,
            prior,
            target,
            v6.secrets.token_hex(32),
        )
        try:
            prepared = self._journal.append_prepared(
                prepared, current_anchor=consistency.baseline
            )
        except Exception as exc:
            self._latch(
                operation,
                "prepare-journal",
                exc,
                journal_state=self._diagnostic_journal_state(),
            )
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
        except Exception as exc:
            self._latch(
                operation,
                "commit-journal",
                exc,
                journal_state=self._diagnostic_journal_state(),
                divergence=True,
            )
            self._publish(target, reconciled=False)
            raise OwnerProfileTransactionError(
                operation, exc, self._root_cause(exc), (), None
            ) from exc
        try:
            self._advance_anchor(
                consistency.baseline, v6._head_for(self._owner_profile_id, committed)
            )
        except Exception as exc:
            self._latch(
                operation,
                "advance-chain-head",
                exc,
                journal_state=self._diagnostic_journal_state(),
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

    def _apply(self, operation: str, target: str | None) -> OwnerProfileSnapshot:
        try:
            with self._hold_transaction_lease():
                return self._apply_locked(operation, target)
        except (OwnerProfileTransactionError, InvalidDisplayName):
            raise
        except Exception as exc:
            if not self._degraded_latched:
                self._latch(
                    operation,
                    "host-transaction-lease",
                    exc,
                    journal_state=self._diagnostic_journal_state(),
                )
                self._publish(self._snapshot.display_name, reconciled=False)
            raise


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
