"""Owner Profile V4: durable decision journal over frozen V1-V3."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Any

import core.owner_profile_v1 as v1
import core.owner_profile_v2 as v2


PROFILE_SCHEMA_VERSION = 4
JOURNAL_MEMORY_KEY = "owner_profile_v4_journal"
JOURNAL_SOURCE = "owner-profile-v4"
JOURNAL_CITATION = "system:preferences/owner_profile_v4_journal"

FALLBACK_ADDRESS = v1.FALLBACK_ADDRESS
FALLBACK_LANGUAGE = v1.FALLBACK_LANGUAGE
FALLBACK_TRANSLATION_POLICY = v1.FALLBACK_TRANSLATION_POLICY
FIRST_CONTACT_QUESTION = v1.FIRST_CONTACT_QUESTION
InvalidDisplayName = v1.InvalidDisplayName
OwnerProfileError = v1.OwnerProfileError
OwnerProfileSnapshot = v1.OwnerProfileSnapshot
OwnerProfileState = v1.OwnerProfileState
normalize_display_name = v1.normalize_display_name


class JournalState(str, Enum):
    PREPARED = "PREPARED"
    COMMITTED = "COMMITTED"
    COMPENSATED = "COMPENSATED"


@dataclass(frozen=True, slots=True)
class JournalEntry:
    journal_id: str
    state: JournalState
    operation: str
    prior_name: str | None
    target_name: str | None


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


class OwnerProfileAuthority(v2.OwnerProfileAuthority):
    """V4 authority whose durable journal state, never deletion, is decision."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._last_failure: OwnerProfileFailure | None = None
        self._last_cleanup_failure: StageDiagnostic | None = None

    @classmethod
    def from_existing_stores(cls) -> "OwnerProfileAuthority":
        from memory.memory_manager import get_store

        return cls(config_path=v1.config_file(), memory=get_store())

    @property
    def last_failure(self) -> OwnerProfileFailure | None:
        return self._last_failure

    @property
    def last_cleanup_failure(self) -> StageDiagnostic | None:
        return self._last_cleanup_failure

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

    def _journal_records(self):
        try:
            records = self._memory.list(kind="semantic", limit=None)
        except Exception as exc:
            raise OwnerProfileError("Owner journal memory is unavailable") from exc
        return [
            record
            for record in records
            if record.category == v1.OWNER_MEMORY_CATEGORY
            and record.key == JOURNAL_MEMORY_KEY
        ]

    def _read_journal(self) -> JournalEntry | None:
        records = self._journal_records()
        if not records:
            return None
        try:
            payload = json.loads(records[0].content)
            if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
                raise ValueError("schema")
            journal_id = payload["journal_id"]
            state = JournalState(payload["state"])
            operation = payload["operation"]
            prior = payload["prior_name"]
            target = payload["target_name"]
            if not isinstance(journal_id, str) or len(journal_id) != 32:
                raise ValueError("journal id")
            int(journal_id, 16)
            if operation not in {"set", "forget"}:
                raise ValueError("operation")
            if prior is not None:
                prior = normalize_display_name(prior)
                if prior is None:
                    raise ValueError("prior")
            if target is not None:
                target = normalize_display_name(target)
                if target is None:
                    raise ValueError("target")
            if (operation == "set") != (target is not None):
                raise ValueError("target operation")
            return JournalEntry(journal_id, state, operation, prior, target)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OwnerProfileError("Owner decision journal is invalid") from exc

    @staticmethod
    def _journal_content(entry: JournalEntry) -> str:
        return json.dumps(
            {
                "journal_id": entry.journal_id,
                "operation": entry.operation,
                "prior_name": entry.prior_name,
                "schema_version": PROFILE_SCHEMA_VERSION,
                "state": entry.state.value,
                "target_name": entry.target_name,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _write_journal(self, entry: JournalEntry) -> None:
        try:
            self._memory.remember(
                self._journal_content(entry),
                kind="semantic",
                source=JOURNAL_SOURCE,
                citation=JOURNAL_CITATION,
                category=v1.OWNER_MEMORY_CATEGORY,
                key=JOURNAL_MEMORY_KEY,
                salience=1.0,
                metadata={"schema_version": PROFILE_SCHEMA_VERSION},
            )
        except Exception as exc:
            raise OwnerProfileError("Owner journal update failed") from exc

    def _persist_state(
        self, entry: JournalEntry, state: JournalState
    ) -> tuple[JournalEntry | None, Exception | None]:
        decided = JournalEntry(
            entry.journal_id,
            state,
            entry.operation,
            entry.prior_name,
            entry.target_name,
        )
        write_error: Exception | None = None
        try:
            self._write_journal(decided)
        except Exception as exc:
            write_error = exc
        try:
            observed = self._read_journal()
        except Exception as exc:
            return None, write_error or exc
        if observed == decided:
            return decided, write_error
        return observed, write_error or OwnerProfileError("Owner journal decision mismatch")

    def _gc_journal(self) -> None:
        """Best-effort only; journal state already decided the transaction."""

        self._last_cleanup_failure = None
        try:
            self._memory.forget_key(v1.OWNER_MEMORY_CATEGORY, JOURNAL_MEMORY_KEY)
        except Exception as exc:
            self._last_cleanup_failure = StageDiagnostic(
                "cleanup-journal", self._error_type(self._root_cause(exc))
            )

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

        verified, recovery = self._drive_value(desired, prefix=prefix)
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
            stage = "read-journal"
            try:
                journal = self._read_journal()
                if journal is not None:
                    stage = f"resolve-{journal.state.value.lower()}"
                    resolved, chosen, recovery = self._resolve_journal(journal)
                    if not resolved:
                        error = OwnerProfileError("Owner journal recovery is incomplete")
                        self._latch(
                            "reconcile",
                            stage,
                            error,
                            recovery,
                            journal_state=journal.state,
                        )
                        return self._publish(chosen, reconciled=False)

                stage = "read-config"
                data, raw = self._read_config()
                try:
                    config_name = normalize_display_name(data.get(v1.OWNER_CONFIG_KEY))
                except InvalidDisplayName:
                    config_name = None
                stage = "read-memory"
                memory_name = self._memory_name()
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
                else:
                    recovery = ()
                stage = "final-readback"
                verified, final_failures = self._verify_owner_value(chosen)
                if not verified:
                    recovery = tuple(recovery) + tuple(
                        (f"final-{item_stage}", item_error)
                        for item_stage, item_error in final_failures
                    )
                    raise OwnerProfileError("Owner reconciliation verification failed")
            except Exception as exc:
                # Preserve an earlier structured recovery diagnosis when one
                # exists instead of overwriting it with a generic precondition.
                self._latch("reconcile", stage, exc, tuple(recovery) if "recovery" in locals() else ())
                return self._publish(chosen, reconciled=False)

            self._degraded_latched = False
            self._last_failure = None
            return self._publish(chosen, reconciled=True)

    def _capture_prior(self) -> str | None:
        snapshot = self.reconcile()
        if snapshot.state is OwnerProfileState.DEGRADED:
            # Do not replace the reconcile stage/root diagnostic.
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
        # If compensation is incomplete, PREPARED remains the durable restart
        # instruction. It is intentionally not garbage-collected.
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
            entry = JournalEntry(
                secrets.token_hex(16), JournalState.PREPARED, operation, prior, target
            )
            stage = "prepare-journal"
            try:
                prepared, prepare_error = self._persist_state(entry, JournalState.PREPARED)
                if prepared != entry:
                    raise prepare_error or OwnerProfileError("Owner journal preparation failed")
            except Exception as exc:
                self._latch(operation, stage, exc)
                self._publish(prior, reconciled=False)
                raise

            stage = "write-target"
            failures = self._write_owner_value(target)
            if failures:
                self._abort_precommit(entry, failures[0][1], failures[0][0])
            stage = "verify-target"
            verified, failures = self._verify_owner_value(target)
            if not verified:
                error = failures[0][1] if failures else OwnerProfileError("Target verification failed")
                self._abort_precommit(entry, error, failures[0][0] if failures else stage)

            # COMMITTED is the durable decision. A post-commit write exception
            # is success when readback proves the exact COMMITTED journal.
            stage = "decision-committed"
            committed, decision_error = self._persist_state(entry, JournalState.COMMITTED)
            if committed is None:
                error = decision_error or OwnerProfileError("Commit decision is unreadable")
                self._latch(
                    operation,
                    stage,
                    error,
                    journal_state=None,
                    decision=None,
                    divergence=True,
                )
                self._publish(target, reconciled=False)
                raise OwnerProfileTransactionError(
                    operation,
                    error,
                    self._root_cause(error),
                    (),
                    None,
                ) from error
            if committed.state is not JournalState.COMMITTED:
                self._abort_precommit(
                    entry,
                    decision_error or OwnerProfileError("Commit decision was not durable"),
                    stage,
                )

            self._degraded_latched = False
            self._last_failure = None
            self._gc_journal()  # post-commit GC: never changes or raises decision
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
    "FALLBACK_ADDRESS",
    "FALLBACK_LANGUAGE",
    "FALLBACK_TRANSLATION_POLICY",
    "FIRST_CONTACT_QUESTION",
    "InvalidDisplayName",
    "JournalEntry",
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
