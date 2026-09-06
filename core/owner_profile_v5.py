"""Owner Profile V5: host-owned authenticated decision journal.

This candidate is isolated and default-off.  Owner configuration and semantic
preference memory remain bilateral projections of the chosen display name.
Transaction authority lives only in a dedicated authenticated journal file;
semantic memory is never trusted as a journal or as a transaction decision.

The caller must supply an exact 32-byte key obtained by the host through an
approved secret channel.  The repository's native vault currently exposes no
sanctioned owner-profile namespace, so this module deliberately does not mint
one or fall back to environment variables, config, or semantic memory.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import core.owner_profile_v1 as v1
import core.owner_profile_v2 as v2


PROFILE_SCHEMA_VERSION = 5
JOURNAL_SCHEMA = "onyx.owner-profile-journal.v5"
MAX_JOURNAL_RECORDS = 4096
JOURNAL_FILENAME = "owner-profile-v5.journal.json"
RESERVED_MEMORY_JOURNAL_KEYS = frozenset(
    {"owner_profile_v3_recovery", "owner_profile_v4_journal", "owner_profile_v5_journal"}
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
_ENVELOPE_FIELDS = frozenset({"schema", "records"})


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
        suffix = f"; decision={decision.value}" if decision is not None else "; decision pending"
        super().__init__(f"Owner profile {operation} failed{suffix}")


class JournalIntegrityError(OwnerProfileError):
    """Safe fail-closed error for malformed or unauthenticated journal state."""


def _validate_identifier(value: object, label: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise TypeError(f"{label} must be a bounded host identifier")
    return value


def _validate_name(value: object, *, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str:
        raise JournalIntegrityError("Owner journal contains an invalid display name")
    try:
        normalized = normalize_display_name(value)
    except InvalidDisplayName as exc:
        raise JournalIntegrityError("Owner journal contains an invalid display name") from exc
    if normalized is None or normalized != value:
        raise JournalIntegrityError("Owner journal contains a non-canonical display name")
    return normalized


class AuthenticatedJournalBackend:
    """Dedicated host-owned append-only journal snapshot.

    Each atomic snapshot contains the complete bounded authenticated chain.
    A valid record is bound to the schema version, owner/profile identity,
    runtime instance, monotonic sequence, operation, prior and target values,
    decision state, nonce, and predecessor MAC.  A process-local high-water mark
    also rejects file rollback observed during the same runtime.

    Atomic replacement guarantees that readers observe an old or new stable
    snapshot on supported local filesystems.  It cannot prove disk flush after
    sudden power loss on every filesystem, and a key alone cannot detect replay
    of an entire older valid snapshot after a process restart.  Those cases fail
    closed when malformed or internally stale, but full cross-restart rollback
    resistance requires a separate sanctioned monotonic host anchor.
    """

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
        self._path = Path(path)
        if not self._path.is_absolute():
            raise TypeError("journal path must be absolute")
        self._key = bytes(key)
        self._owner_profile_id = _validate_identifier(owner_profile_id, "owner_profile_id")
        self._runtime_instance = _validate_identifier(runtime_instance, "runtime_instance")
        self._high_water_sequence = 0
        self._high_water_digest: str | None = None

    @property
    def path(self) -> Path:
        return self._path

    def _canonical(self, record: dict[str, Any]) -> bytes:
        payload = {field: record[field] for field in _MAC_FIELDS}
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")

    def _mac(self, record: dict[str, Any]) -> str:
        return hmac.new(self._key, self._canonical(record), hashlib.sha256).hexdigest()

    @staticmethod
    def _safe_file(path: Path) -> os.stat_result:
        try:
            info = path.lstat()
        except OSError as exc:
            raise JournalIntegrityError("Owner journal path is unavailable") from exc
        attributes = getattr(info, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if path.is_symlink() or attributes & reparse or not stat.S_ISREG(info.st_mode):
            raise JournalIntegrityError("Owner journal must be a regular non-link file")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
            raise JournalIntegrityError("Owner journal permissions are not private")
        return info

    @staticmethod
    def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size)

    def _read_raw(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        before = self._safe_file(self._path)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self._path, flags)
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                opened = os.fstat(handle.fileno())
                if self._identity(opened) != self._identity(before):
                    raise JournalIntegrityError("Owner journal changed while opening")
                data = json.load(handle)
        except JournalIntegrityError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JournalIntegrityError("Owner journal is unreadable") from exc
        if type(data) is not dict or frozenset(data) != _ENVELOPE_FIELDS:
            raise JournalIntegrityError("Owner journal envelope is invalid")
        if data.get("schema") != JOURNAL_SCHEMA or type(data.get("records")) is not list:
            raise JournalIntegrityError("Owner journal schema is invalid")
        return data

    def _validate_record(
        self,
        raw: object,
        *,
        expected_sequence: int,
        previous_mac: str,
        previous: JournalEntry | None,
    ) -> JournalEntry:
        if type(raw) is not dict or frozenset(raw) != _RECORD_FIELDS:
            raise JournalIntegrityError("Owner journal record fields are invalid")
        if type(raw["version"]) is not int or raw["version"] != PROFILE_SCHEMA_VERSION:
            raise JournalIntegrityError("Owner journal version is invalid")
        if raw["owner_profile_id"] != self._owner_profile_id:
            raise JournalIntegrityError("Owner journal profile binding is invalid")
        if raw["runtime_instance"] != self._runtime_instance:
            raise JournalIntegrityError("Owner journal runtime binding is invalid")
        if type(raw["sequence"]) is not int or raw["sequence"] != expected_sequence:
            raise JournalIntegrityError("Owner journal sequence is invalid")
        if raw["operation"] not in {"set", "forget"} or type(raw["operation"]) is not str:
            raise JournalIntegrityError("Owner journal operation is invalid")
        if type(raw["decision_state"]) is not str:
            raise JournalIntegrityError("Owner journal state is invalid")
        try:
            state = JournalState(raw["decision_state"])
        except ValueError as exc:
            raise JournalIntegrityError("Owner journal state is invalid") from exc
        prior = _validate_name(raw["prior_name"], nullable=True)
        target = _validate_name(raw["target_name"], nullable=True)
        if (raw["operation"] == "set") != (target is not None):
            raise JournalIntegrityError("Owner journal target is invalid")
        if type(raw["nonce"]) is not str or not _LOWER_HEX_64.fullmatch(raw["nonce"]):
            raise JournalIntegrityError("Owner journal nonce is invalid")
        if type(raw["previous_mac"]) is not str or raw["previous_mac"] != previous_mac:
            raise JournalIntegrityError("Owner journal predecessor is invalid")
        if type(raw["mac"]) is not str or not _LOWER_HEX_64.fullmatch(raw["mac"]):
            raise JournalIntegrityError("Owner journal authenticator is invalid")
        expected_mac = self._mac(raw)
        if not hmac.compare_digest(expected_mac, raw["mac"]):
            raise JournalIntegrityError("Owner journal authentication failed")

        entry = JournalEntry(
            sequence=raw["sequence"],
            state=state,
            operation=raw["operation"],
            prior_name=prior,
            target_name=target,
            nonce=raw["nonce"],
            mac=raw["mac"],
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
        data = self._read_raw()
        if data is None:
            if self._high_water_sequence:
                raise JournalIntegrityError("Owner journal disappeared during this runtime")
            return []
        records = data["records"]
        if not records or len(records) > MAX_JOURNAL_RECORDS:
            raise JournalIntegrityError("Owner journal record count is invalid")
        validated: list[JournalEntry] = []
        previous_mac = "0" * 64
        for index, raw in enumerate(records, start=1):
            entry = self._validate_record(
                raw,
                expected_sequence=index,
                previous_mac=previous_mac,
                previous=validated[-1] if validated else None,
            )
            validated.append(entry)
            previous_mac = entry.mac
        latest = validated[-1]
        digest = hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if latest.sequence < self._high_water_sequence:
            raise JournalIntegrityError("Owner journal replay was detected")
        if latest.sequence == self._high_water_sequence and self._high_water_digest not in {None, digest}:
            raise JournalIntegrityError("Owner journal snapshot changed at a stable sequence")
        self._high_water_sequence = latest.sequence
        self._high_water_digest = digest
        return validated

    def read_latest(self) -> JournalEntry | None:
        records = self.read_all()
        return records[-1] if records else None

    def _record(self, entry: JournalEntry, previous_mac: str) -> dict[str, Any]:
        record: dict[str, Any] = {
            "version": PROFILE_SCHEMA_VERSION,
            "owner_profile_id": self._owner_profile_id,
            "runtime_instance": self._runtime_instance,
            "sequence": entry.sequence,
            "operation": entry.operation,
            "prior_name": entry.prior_name,
            "target_name": entry.target_name,
            "decision_state": entry.state.value,
            "nonce": entry.nonce,
            "previous_mac": previous_mac,
        }
        record["mac"] = self._mac(record)
        return record

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if parent.is_symlink() or not parent.is_dir():
            raise JournalIntegrityError("Owner journal directory is invalid")
        expected = self._safe_file(self._path) if self._path.exists() else None
        fd, temporary = tempfile.mkstemp(prefix=f".{self._path.name}.", suffix=".tmp", dir=parent)
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if expected is not None:
                current = self._safe_file(self._path)
                if self._identity(current) != self._identity(expected):
                    raise JournalIntegrityError("Owner journal changed during update")
            os.replace(temporary, self._path)
            if os.name != "nt":
                os.chmod(self._path, 0o600)
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
        prior = _validate_name(entry.prior_name, nullable=True)
        target = _validate_name(entry.target_name, nullable=True)
        if prior != entry.prior_name or target != entry.target_name:
            raise JournalIntegrityError("Owner journal append names are invalid")
        if (entry.operation == "set") != (entry.target_name is not None):
            raise JournalIntegrityError("Owner journal append target is invalid")
        records = self.read_all()
        latest = records[-1] if records else None
        expected_sequence = len(records) + 1
        if entry.sequence != expected_sequence or type(entry.sequence) is not int:
            raise JournalIntegrityError("Owner journal append sequence is stale")
        if type(entry.nonce) is not str or not _LOWER_HEX_64.fullmatch(entry.nonce):
            raise JournalIntegrityError("Owner journal append nonce is invalid")
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
                raise JournalIntegrityError("Owner journal decision does not match preparation")
        if len(records) >= MAX_JOURNAL_RECORDS:
            raise JournalIntegrityError("Owner journal capacity is exhausted")
        previous_mac = latest.mac if latest is not None else "0" * 64
        raw = self._record(entry, previous_mac)
        raw_entry = JournalEntry(
            entry.sequence,
            entry.state,
            entry.operation,
            entry.prior_name,
            entry.target_name,
            entry.nonce,
            raw["mac"],
        )
        payload = {"schema": JOURNAL_SCHEMA, "records": [
            *([self._record_from_entry(item, "0" * 64 if index == 0 else records[index - 1].mac) for index, item in enumerate(records)]),
            raw,
        ]}
        self._atomic_write(payload)
        observed = self.read_latest()
        if observed != raw_entry:
            raise JournalIntegrityError("Owner journal append readback failed")
        return observed

    def _record_from_entry(self, entry: JournalEntry, previous_mac: str) -> dict[str, Any]:
        record = {
            "version": PROFILE_SCHEMA_VERSION,
            "owner_profile_id": self._owner_profile_id,
            "runtime_instance": self._runtime_instance,
            "sequence": entry.sequence,
            "operation": entry.operation,
            "prior_name": entry.prior_name,
            "target_name": entry.target_name,
            "decision_state": entry.state.value,
            "nonce": entry.nonce,
            "previous_mac": previous_mac,
            "mac": entry.mac,
        }
        return record


class OwnerProfileAuthority(v2.OwnerProfileAuthority):
    """V5 authority with authenticated host journal and semantic projection."""

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        memory: v1.PreferenceMemory,
        journal_path: Path | str,
        journal_key: bytes,
        owner_profile_id: str,
        runtime_instance: str,
    ) -> None:
        super().__init__(config_path=config_path, memory=memory)
        resolved_journal = Path(journal_path).resolve(strict=False)
        if resolved_journal == self._config_path.resolve(strict=False):
            raise TypeError("journal path must be separate from owner settings")
        memory_path = getattr(memory, "path", None)
        if memory_path is None:
            memory_path = getattr(getattr(memory, "delegate", None), "path", None)
        if memory_path is not None and resolved_journal == Path(memory_path).resolve(strict=False):
            raise TypeError("journal path must be separate from semantic memory")
        self._journal = AuthenticatedJournalBackend(
            resolved_journal,
            key=journal_key,
            owner_profile_id=owner_profile_id,
            runtime_instance=runtime_instance,
        )
        self._last_failure: OwnerProfileFailure | None = None
        self._last_cleanup_failure: StageDiagnostic | None = None

    @classmethod
    def from_existing_stores(
        cls,
        *,
        journal_key: bytes,
        owner_profile_id: str,
        runtime_instance: str,
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
            operation=operation,
            stage=stage,
            original_error_type=self._error_type(root),
            recovery=tuple(
                StageDiagnostic(item_stage, self._error_type(self._root_cause(item_error)))
                for item_stage, item_error in recovery
            ),
            journal_state=journal_state.value if journal_state is not None else None,
            decision=decision.value if decision is not None else None,
            divergence_possible=divergence,
        )

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
            raise JournalIntegrityError("A journal-like semantic memory record was rejected")
        owner_records = [
            record
            for record in records
            if record.category == v1.OWNER_MEMORY_CATEGORY
            and record.key == v1.OWNER_MEMORY_KEY
        ]
        if not owner_records:
            return None
        try:
            return normalize_display_name(owner_records[0].content)
        except InvalidDisplayName:
            return None

    def _reject_semantic_journal(self) -> None:
        self._semantic_state()

    def _read_journal(self) -> JournalEntry | None:
        return self._journal.read_latest()

    def _persist_state(
        self, entry: JournalEntry, state: JournalState
    ) -> tuple[JournalEntry | None, Exception | None]:
        latest = self._read_journal()
        if state is JournalState.PREPARED:
            decided = JournalEntry(
                entry.sequence,
                state,
                entry.operation,
                entry.prior_name,
                entry.target_name,
                entry.nonce,
            )
        else:
            if latest is None or latest.state is not JournalState.PREPARED:
                return latest, JournalIntegrityError("Owner journal has no prepared transaction")
            decided = JournalEntry(
                latest.sequence + 1,
                state,
                latest.operation,
                latest.prior_name,
                latest.target_name,
                latest.nonce,
            )
        write_error: Exception | None = None
        try:
            written = self._journal.append(decided)
        except Exception as exc:
            write_error = exc
            written = None
        try:
            observed = self._read_journal()
        except Exception as exc:
            return None, write_error or exc
        if written is not None and observed == written:
            return observed, write_error
        if observed is not None and (
            observed.state,
            observed.operation,
            observed.prior_name,
            observed.target_name,
            observed.nonce,
        ) == (
            decided.state,
            decided.operation,
            decided.prior_name,
            decided.target_name,
            decided.nonce,
        ):
            return observed, write_error
        return observed, write_error or OwnerProfileError("Owner journal decision mismatch")

    def _gc_journal(self) -> None:
        """Cleanup is diagnostic-only: authenticated decisions remain durable."""

        self._last_cleanup_failure = None

    def _write_owner_value(self, value: str | None) -> list[tuple[str, Exception]]:
        failures: list[tuple[str, Exception]] = []
        try:
            self._write_config(value or "")
        except Exception as exc:
            failures.append(("write-config", self._root_cause(exc)))
        try:
            if value is None:
                self._clear_memory()
            else:
                self._write_memory(value)
        except Exception as exc:
            failures.append(("write-memory", self._root_cause(exc)))
        return failures

    def _verify_owner_value(
        self, value: str | None
    ) -> tuple[bool, list[tuple[str, Exception]]]:
        failures: list[tuple[str, Exception]] = []
        config_ok = False
        memory_ok = False
        try:
            data, _raw = self._read_config()
            try:
                config_ok = normalize_display_name(data.get(v1.OWNER_CONFIG_KEY)) == value
            except InvalidDisplayName:
                config_ok = value is None
        except Exception as exc:
            failures.append(("readback-config", self._root_cause(exc)))
        try:
            memory_ok = self._memory_name() == value
        except Exception as exc:
            failures.append(("readback-memory", self._root_cause(exc)))
        if not config_ok and not any(stage == "readback-config" for stage, _ in failures):
            failures.append(("readback-config", OwnerProfileError("Owner config mismatch")))
        if not memory_ok and not any(stage == "readback-memory" for stage, _ in failures):
            failures.append(("readback-memory", OwnerProfileError("Owner memory mismatch")))
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

    def _resolve_journal(
        self, entry: JournalEntry
    ) -> tuple[bool, str | None, tuple[tuple[str, Exception], ...]]:
        if entry.state is JournalState.COMMITTED:
            desired = entry.target_name
            prefix = "commit"
        else:
            desired = entry.prior_name
            prefix = "compensate"
        # Terminal decisions are retained durably, so routine reconciliation
        # must not rewrite already-correct config and memory on every call.
        if entry.state is not JournalState.PREPARED:
            verified, observed_failures = self._verify_owner_value(desired)
            if verified:
                self._gc_journal()
                return True, desired, ()
            recovery: tuple[tuple[str, Exception], ...] = tuple(
                (f"{prefix}-{stage}", error) for stage, error in observed_failures
            )
        else:
            recovery = ()
        verified, driven = self._drive_value(desired, prefix=prefix)
        recovery += driven
        if not verified:
            return False, desired, recovery
        if entry.state is JournalState.PREPARED:
            decided, decision_error = self._persist_state(entry, JournalState.COMPENSATED)
            if decided is None or decided.state is not JournalState.COMPENSATED:
                if decision_error is not None:
                    recovery += (("decision-compensated", self._root_cause(decision_error)),)
                return False, desired, recovery
        self._gc_journal()
        return True, desired, recovery

    def reconcile(self) -> OwnerProfileSnapshot:
        with v1._PROCESS_LOCK:
            chosen = self._snapshot.display_name
            recovery: tuple[tuple[str, Exception], ...] = ()
            stage = "reject-memory-journal"
            try:
                memory_name = self._semantic_state()
                stage = "read-journal"
                journal = self._read_journal()
                if journal is not None:
                    stage = f"resolve-{journal.state.value.lower()}"
                    chosen = (
                        journal.target_name
                        if journal.state is JournalState.COMMITTED
                        else journal.prior_name
                    )
                    if journal.state is not JournalState.PREPARED:
                        data, _raw = self._read_config()
                        try:
                            config_name = normalize_display_name(data.get(v1.OWNER_CONFIG_KEY))
                        except InvalidDisplayName:
                            config_name = None
                        if config_name == chosen and memory_name == chosen:
                            self._degraded_latched = False
                            self._last_failure = None
                            return self._publish(chosen, reconciled=True)
                    resolved, chosen, recovery = self._resolve_journal(journal)
                    if not resolved:
                        error = OwnerProfileError("Owner journal recovery is incomplete")
                        self._latch(
                            "reconcile", stage, error, recovery, journal_state=journal.state
                        )
                        return self._publish(chosen, reconciled=False)
                    self._degraded_latched = False
                    self._last_failure = None
                    return self._publish(chosen, reconciled=True)
                stage = "read-config"
                data, raw = self._read_config()
                try:
                    config_name = normalize_display_name(data.get(v1.OWNER_CONFIG_KEY))
                except InvalidDisplayName:
                    config_name = None
                chosen = config_name or memory_name
                if config_name != chosen or memory_name != chosen:
                    stage = "repair-without-journal"
                    verified, recovery = self._drive_value(chosen, prefix="repair")
                    if not verified:
                        raise OwnerProfileError("Owner reconciliation repair failed")
                elif chosen is None and raw is not v1._MISSING and raw != "":
                    stage = "sanitize-placeholder"
                    verified, recovery = self._drive_value(None, prefix="repair")
                    if not verified:
                        raise OwnerProfileError("Owner placeholder repair failed")
            except Exception as exc:
                self._latch("reconcile", stage, exc, tuple(recovery))
                return self._publish(chosen, reconciled=False)
            self._degraded_latched = False
            self._last_failure = None
            return self._publish(chosen, reconciled=True)

    def _capture_prior(self) -> str | None:
        snapshot = self.reconcile()
        if snapshot.state is OwnerProfileState.DEGRADED:
            raise OwnerProfileError("Owner profile requires reconciliation")
        verified, failures = self._verify_owner_value(snapshot.display_name)
        if not verified:
            error = OwnerProfileError("Owner prior-state verification failed")
            self._latch("prepare", "verify-prior", error, tuple(failures))
            self._publish(snapshot.display_name, reconciled=False)
            raise error
        return snapshot.display_name

    def _abort_precommit(
        self,
        entry: JournalEntry,
        operation_error: Exception,
        operation_stage: str,
    ) -> None:
        root = self._root_cause(operation_error)
        verified, recovery = self._drive_value(entry.prior_name, prefix="compensate")
        decision: JournalState | None = None
        if verified:
            decided, decision_error = self._persist_state(entry, JournalState.COMPENSATED)
            if decided is not None and decided.state is JournalState.COMPENSATED:
                decision = JournalState.COMPENSATED
                self._gc_journal()
            elif decision_error is not None:
                recovery += (("decision-compensated", self._root_cause(decision_error)),)
        self._latch(
            entry.operation,
            operation_stage,
            root,
            recovery,
            journal_state=JournalState.PREPARED,
            decision=decision,
            divergence=decision is None,
        )
        self._publish(entry.prior_name, reconciled=False)
        raise OwnerProfileTransactionError(
            entry.operation, operation_error, root, recovery, decision
        ) from operation_error

    def _apply(self, operation: str, target: str | None) -> OwnerProfileSnapshot:
        with v1._PROCESS_LOCK:
            prior = self._capture_prior()
            latest = self._read_journal()
            if latest is not None and latest.state is JournalState.PREPARED:
                error = JournalIntegrityError("Owner journal already has a pending transaction")
                self._latch(operation, "prepare-journal", error, journal_state=latest.state)
                raise error
            entry = JournalEntry(
                sequence=(latest.sequence + 1 if latest else 1),
                state=JournalState.PREPARED,
                operation=operation,
                prior_name=prior,
                target_name=target,
                nonce=secrets.token_hex(32),
            )
            stage = "prepare-journal"
            try:
                prepared, prepare_error = self._persist_state(entry, JournalState.PREPARED)
                if prepared is None or prepared.state is not JournalState.PREPARED:
                    raise prepare_error or OwnerProfileError("Owner journal preparation failed")
                entry = prepared
            except Exception as exc:
                self._latch(operation, stage, exc)
                self._publish(prior, reconciled=False)
                raise
            failures = self._write_owner_value(target)
            if failures:
                self._abort_precommit(entry, failures[0][1], failures[0][0])
            verified, failures = self._verify_owner_value(target)
            if not verified:
                error = failures[0][1] if failures else OwnerProfileError("Target verification failed")
                self._abort_precommit(entry, error, failures[0][0] if failures else "verify-target")
            committed, decision_error = self._persist_state(entry, JournalState.COMMITTED)
            if committed is None:
                error = decision_error or OwnerProfileError("Commit decision is unreadable")
                self._latch(operation, "decision-committed", error, divergence=True)
                self._publish(target, reconciled=False)
                raise OwnerProfileTransactionError(operation, error, self._root_cause(error), (), None) from error
            if committed.state is not JournalState.COMMITTED:
                self._abort_precommit(
                    entry,
                    decision_error or OwnerProfileError("Commit decision was not durable"),
                    "decision-committed",
                )
            self._degraded_latched = False
            self._last_failure = None
            self._gc_journal()
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
    "normalize_display_name",
]
