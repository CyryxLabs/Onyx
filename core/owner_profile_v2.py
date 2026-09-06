"""Owner Profile V2: failure-latched durability over the frozen V1 contract.

V2 is an isolated, default-off candidate.  It deliberately imports but never
modifies V1, retaining its Unicode, state-machine, persistence, and prompt
contracts while making cross-store failure state finally-safe and diagnosable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import core.owner_profile_v1 as v1


PROFILE_SCHEMA_VERSION = 2
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
class OwnerProfileFailure:
    """Content-free diagnostic for a latched durability failure."""

    operation: str
    stage: str
    original_error_type: str
    rollback_error_types: tuple[str, ...] = ()
    divergence_possible: bool = True


class OwnerProfileTransactionError(OwnerProfileError):
    """Carries both the original and compensating failures without logging."""

    def __init__(
        self,
        operation: str,
        original_error: Exception,
        rollback_errors: tuple[Exception, ...] = (),
        *,
        operation_error: Exception | None = None,
    ) -> None:
        self.operation = operation
        self.original_error = original_error
        self.rollback_errors = rollback_errors
        self.operation_error = operation_error or original_error
        suffix = "; rollback also failed" if rollback_errors else ""
        super().__init__(f"Owner profile {operation} failed{suffix}")


class OwnerProfileAuthority(v1.OwnerProfileAuthority):
    """V2 authority whose degraded health is sticky until verified reconcile."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._degraded_latched = False
        self._last_failure: OwnerProfileFailure | None = None

    @classmethod
    def from_existing_stores(cls) -> "OwnerProfileAuthority":
        from memory.memory_manager import get_store

        return cls(config_path=v1.config_file(), memory=get_store())

    @property
    def last_failure(self) -> OwnerProfileFailure | None:
        return self._last_failure

    @property
    def degraded_latched(self) -> bool:
        return self._degraded_latched

    def _publish(
        self, name: str | None, *, reconciled: bool = True
    ) -> OwnerProfileSnapshot:
        """Never publish healthy state while degraded or reconciliation failed."""

        if not reconciled or self._degraded_latched:
            self._snapshot = OwnerProfileSnapshot(
                state=OwnerProfileState.DEGRADED,
                display_name=name,
                address=name or FALLBACK_ADDRESS,
                reconciled=False,
            )
            return self._snapshot
        return super()._publish(name, reconciled=True)

    @staticmethod
    def _error_type(error: Exception) -> str:
        return type(error).__name__[:120]

    @staticmethod
    def _root_cause(error: Exception) -> Exception:
        current = error
        seen: set[int] = set()
        while isinstance(current.__cause__, Exception) and id(current) not in seen:
            seen.add(id(current))
            current = current.__cause__
        return current

    def _latch_failure(
        self,
        operation: str,
        stage: str,
        original: Exception,
        rollback_errors: tuple[Exception, ...] = (),
    ) -> None:
        self._degraded_latched = True
        self._last_failure = OwnerProfileFailure(
            operation=operation,
            stage=stage,
            original_error_type=self._error_type(original),
            rollback_error_types=tuple(self._error_type(item) for item in rollback_errors),
            divergence_possible=True,
        )

    def _rollback_capturing(
        self, prior_config: object, prior_memory: str | None
    ) -> tuple[Exception, ...]:
        failures: list[Exception] = []
        try:
            self._write_config("" if prior_config is v1._MISSING else prior_config)
        except Exception as exc:  # both compensation attempts must run
            failures.append(self._root_cause(exc))
        try:
            if prior_memory is None:
                self._clear_memory()
            else:
                self._write_memory(prior_memory)
        except Exception as exc:  # preserve a second independent diagnosis
            failures.append(self._root_cause(exc))
        return tuple(failures)

    def reconcile(self) -> OwnerProfileSnapshot:
        """Repair and prove both stores before clearing the degraded latch."""

        with v1._PROCESS_LOCK:
            chosen = self._snapshot.display_name
            stage = "read-config"
            try:
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
                verified_data, _verified_raw = self._read_config()
                try:
                    verified_config = normalize_display_name(
                        verified_data.get(v1.OWNER_CONFIG_KEY)
                    )
                except InvalidDisplayName:
                    verified_config = None

                stage = "verify-memory"
                verified_memory = self._memory_name()
                if verified_config != chosen or verified_memory != chosen:
                    raise OwnerProfileError("Owner profile reconciliation verification failed")
            except Exception as exc:
                self._latch_failure("reconcile", stage, exc)
                return self._publish(chosen, reconciled=False)

            self._degraded_latched = False
            self._last_failure = None
            return self._publish(chosen, reconciled=True)

    def begin_contact(self) -> str | None:
        """Ask once only when both durable sources have healthy unknown state."""

        with v1._PROCESS_LOCK:
            current = self.reconcile()
            if current.state is OwnerProfileState.DEGRADED:
                return None
            if current.name_known or self._contact_prompted:
                return None
            self._contact_prompted = True
            self._publish(None, reconciled=True)
            return FIRST_CONTACT_QUESTION

    def _failed_transaction(
        self,
        *,
        operation: str,
        stage: str,
        original: Exception,
        prior_config: object,
        prior_memory: str | None,
        config_written: bool,
    ) -> None:
        """Latch first, compensate independently, and always publish degraded."""

        rollback_errors: tuple[Exception, ...] = ()
        root_original = self._root_cause(original)
        self._latch_failure(operation, stage, root_original)
        try:
            if config_written:
                rollback_errors = self._rollback_capturing(prior_config, prior_memory)
        finally:
            self._latch_failure(operation, stage, root_original, rollback_errors)
            try:
                prior_config_name = normalize_display_name(
                    None if prior_config is v1._MISSING else prior_config
                )
            except InvalidDisplayName:
                prior_config_name = None
            self._publish(
                prior_config_name or prior_memory or self._snapshot.display_name,
                reconciled=False,
            )
        if rollback_errors:
            raise OwnerProfileTransactionError(
                operation,
                root_original,
                rollback_errors,
                operation_error=original,
            ) from original
        raise original

    def set_name(self, value: object) -> OwnerProfileSnapshot:
        name = normalize_display_name(value)
        if name is None:
            raise InvalidDisplayName("A real display name is required")
        with v1._PROCESS_LOCK:
            stage = "read-prior-config"
            try:
                _data, prior_config = self._read_config()
                stage = "read-prior-memory"
                prior_memory = self._memory_name()
            except Exception as exc:
                self._latch_failure("set", stage, exc)
                self._publish(self._snapshot.display_name, reconciled=False)
                raise

            config_written = False
            try:
                stage = "write-config"
                self._write_config(name)
                config_written = True
                stage = "write-memory"
                self._write_memory(name)
                stage = "verify-config"
                verified_config = normalize_display_name(
                    self._read_config()[0].get(v1.OWNER_CONFIG_KEY)
                )
                if verified_config != name:
                    raise OwnerProfileError("Owner settings verification failed")
                stage = "verify-memory"
                if self._memory_name() != name:
                    raise OwnerProfileError("Owner preference memory verification failed")
            except Exception as exc:
                self._failed_transaction(
                    operation="set",
                    stage=stage,
                    original=exc,
                    prior_config=prior_config,
                    prior_memory=prior_memory,
                    config_written=config_written,
                )

            self._contact_prompted = True
            return self._publish(name, reconciled=not self._degraded_latched)

    def correct_name(self, value: object) -> OwnerProfileSnapshot:
        return self.set_name(value)

    def forget_name(self) -> OwnerProfileSnapshot:
        with v1._PROCESS_LOCK:
            stage = "read-prior-config"
            try:
                _data, prior_config = self._read_config()
                stage = "read-prior-memory"
                prior_memory = self._memory_name()
            except Exception as exc:
                self._latch_failure("forget", stage, exc)
                self._publish(self._snapshot.display_name, reconciled=False)
                raise

            config_written = False
            try:
                stage = "clear-config"
                self._write_config("")
                config_written = True
                stage = "clear-memory"
                self._clear_memory()
                stage = "verify-config"
                if normalize_display_name(
                    self._read_config()[0].get(v1.OWNER_CONFIG_KEY)
                ) is not None:
                    raise OwnerProfileError("Owner settings removal verification failed")
                stage = "verify-memory"
                if self._memory_name() is not None:
                    raise OwnerProfileError("Owner preference removal verification failed")
            except Exception as exc:
                self._failed_transaction(
                    operation="forget",
                    stage=stage,
                    original=exc,
                    prior_config=prior_config,
                    prior_memory=prior_memory,
                    config_written=config_written,
                )

            self._contact_prompted = False
            return self._publish(None, reconciled=not self._degraded_latched)


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
    "normalize_display_name",
]
