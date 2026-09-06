"""Owner identity authority for Onyx (isolated, default-off candidate).

This module owns the semantic contract for first-contact identity.  It has no
startup, UI, dashboard, provider, or live-process wiring.  The existing
``owner_name`` non-secret setting is the primary durable value; the sanctioned
semantic preference memory is a recoverable mirror.  Cross-store updates use
atomic operations supplied by those stores plus compensating rollback.
"""

from __future__ import annotations

import threading
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, Sequence

from core.credentials import CredentialError, _read_config_object, save_settings
from core.paths import config_file
from memory.store import MemoryRecord, MemoryStoreError


PROFILE_SCHEMA_VERSION = 1
OWNER_CONFIG_KEY = "owner_name"
OWNER_MEMORY_CATEGORY = "preferences"
OWNER_MEMORY_KEY = "owner_display_name"
OWNER_MEMORY_SOURCE = "owner-profile-v1"
OWNER_MEMORY_CITATION = "user:preferences/owner_display_name"
FALLBACK_ADDRESS = "Sir"
FALLBACK_LANGUAGE = "en"
FALLBACK_TRANSLATION_POLICY = "literal-non-translatable"
FIRST_CONTACT_QUESTION = "Before we continue, what name should I use for you?"
MAX_DISPLAY_NAME_CHARS = 80

_PLACEHOLDERS = frozenset(
    {
        "",
        "sir",
        "efendim",
        "guest",
        "name",
        "owner",
        "placeholder",
        "unknown",
        "user",
        "your name",
    }
)
_ALLOWED_PUNCTUATION = frozenset({"'", "\N{RIGHT SINGLE QUOTATION MARK}", ".", "-", "\N{HYPHEN}", "\N{NON-BREAKING HYPHEN}"})
_PROCESS_LOCK = threading.RLock()


class OwnerProfileError(RuntimeError):
    """Safe owner-profile failure without config or memory contents."""


class InvalidDisplayName(OwnerProfileError):
    """Raised when proposed address text is blank, placeholder, or unsafe."""


class OwnerProfileState(str, Enum):
    UNKNOWN = "unknown"
    AWAITING_NAME = "awaiting_name"
    KNOWN = "known"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class OwnerProfileSnapshot:
    state: OwnerProfileState
    display_name: str | None
    address: str
    fallback_language: str = FALLBACK_LANGUAGE
    fallback_translation_policy: str = FALLBACK_TRANSLATION_POLICY
    reconciled: bool = True

    @property
    def name_known(self) -> bool:
        return self.display_name is not None


class PreferenceMemory(Protocol):
    def list(self, *, kind: str | None = None, limit: int | None = 100) -> Sequence[MemoryRecord]: ...

    def remember(
        self,
        content: str,
        *,
        kind: str = "semantic",
        source: str = "user",
        citation: str | None = None,
        salience: float = 0.6,
        category: str | None = None,
        key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord: ...

    def forget_key(self, category: str, key: str) -> int: ...


def normalize_display_name(value: object) -> str | None:
    """Return a prompt-safe Unicode display name or ``None`` for placeholders.

    NFC preserves the user's Unicode spelling while eliminating canonically
    equivalent byte variants.  Only characters useful in personal names and
    short aliases are admitted; instructions, markup, controls, and line
    breaks therefore cannot enter the trusted owner-profile prompt.
    """

    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFC", value)
    if any(char != " " and char.isspace() for char in normalized):
        raise InvalidDisplayName("Display name must be a single line")
    normalized = " ".join(normalized.split())
    if not normalized or normalized.casefold() in _PLACEHOLDERS:
        return None
    if len(normalized) > MAX_DISPLAY_NAME_CHARS:
        raise InvalidDisplayName("Display name is too long")
    if "efendim" in {word.casefold().strip(".'\N{RIGHT SINGLE QUOTATION MARK}-") for word in normalized.split()}:
        raise InvalidDisplayName("Translated honorifics are not valid owner names")
    if not any(unicodedata.category(char).startswith("L") for char in normalized):
        raise InvalidDisplayName("Display name must contain a letter")
    for char in normalized:
        category = unicodedata.category(char)
        if char == " " or char in _ALLOWED_PUNCTUATION:
            continue
        if category[0] in {"L", "M", "N"}:
            continue
        raise InvalidDisplayName("Display name contains unsupported characters")
    return normalized


class OwnerProfileAuthority:
    """The sole V1 authority for owner addressing and first-contact state."""

    def __init__(self, *, config_path: Path | None = None, memory: PreferenceMemory):
        if memory is None:
            raise TypeError("memory is required")
        self._config_path = Path(config_path) if config_path is not None else config_file()
        self._memory = memory
        self._contact_prompted = False
        self._snapshot = OwnerProfileSnapshot(
            state=OwnerProfileState.UNKNOWN,
            display_name=None,
            address=FALLBACK_ADDRESS,
            reconciled=False,
        )

    @classmethod
    def from_existing_stores(cls) -> "OwnerProfileAuthority":
        """Construct against sanctioned stores without activating integration."""

        from memory.memory_manager import get_store

        return cls(config_path=config_file(), memory=get_store())

    @property
    def snapshot(self) -> OwnerProfileSnapshot:
        return self._snapshot

    def _read_config(self) -> tuple[dict[str, Any], object]:
        if not self._config_path.exists():
            return {}, _MISSING
        try:
            data, _identity = _read_config_object(self._config_path)
        except (CredentialError, OSError, UnicodeError) as exc:
            raise OwnerProfileError("Owner settings are unreadable") from exc
        return data, data.get(OWNER_CONFIG_KEY, _MISSING)

    def _memory_records(self) -> list[MemoryRecord]:
        try:
            return [
                record
                for record in self._memory.list(kind="semantic", limit=None)
                if record.category == OWNER_MEMORY_CATEGORY and record.key == OWNER_MEMORY_KEY
            ]
        except (MemoryStoreError, OSError, ValueError) as exc:
            raise OwnerProfileError("Owner preference memory is unavailable") from exc

    def _memory_name(self) -> str | None:
        records = self._memory_records()
        if not records:
            return None
        try:
            return normalize_display_name(records[0].content)
        except InvalidDisplayName:
            return None

    def _write_config(self, value: object) -> None:
        try:
            save_settings({OWNER_CONFIG_KEY: value}, self._config_path)
        except (CredentialError, OSError, TypeError, ValueError) as exc:
            raise OwnerProfileError("Owner settings update failed") from exc

    def _write_memory(self, name: str) -> None:
        try:
            self._memory.remember(
                name,
                kind="semantic",
                source=OWNER_MEMORY_SOURCE,
                citation=OWNER_MEMORY_CITATION,
                category=OWNER_MEMORY_CATEGORY,
                key=OWNER_MEMORY_KEY,
                salience=1.0,
                metadata={"schema_version": PROFILE_SCHEMA_VERSION},
            )
        except (MemoryStoreError, OSError, TypeError, ValueError) as exc:
            raise OwnerProfileError("Owner preference memory update failed") from exc

    def _clear_memory(self) -> None:
        try:
            self._memory.forget_key(OWNER_MEMORY_CATEGORY, OWNER_MEMORY_KEY)
        except (MemoryStoreError, OSError, ValueError) as exc:
            # Secure WAL cleanup can report pending after logical deletion.  A
            # read-back makes the semantic outcome authoritative.
            if self._memory_name() is None:
                return
            raise OwnerProfileError("Owner preference memory removal failed") from exc

    def _publish(self, name: str | None, *, reconciled: bool = True) -> OwnerProfileSnapshot:
        state = OwnerProfileState.KNOWN if name is not None else (
            OwnerProfileState.AWAITING_NAME if self._contact_prompted else OwnerProfileState.UNKNOWN
        )
        self._snapshot = OwnerProfileSnapshot(
            state=state,
            display_name=name,
            address=name or FALLBACK_ADDRESS,
            reconciled=reconciled,
        )
        return self._snapshot

    def _rollback(self, prior_config: object, prior_memory: str | None) -> None:
        failures = 0
        try:
            self._write_config("" if prior_config is _MISSING else prior_config)
        except OwnerProfileError:
            failures += 1
        try:
            if prior_memory is None:
                self._clear_memory()
            else:
                self._write_memory(prior_memory)
        except OwnerProfileError:
            failures += 1
        if failures:
            raise OwnerProfileError("Owner profile rollback requires reconciliation")

    def reconcile(self) -> OwnerProfileSnapshot:
        """Resolve drift deterministically: valid config wins; memory recovers blanks."""

        with _PROCESS_LOCK:
            data, raw_config = self._read_config()
            try:
                config_name = normalize_display_name(data.get(OWNER_CONFIG_KEY))
            except InvalidDisplayName:
                config_name = None
            memory_name = self._memory_name()
            chosen = config_name or memory_name
            try:
                if chosen is None:
                    if raw_config is not _MISSING and raw_config != "":
                        self._write_config("")
                    if self._memory_records():
                        self._clear_memory()
                else:
                    if config_name != chosen or raw_config != chosen:
                        self._write_config(chosen)
                    if memory_name != chosen:
                        self._write_memory(chosen)
            except OwnerProfileError:
                return self._publish(chosen, reconciled=False)
            return self._publish(chosen)

    def begin_contact(self) -> str | None:
        """Return the name question exactly once for this unnamed contact."""

        with _PROCESS_LOCK:
            current = self.reconcile()
            if current.name_known or self._contact_prompted:
                return None
            self._contact_prompted = True
            self._publish(None, reconciled=current.reconciled)
            return FIRST_CONTACT_QUESTION

    def set_name(self, value: object) -> OwnerProfileSnapshot:
        """Persist a first answer; use :meth:`correct_name` for explicit correction."""

        name = normalize_display_name(value)
        if name is None:
            raise InvalidDisplayName("A real display name is required")
        with _PROCESS_LOCK:
            _data, prior_config = self._read_config()
            prior_memory = self._memory_name()
            config_written = False
            try:
                self._write_config(name)
                config_written = True
                self._write_memory(name)
                if normalize_display_name(self._read_config()[0].get(OWNER_CONFIG_KEY)) != name:
                    raise OwnerProfileError("Owner settings verification failed")
                if self._memory_name() != name:
                    raise OwnerProfileError("Owner preference memory verification failed")
            except (OwnerProfileError, InvalidDisplayName):
                if config_written:
                    self._rollback(prior_config, prior_memory)
                self._publish(prior_memory, reconciled=False)
                raise
            self._contact_prompted = True
            return self._publish(name)

    def correct_name(self, value: object) -> OwnerProfileSnapshot:
        return self.set_name(value)

    def forget_name(self) -> OwnerProfileSnapshot:
        """Forget both durable copies and reset first-contact state."""

        with _PROCESS_LOCK:
            _data, prior_config = self._read_config()
            prior_memory = self._memory_name()
            config_written = False
            try:
                self._write_config("")
                config_written = True
                self._clear_memory()
                if normalize_display_name(self._read_config()[0].get(OWNER_CONFIG_KEY)) is not None:
                    raise OwnerProfileError("Owner settings removal verification failed")
                if self._memory_name() is not None:
                    raise OwnerProfileError("Owner preference removal verification failed")
            except (OwnerProfileError, InvalidDisplayName):
                if config_written:
                    self._rollback(prior_config, prior_memory)
                self._publish(prior_memory, reconciled=False)
                raise
            self._contact_prompted = False
            return self._publish(None)

    def address(self) -> str:
        """Return the chosen name or literal English non-translatable fallback."""

        return self._snapshot.display_name or FALLBACK_ADDRESS

    def prompt_directive(self) -> str:
        """Return bounded trusted prompt text for a later host integration."""

        if self._snapshot.display_name:
            return (
                "[OWNER PROFILE - TRUSTED LOCAL CONFIGURATION]\n"
                f"The owner's chosen display name is {self._snapshot.display_name}. "
                "Use it naturally and occasionally, not in every response."
            )
        return (
            "[OWNER PROFILE - TRUSTED LOCAL CONFIGURATION]\n"
            "The owner's name is unknown. Address them with the literal English word "
            f"'{FALLBACK_ADDRESS}' only when an address is necessary. "
            "This fallback is non-translatable. Ask the configured first-contact question at most once."
        )


_MISSING = object()


__all__ = [
    "FALLBACK_ADDRESS",
    "FALLBACK_LANGUAGE",
    "FALLBACK_TRANSLATION_POLICY",
    "FIRST_CONTACT_QUESTION",
    "InvalidDisplayName",
    "OwnerProfileAuthority",
    "OwnerProfileError",
    "OwnerProfileSnapshot",
    "OwnerProfileState",
    "normalize_display_name",
]
