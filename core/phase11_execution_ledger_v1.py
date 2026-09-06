"""Trusted, host-keyed execution evidence for Phase 11 dispatches.

The three storage objects are fixed names beneath one descriptor/handle-bound
trusted directory.  A missing receipt is never evidence that execution did not
occur: every unresolved reservation is ``unknown``.

Rollback of both the ledger and its checkpoint remains detectable only when an
external monotonic anchor is available.  This module detects single-object
rollback, tamper, replay, truncation, and crash windows where a fully-authentic
ledger commit is ahead of its checkpoint.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Generator, Literal, Mapping, cast

from core.phase11_executable_sandbox_v1 import (
    verify_executable_sandbox_receipt_v1,
)


SCHEMA = "onyx.phase11.execution_ledger.v1"
KINDS = frozenset({"intent", "dispatch_reserved", "receipt", "unknown"})
ZERO_HASH = "0" * 64
MAX_LEDGER_BYTES = 64 * 1024 * 1024
LEDGER_NAME = "execution-ledger.jsonl"
CHECKPOINT_NAME = "execution-ledger.checkpoint"
LOCK_NAME = "execution-ledger.lock"
_DOMAIN_RECORD = b"ONYX/PHASE11/EXECUTION-LEDGER/RECORD/V1\0"
_DOMAIN_CHECKPOINT = b"ONYX/PHASE11/EXECUTION-LEDGER/CHECKPOINT/V1\0"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MISSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_PATH_GUARDS_LOCK = threading.Lock()
_PATH_GUARDS: dict[str, threading.RLock] = {}


class ExecutionLedgerError(RuntimeError):
    """Fail-closed ledger contract or integrity failure."""


@dataclass(frozen=True)
class ExecutionLedgerRecordV1:
    schema: str
    sequence: int
    prev_hash: str
    kind: Literal["intent", "dispatch_reserved", "receipt", "unknown"]
    mission_id: str
    execution_id: str
    workspace_id: str
    image_digest: str
    argv_digest: str
    attempt: int
    timestamp: int
    receipt_payload: str
    receipt_argv_payload: str
    receipt_digest: str
    verdict: str
    exit_code: int | None
    stdout_digest: str
    stderr_digest: str
    receipt_hmac_sha256: str
    record_hash: str


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _mac(secret: bytes, domain: bytes, value: object) -> str:
    return hmac.new(secret, domain + _canonical(value), hashlib.sha256).hexdigest()


def _guard_for(boundary: object) -> threading.RLock:
    path = getattr(boundary, "path", None)
    name = os.path.normcase(str(path)) if path is not None else f"object:{id(boundary)}"
    with _PATH_GUARDS_LOCK:
        return _PATH_GUARDS.setdefault(name, threading.RLock())


def _busy_exception(exc: BaseException) -> bool:
    lowered = str(exc).casefold()
    return "busy" in lowered or "lock_busy" in lowered or "single_instance_busy" in lowered


class Phase11ExecutionLedgerV1:
    """Authenticate execution transitions within one trusted directory."""

    def __init__(
        self,
        *,
        host_secret: bytes | None = None,
        trusted_directory: object | None = None,
        receipt_signing_key: bytes | None = None,
        receipt_verifier: Callable[..., bool] | None = None,
        enabled: bool = False,
        clock_ns: Callable[[], int] = time.time_ns,
        lock_timeout_seconds: float = 10.0,
        **legacy_storage: object,
    ) -> None:
        self.enabled = enabled is True
        self._secret = host_secret
        self._boundary = trusted_directory
        self._clock_ns = clock_ns
        self._receipt_signing_key = receipt_signing_key
        self._receipt_verifier = verify_executable_sandbox_receipt_v1
        self._lock_timeout_seconds = lock_timeout_seconds
        self._guard = threading.RLock()
        if legacy_storage:
            raise ExecutionLedgerError("execution_ledger_legacy_storage_refused")
        if not self.enabled:
            return
        if not isinstance(host_secret, bytes) or len(host_secret) < 32:
            raise ExecutionLedgerError("execution_ledger_host_secret_invalid")
        if trusted_directory is None or getattr(trusted_directory, "enabled", None) is not True:
            raise ExecutionLedgerError("execution_ledger_trusted_directory_required")
        if not callable(getattr(trusted_directory, "session", None)):
            raise ExecutionLedgerError("execution_ledger_trusted_directory_invalid")
        if (
            not isinstance(receipt_signing_key, bytes)
            or len(receipt_signing_key) < 32
            or receipt_verifier is not verify_executable_sandbox_receipt_v1
        ):
            raise ExecutionLedgerError("execution_ledger_receipt_verifier_required")
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not 0 < float(lock_timeout_seconds) <= 60.0
        ):
            raise ExecutionLedgerError("execution_ledger_lock_timeout_invalid")
        self._guard = _guard_for(trusted_directory)
        with self._locked() as session:
            self._initialize_or_verify(session)

    @contextlib.contextmanager
    def _locked(self) -> Generator[Any, None, None]:
        if not self.enabled:
            raise ExecutionLedgerError("execution_ledger_disabled")
        assert self._boundary is not None
        deadline = time.monotonic() + float(self._lock_timeout_seconds)
        with self._guard:
            while True:
                stack = contextlib.ExitStack()
                try:
                    session = stack.enter_context(self._boundary.session())
                    stack.enter_context(session.lock(LOCK_NAME))
                except BaseException as exc:
                    stack.close()
                    if not _busy_exception(exc) or time.monotonic() >= deadline:
                        raise ExecutionLedgerError("execution_ledger_lock_failed") from exc
                    time.sleep(0.01)
                    continue
                try:
                    with stack:
                        yield session
                    return
                except ExecutionLedgerError:
                    raise
                except BaseException as exc:
                    raise ExecutionLedgerError("execution_ledger_storage_failed") from exc

    def _checkpoint(self, *, sequence: int, tail_hash: str, size: int) -> dict[str, object]:
        unsigned: dict[str, object] = {
            "schema": SCHEMA,
            "sequence": sequence,
            "tail_hash": tail_hash,
            "size": size,
        }
        return {
            **unsigned,
            "checkpoint_hmac": _mac(
                cast(bytes, self._secret), _DOMAIN_CHECKPOINT, unsigned
            ),
        }

    @staticmethod
    def _publish(session: Any, name: str, content: bytes) -> None:
        if session.exists(name, directory=False):
            session.publish_replace(name, content)
        else:
            session.publish_create(name, content)

    def _write_checkpoint(self, session: Any, checkpoint: Mapping[str, object]) -> None:
        self._publish(session, CHECKPOINT_NAME, _canonical(dict(checkpoint)) + b"\n")

    def _read_checkpoint(self, session: Any) -> dict[str, object] | None:
        raw = session.read_optional(CHECKPOINT_NAME, max_bytes=4096)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExecutionLedgerError("execution_ledger_checkpoint_invalid") from exc
        if not isinstance(value, dict) or set(value) != {
            "schema", "sequence", "tail_hash", "size", "checkpoint_hmac"
        }:
            raise ExecutionLedgerError("execution_ledger_checkpoint_invalid")
        signature = value.get("checkpoint_hmac")
        unsigned = {key: value[key] for key in ("schema", "sequence", "tail_hash", "size")}
        expected = _mac(cast(bytes, self._secret), _DOMAIN_CHECKPOINT, unsigned)
        if (
            value.get("schema") != SCHEMA
            or type(value.get("sequence")) is not int
            or cast(int, value["sequence"]) < 0
            or type(value.get("size")) is not int
            or cast(int, value["size"]) < 0
            or not isinstance(value.get("tail_hash"), str)
            or _DIGEST.fullmatch(cast(str, value["tail_hash"])) is None
            or not isinstance(signature, str)
            or not hmac.compare_digest(signature, expected)
        ):
            raise ExecutionLedgerError("execution_ledger_checkpoint_invalid")
        return value

    def _initialize_or_verify(self, session: Any) -> None:
        raw = session.read_optional(LEDGER_NAME, max_bytes=MAX_LEDGER_BYTES)
        if raw is None:
            self._publish(session, LEDGER_NAME, b"")
            raw = b""
        checkpoint = self._read_checkpoint(session)
        if checkpoint is None:
            if raw:
                raise ExecutionLedgerError("execution_ledger_checkpoint_missing")
            self._write_checkpoint(
                session, self._checkpoint(sequence=0, tail_hash=ZERO_HASH, size=0)
            )
        self._read_verified(session, repair_checkpoint=True)

    def _parse_records(
        self, raw: bytes
    ) -> tuple[tuple[ExecutionLedgerRecordV1, ...], tuple[int, ...]]:
        if len(raw) > MAX_LEDGER_BYTES:
            raise ExecutionLedgerError("execution_ledger_size_limit")
        if raw and not raw.endswith(b"\n"):
            raise ExecutionLedgerError("execution_ledger_truncated")
        records: list[ExecutionLedgerRecordV1] = []
        sizes: list[int] = []
        previous = ZERO_HASH
        offset = 0
        for sequence, line in enumerate(raw.splitlines(keepends=True), 1):
            offset += len(line)
            sizes.append(offset)
            try:
                document = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ExecutionLedgerError("execution_ledger_record_invalid") from exc
            if not isinstance(document, dict) or set(document) != set(
                ExecutionLedgerRecordV1.__dataclass_fields__
            ):
                raise ExecutionLedgerError("execution_ledger_record_invalid")
            signature = document.get("record_hash")
            unsigned = {**document, "record_hash": ""}
            expected = _mac(cast(bytes, self._secret), _DOMAIN_RECORD, unsigned)
            if (
                document.get("schema") != SCHEMA
                or document.get("sequence") != sequence
                or document.get("prev_hash") != previous
                or not isinstance(signature, str)
                or not hmac.compare_digest(signature, expected)
            ):
                raise ExecutionLedgerError("execution_ledger_chain_invalid")
            try:
                record = ExecutionLedgerRecordV1(**document)
            except TypeError as exc:
                raise ExecutionLedgerError("execution_ledger_record_invalid") from exc
            self._validate_record(record)
            records.append(record)
            previous = record.record_hash
        self._validate_transitions(records)
        return tuple(records), tuple(sizes)

    def _read_verified(
        self, session: Any, *, repair_checkpoint: bool = True
    ) -> tuple[ExecutionLedgerRecordV1, ...]:
        raw = session.read(LEDGER_NAME, max_bytes=MAX_LEDGER_BYTES)
        records, sizes = self._parse_records(raw)
        checkpoint = self._read_checkpoint(session)
        if checkpoint is None:
            raise ExecutionLedgerError("execution_ledger_checkpoint_missing")
        cp_sequence = cast(int, checkpoint["sequence"])
        cp_size = cast(int, checkpoint["size"])
        cp_tail = cast(str, checkpoint["tail_hash"])
        if cp_sequence > len(records) or cp_size > len(raw):
            raise ExecutionLedgerError("execution_ledger_checkpoint_ahead")
        expected_size = 0 if cp_sequence == 0 else sizes[cp_sequence - 1]
        expected_tail = ZERO_HASH if cp_sequence == 0 else records[cp_sequence - 1].record_hash
        if cp_size != expected_size or cp_tail != expected_tail:
            raise ExecutionLedgerError("execution_ledger_checkpoint_mismatch")
        if cp_sequence < len(records):
            if not repair_checkpoint:
                raise ExecutionLedgerError("execution_ledger_checkpoint_behind")
            self._write_checkpoint(
                session,
                self._checkpoint(
                    sequence=len(records),
                    tail_hash=records[-1].record_hash,
                    size=len(raw),
                ),
            )
        return records

    def _validate_record(self, record: ExecutionLedgerRecordV1) -> None:
        digests = (
            record.execution_id,
            record.workspace_id,
            record.image_digest,
            record.argv_digest,
            record.prev_hash,
            record.record_hash,
        )
        if (
            record.kind not in KINDS
            or type(record.sequence) is not int
            or record.sequence < 1
            or type(record.attempt) is not int
            or record.attempt < 1
            or type(record.timestamp) is not int
            or record.timestamp < 0
            or _MISSION.fullmatch(record.mission_id) is None
            or any(_DIGEST.fullmatch(value) is None for value in digests)
        ):
            raise ExecutionLedgerError("execution_ledger_record_invalid")
        if record.kind == "receipt":
            if (
                not record.receipt_payload
                or not record.receipt_argv_payload
                or _DIGEST.fullmatch(record.receipt_digest) is None
                or hashlib.sha256(record.receipt_payload.encode("ascii")).hexdigest()
                != record.receipt_digest
                or record.verdict not in {"PASS", "FAIL", "CANCELLED", "TIMEOUT", "OUTPUT_LIMIT"}
                or (record.exit_code is not None and type(record.exit_code) is not int)
                or _DIGEST.fullmatch(record.stdout_digest) is None
                or _DIGEST.fullmatch(record.stderr_digest) is None
                or _DIGEST.fullmatch(record.receipt_hmac_sha256) is None
            ):
                raise ExecutionLedgerError("execution_ledger_receipt_invalid")
            try:
                document = json.loads(record.receipt_payload)
                argv_document = json.loads(record.receipt_argv_payload)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ExecutionLedgerError("execution_ledger_receipt_invalid") from exc
            argv = (
                tuple(argv_document)
                if isinstance(argv_document, list)
                and argv_document
                and all(isinstance(argument, str) for argument in argv_document)
                else ()
            )
            verifier = self._receipt_verifier
            if (
                not isinstance(document, dict)
                or _canonical(document).decode("ascii") != record.receipt_payload
                or not argv
                or _canonical(argv).decode("ascii") != record.receipt_argv_payload
                or hashlib.sha256(_canonical(argv)).hexdigest() != record.argv_digest
                or document.get("execution_id") != record.execution_id
                or document.get("attempt") != record.attempt
                or document.get("image_sha256") != record.image_digest
                or document.get("verdict") != record.verdict
                or document.get("exit_code") != record.exit_code
                or document.get("stdout_hmac_sha256") != record.stdout_digest
                or document.get("stderr_hmac_sha256") != record.stderr_digest
                or document.get("receipt_hmac_sha256") != record.receipt_hmac_sha256
                or not callable(verifier)
                or verifier(
                    document,
                    signing_key=self._receipt_signing_key,
                    mission_id=record.mission_id,
                    execution_id=record.execution_id,
                    image_id=f"sha256:{record.image_digest}",
                    argv=argv,
                    attempt=record.attempt,
                )
                is not True
            ):
                raise ExecutionLedgerError("execution_ledger_receipt_binding_invalid")
        elif any(
            value not in {"", None}
            for value in (
                record.receipt_payload,
                record.receipt_argv_payload,
                record.receipt_digest,
                record.verdict,
                record.exit_code,
                record.stdout_digest,
                record.stderr_digest,
                record.receipt_hmac_sha256,
            )
        ):
            raise ExecutionLedgerError("execution_ledger_unexpected_receipt")

    @staticmethod
    def _validate_transitions(
        records: list[ExecutionLedgerRecordV1]
        | tuple[ExecutionLedgerRecordV1, ...],
    ) -> None:
        states: dict[tuple[str, str, int], str] = {}
        execution_bindings: dict[str, tuple[str, str, str, str]] = {}
        attempts: dict[str, set[int]] = {}
        allowed = {
            None: {"intent"},
            "intent": {"dispatch_reserved"},
            "dispatch_reserved": {"receipt", "unknown"},
            "receipt": set(),
            "unknown": set(),
        }
        for record in records:
            binding = (
                record.mission_id,
                record.workspace_id,
                record.image_digest,
                record.argv_digest,
            )
            prior_binding = execution_bindings.setdefault(record.execution_id, binding)
            if prior_binding != binding:
                raise ExecutionLedgerError("execution_ledger_global_execution_replay")
            seen_attempts = attempts.setdefault(record.execution_id, set())
            key = (record.mission_id, record.execution_id, record.attempt)
            prior = states.get(key)
            if prior is None and record.kind == "intent":
                if record.attempt != 1:
                    # No authenticated takeover/reapproval API exists in V1.
                    raise ExecutionLedgerError("execution_ledger_retry_takeover_required")
                seen_attempts.add(record.attempt)
            if record.kind not in allowed[prior]:
                raise ExecutionLedgerError("execution_ledger_replay_or_binding_invalid")
            states[key] = record.kind

    def read(
        self,
        *,
        mission_id: str | None = None,
        execution_id: str | None = None,
        workspace_id: str | None = None,
        image_digest: str | None = None,
        argv_digest: str | None = None,
    ) -> tuple[ExecutionLedgerRecordV1, ...]:
        if not self.enabled:
            return ()
        with self._locked() as session:
            records = self._read_verified(session)
        expected = {
            "mission_id": mission_id,
            "execution_id": execution_id,
            "workspace_id": workspace_id,
            "image_digest": image_digest,
            "argv_digest": argv_digest,
        }
        for name, value in expected.items():
            if value is not None and any(getattr(record, name) != value for record in records):
                raise ExecutionLedgerError("execution_ledger_binding_mismatch")
        return records

    def append(
        self,
        kind: Literal["intent", "dispatch_reserved", "receipt", "unknown"],
        *,
        mission_id: str,
        execution_id: str,
        workspace_id: str,
        image_digest: str,
        argv_digest: str,
        attempt: int,
        timestamp: int | None = None,
        receipt: Mapping[str, object] | None = None,
        image_id: str | None = None,
        argv: tuple[str, ...] | None = None,
    ) -> ExecutionLedgerRecordV1 | None:
        if not self.enabled:
            return None
        receipt_values: dict[str, object] = {
            "receipt_payload": "",
            "receipt_argv_payload": "",
            "receipt_digest": "",
            "verdict": "",
            "exit_code": None,
            "stdout_digest": "",
            "stderr_digest": "",
            "receipt_hmac_sha256": "",
        }
        if kind == "receipt":
            if (
                not isinstance(receipt, Mapping)
                or not isinstance(image_id, str)
                or not isinstance(argv, tuple)
            ):
                raise ExecutionLedgerError("execution_ledger_receipt_unverified")
            document = dict(receipt)
            verifier = self._receipt_verifier
            assert callable(verifier)
            if (
                image_id != f"sha256:{image_digest}"
                or hashlib.sha256(_canonical(argv)).hexdigest() != argv_digest
                or verifier(
                    document,
                    signing_key=self._receipt_signing_key,
                    mission_id=mission_id,
                    execution_id=execution_id,
                    image_id=image_id,
                    argv=argv,
                    attempt=attempt,
                )
                is not True
            ):
                raise ExecutionLedgerError("execution_ledger_receipt_unverified")
            payload = _canonical(document).decode("ascii")
            receipt_values = {
                "receipt_payload": payload,
                "receipt_argv_payload": _canonical(argv).decode("ascii"),
                "receipt_digest": hashlib.sha256(payload.encode("ascii")).hexdigest(),
                "verdict": document.get("verdict"),
                "exit_code": document.get("exit_code"),
                "stdout_digest": document.get("stdout_hmac_sha256"),
                "stderr_digest": document.get("stderr_hmac_sha256"),
                "receipt_hmac_sha256": document.get("receipt_hmac_sha256"),
            }
        elif receipt is not None or image_id is not None or argv is not None:
            raise ExecutionLedgerError("execution_ledger_unexpected_receipt")
        with self._locked() as session:
            records = self._read_verified(session)
            unsigned: dict[str, object] = {
                "schema": SCHEMA,
                "sequence": len(records) + 1,
                "prev_hash": records[-1].record_hash if records else ZERO_HASH,
                "kind": kind,
                "mission_id": mission_id,
                "execution_id": execution_id,
                "workspace_id": workspace_id,
                "image_digest": image_digest,
                "argv_digest": argv_digest,
                "attempt": attempt,
                "timestamp": self._clock_ns() if timestamp is None else timestamp,
                **receipt_values,
                "record_hash": "",
            }
            signature = _mac(cast(bytes, self._secret), _DOMAIN_RECORD, unsigned)
            record = ExecutionLedgerRecordV1(
                **{**unsigned, "record_hash": signature}  # type: ignore[arg-type]
            )
            self._validate_record(record)
            self._validate_transitions((*records, record))
            encoded = _canonical(asdict(record)) + b"\n"
            prior = session.read(LEDGER_NAME, max_bytes=MAX_LEDGER_BYTES)
            if len(prior) + len(encoded) > MAX_LEDGER_BYTES:
                raise ExecutionLedgerError("execution_ledger_size_limit")
            content = prior + encoded
            session.publish_replace(LEDGER_NAME, content)
            self._write_checkpoint(
                session,
                self._checkpoint(
                    sequence=record.sequence,
                    tail_hash=record.record_hash,
                    size=len(content),
                ),
            )
            return record

    def authenticated_receipt(
        self, *, mission_id: str, execution_id: str, attempt: int
    ) -> dict[str, object] | None:
        """Return only a chain-authenticated, exactly-bound receipt payload."""

        records = self.read()
        matches = [
            record
            for record in records
            if record.mission_id == mission_id
            and record.execution_id == execution_id
            and record.attempt == attempt
            and record.kind == "receipt"
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise ExecutionLedgerError("execution_ledger_receipt_replay")
        value = json.loads(matches[0].receipt_payload)
        if not isinstance(value, dict):  # already validated; defensive fence.
            raise ExecutionLedgerError("execution_ledger_receipt_invalid")
        return value

    def execution_state(self, *, mission_id: str, execution_id: str, attempt: int) -> str | None:
        records = self.read()
        latest = next(
            (
                record
                for record in reversed(records)
                if record.mission_id == mission_id
                and record.execution_id == execution_id
                and record.attempt == attempt
            ),
            None,
        )
        if latest is None:
            return None
        if latest.kind == "dispatch_reserved":
            return "unknown"
        return latest.kind


__all__ = [
    "CHECKPOINT_NAME",
    "ExecutionLedgerError",
    "ExecutionLedgerRecordV1",
    "LEDGER_NAME",
    "LOCK_NAME",
    "MAX_LEDGER_BYTES",
    "Phase11ExecutionLedgerV1",
    "SCHEMA",
]
