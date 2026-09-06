"""Owner Profile V3: restart-safe compensation over frozen V1/V2."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import core.owner_profile_v1 as v1
import core.owner_profile_v2 as v2


PROFILE_SCHEMA_VERSION = 3
RECOVERY_MEMORY_KEY = "owner_profile_v3_recovery"
RECOVERY_SOURCE = "owner-profile-v3"
RECOVERY_CITATION = "system:preferences/owner_profile_v3_recovery"

FALLBACK_ADDRESS = v1.FALLBACK_ADDRESS
FALLBACK_LANGUAGE = v1.FALLBACK_LANGUAGE
FALLBACK_TRANSLATION_POLICY = v1.FALLBACK_TRANSLATION_POLICY
FIRST_CONTACT_QUESTION = v1.FIRST_CONTACT_QUESTION
InvalidDisplayName = v1.InvalidDisplayName
OwnerProfileError = v1.OwnerProfileError
OwnerProfileSnapshot = v1.OwnerProfileSnapshot
OwnerProfileState = v1.OwnerProfileState
normalize_display_name = v1.normalize_display_name


@dataclass(frozen=True, slots=True)
class RollbackDiagnostic:
    stage: str
    error_type: str


@dataclass(frozen=True, slots=True)
class OwnerProfileFailure:
    operation: str
    stage: str
    original_error_type: str
    rollback: tuple[RollbackDiagnostic, ...] = ()
    compensation_attempted: bool = False
    compensation_complete: bool = False
    divergence_possible: bool = True


class OwnerProfileTransactionError(OwnerProfileError):
    """Safe public error retaining local programmatic failure objects."""

    def __init__(
        self,
        operation: str,
        operation_error: Exception,
        root_error: Exception,
        rollback_errors: tuple[tuple[str, Exception], ...],
        compensation_complete: bool,
    ) -> None:
        self.operation = operation
        self.operation_error = operation_error
        self.original_error = root_error
        self.rollback_errors = rollback_errors
        self.compensation_complete = compensation_complete
        suffix = " after compensation" if compensation_complete else "; recovery pending"
        super().__init__(f"Owner profile {operation} failed{suffix}")


class OwnerProfileAuthority(v2.OwnerProfileAuthority):
    """V3 authority with a durable pre-mutation recovery marker."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._last_failure: OwnerProfileFailure | None = None

    @classmethod
    def from_existing_stores(cls) -> "OwnerProfileAuthority":
        from memory.memory_manager import get_store

        return cls(config_path=v1.config_file(), memory=get_store())

    @property
    def last_failure(self) -> OwnerProfileFailure | None:
        return self._last_failure

    def _latch(
        self,
        operation: str,
        stage: str,
        original: Exception,
        rollback: tuple[tuple[str, Exception], ...] = (),
        *,
        attempted: bool = False,
        complete: bool = False,
    ) -> None:
        root = self._root_cause(original)
        self._degraded_latched = True
        self._last_failure = OwnerProfileFailure(
            operation=operation,
            stage=stage,
            original_error_type=self._error_type(root),
            rollback=tuple(
                RollbackDiagnostic(item_stage, self._error_type(self._root_cause(error)))
                for item_stage, error in rollback
            ),
            compensation_attempted=attempted,
            compensation_complete=complete,
            divergence_possible=not complete,
        )

    def _marker_record(self):
        records = self._memory_records_all()
        return next(
            (
                record
                for record in records
                if record.category == v1.OWNER_MEMORY_CATEGORY
                and record.key == RECOVERY_MEMORY_KEY
            ),
            None,
        )

    def _memory_records_all(self):
        try:
            return list(self._memory.list(kind="semantic", limit=None))
        except Exception as exc:
            raise OwnerProfileError("Owner preference memory is unavailable") from exc

    def _read_marker(self) -> tuple[str | None, str] | None:
        record = self._marker_record()
        if record is None:
            return None
        try:
            payload = json.loads(record.content)
            prior = payload["prior_name"]
            operation = payload["operation"]
            if prior is not None:
                prior = normalize_display_name(prior)
                if prior is None:
                    raise ValueError("invalid prior name")
            if operation not in {"set", "forget"}:
                raise ValueError("invalid operation")
            return prior, operation
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OwnerProfileError("Owner recovery marker is invalid") from exc

    def _write_marker(self, prior_name: str | None, operation: str) -> None:
        content = json.dumps(
            {"operation": operation, "prior_name": prior_name},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            self._memory.remember(
                content,
                kind="semantic",
                source=RECOVERY_SOURCE,
                citation=RECOVERY_CITATION,
                category=v1.OWNER_MEMORY_CATEGORY,
                key=RECOVERY_MEMORY_KEY,
                salience=1.0,
                metadata={"schema_version": PROFILE_SCHEMA_VERSION},
            )
        except Exception as exc:
            raise OwnerProfileError("Owner recovery preparation failed") from exc
        marker = self._read_marker()
        if marker != (prior_name, operation):
            raise OwnerProfileError("Owner recovery preparation verification failed")

    def _clear_marker(self) -> None:
        try:
            self._memory.forget_key(v1.OWNER_MEMORY_CATEGORY, RECOVERY_MEMORY_KEY)
        except Exception as exc:
            try:
                absent = self._marker_record() is None
            except Exception:
                absent = False
            if not absent:
                raise OwnerProfileError("Owner recovery marker removal failed") from exc
        if self._marker_record() is not None:
            raise OwnerProfileError("Owner recovery marker removal verification failed")

    def _capture_verified_prior(self) -> tuple[str | None, object]:
        snapshot = self.reconcile()
        if snapshot.state is OwnerProfileState.DEGRADED:
            raise OwnerProfileError("Owner profile is degraded; reconciliation is required")
        data, raw = self._read_config()
        try:
            config_name = normalize_display_name(data.get(v1.OWNER_CONFIG_KEY))
        except InvalidDisplayName:
            config_name = None
        memory_name = self._memory_name()
        if config_name != snapshot.display_name or memory_name != snapshot.display_name:
            raise OwnerProfileError("Owner prior-state verification failed")
        return snapshot.display_name, raw

    def _compensate(
        self, prior_name: str | None, prior_raw: object
    ) -> tuple[tuple[tuple[str, Exception], ...], bool]:
        failures: list[tuple[str, Exception]] = []

        try:
            self._write_config("" if prior_raw is v1._MISSING else prior_raw)
        except Exception as exc:
            failures.append(("rollback-config", self._root_cause(exc)))
        try:
            if prior_name is None:
                self._clear_memory()
            else:
                self._write_memory(prior_name)
        except Exception as exc:
            failures.append(("rollback-memory", self._root_cause(exc)))

        config_ok = False
        memory_ok = False
        try:
            data, _raw = self._read_config()
            try:
                config_ok = normalize_display_name(data.get(v1.OWNER_CONFIG_KEY)) == prior_name
            except InvalidDisplayName:
                config_ok = prior_name is None
        except Exception as exc:
            failures.append(("rollback-readback-config", self._root_cause(exc)))
        if not config_ok and not any(
            stage == "rollback-readback-config" for stage, _error in failures
        ):
            failures.append(
                (
                    "rollback-readback-config",
                    OwnerProfileError("Owner config compensation mismatch"),
                )
            )
        try:
            memory_ok = self._memory_name() == prior_name
        except Exception as exc:
            failures.append(("rollback-readback-memory", self._root_cause(exc)))
        if not memory_ok and not any(
            stage == "rollback-readback-memory" for stage, _error in failures
        ):
            failures.append(
                (
                    "rollback-readback-memory",
                    OwnerProfileError("Owner memory compensation mismatch"),
                )
            )

        complete = config_ok and memory_ok
        if complete:
            try:
                self._clear_marker()
            except Exception as exc:
                failures.append(("rollback-clear-marker", self._root_cause(exc)))
                complete = False
        return tuple(failures), complete

    def _recover_marker(self) -> bool:
        marker = self._read_marker()
        if marker is None:
            return True
        prior_name, prior_operation = marker
        # The marker's prior semantic value is authoritative.  Raw config from
        # the failed transaction must never be restored as the prior value.
        rollback, complete = self._compensate(
            prior_name, "" if prior_name is None else prior_name
        )
        if not complete:
            error = OwnerProfileError("Owner recovery is incomplete")
            self._latch(
                f"recover-{prior_operation}",
                "recovery",
                error,
                rollback,
                attempted=True,
                complete=False,
            )
        return complete

    def reconcile(self) -> OwnerProfileSnapshot:
        with v1._PROCESS_LOCK:
            chosen = self._snapshot.display_name
            stage = "read-recovery-marker"
            try:
                if not self._recover_marker():
                    return self._publish(chosen, reconciled=False)

                stage = "read-config"
                data, raw_config = self._read_config()
                try:
                    config_name = normalize_display_name(data.get(v1.OWNER_CONFIG_KEY))
                except InvalidDisplayName:
                    config_name = None
                chosen = config_name or chosen

                stage = "read-memory"
                memory_name = self._memory_name()
                chosen = config_name or memory_name

                stage = "repair"
                if chosen is None:
                    if raw_config is not v1._MISSING and raw_config != "":
                        self._write_config("")
                    if self._memory_records():
                        self._clear_memory()
                else:
                    if config_name != chosen or raw_config != chosen:
                        self._write_config(chosen)
                    if memory_name != chosen:
                        self._write_memory(chosen)

                stage = "verify-config"
                verified_data, _raw = self._read_config()
                try:
                    verified_config = normalize_display_name(
                        verified_data.get(v1.OWNER_CONFIG_KEY)
                    )
                except InvalidDisplayName:
                    verified_config = None
                stage = "verify-memory"
                verified_memory = self._memory_name()
                stage = "verify-marker"
                marker_absent = self._read_marker() is None
                if (
                    verified_config != chosen
                    or verified_memory != chosen
                    or not marker_absent
                ):
                    raise OwnerProfileError("Owner reconciliation verification failed")
            except Exception as exc:
                self._latch("reconcile", stage, exc)
                return self._publish(chosen, reconciled=False)

            self._degraded_latched = False
            self._last_failure = None
            return self._publish(chosen, reconciled=True)

    def _apply(self, operation: str, desired: str | None) -> OwnerProfileSnapshot:
        with v1._PROCESS_LOCK:
            try:
                prior_name, prior_raw = self._capture_verified_prior()
            except Exception as exc:
                self._latch(operation, "verify-prior", exc)
                self._publish(self._snapshot.display_name, reconciled=False)
                raise

            stage = "prepare-recovery"
            try:
                self._write_marker(prior_name, operation)
            except Exception as exc:
                self._latch(operation, stage, exc)
                self._publish(prior_name, reconciled=False)
                raise

            # Compensation is required before entering any config writer; its
            # exception may be raised after the atomic replace already committed.
            compensation_needed = True
            stage = "write-config"
            try:
                self._write_config(desired or "")
                stage = "write-memory"
                if desired is None:
                    self._clear_memory()
                else:
                    self._write_memory(desired)
                stage = "verify-config"
                data, _raw = self._read_config()
                try:
                    config_name = normalize_display_name(data.get(v1.OWNER_CONFIG_KEY))
                except InvalidDisplayName:
                    config_name = None
                stage = "verify-memory"
                memory_name = self._memory_name()
                if config_name != desired or memory_name != desired:
                    raise OwnerProfileError("Owner transaction verification failed")
                stage = "commit-clear-marker"
                self._clear_marker()
            except Exception as exc:
                root = self._root_cause(exc)
                self._latch(
                    operation, stage, root, attempted=compensation_needed, complete=False
                )
                rollback: tuple[tuple[str, Exception], ...] = ()
                complete = False
                try:
                    rollback, complete = self._compensate(prior_name, prior_raw)
                finally:
                    self._latch(
                        operation,
                        stage,
                        root,
                        rollback,
                        attempted=True,
                        complete=complete,
                    )
                    self._publish(prior_name, reconciled=False)
                raise OwnerProfileTransactionError(
                    operation, exc, root, rollback, complete
                ) from exc

            if operation == "forget":
                self._contact_prompted = False
            else:
                self._contact_prompted = True
            return self._publish(desired, reconciled=not self._degraded_latched)

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
    "OwnerProfileAuthority",
    "OwnerProfileError",
    "OwnerProfileFailure",
    "OwnerProfileSnapshot",
    "OwnerProfileState",
    "OwnerProfileTransactionError",
    "RollbackDiagnostic",
    "normalize_display_name",
]
