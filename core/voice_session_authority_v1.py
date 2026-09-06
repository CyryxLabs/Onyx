"""Default-off voice-opened session authority (exact low-risk enablement).

This is the slice the capability matrix names as the next step for bounded
session grants: the first Onyx contract that can actually *grant* authority
rather than shadow it, so ordinary file and development work stops
interrupting the owner while everything consequential still stops and asks.

It is installed as the permission broker's `governance_authorization_hook`,
which the broker consults **before** the human prompt:

* ``(True, reason)``  — authorize without interrupting the owner
* ``None``            — defer to the existing approval path (unchanged)
* ``(False, reason)`` — deny outright

Governance is structural, not advisory:

* **Kill switch first.** When engaged, every evaluation denies before any
  other rule is consulted.
* **Always-explicit is absolute.** Deleting outside the roots, desktop and
  browser control, pushing, publishing, messaging, spending and credentials
  can never be allowed by an envelope; they always defer to the owner.
* **Roots contain everything.** Every path argument must resolve inside an
  authorized root. Traversal, relative paths and sibling-prefix lookalikes
  (``C:\\Work2`` against root ``C:\\Work``) defer.
* **Envelopes are bounded.** Lifetime and operation count are capped at
  construction; expiry and cap exhaustion return the session to asking.
* **Opening needs an unambiguous phrase.** A multi-word exact trigger is
  required, so a single stray word in a transcript cannot open authority.

ACCEPTED EXPOSURE — recorded, not hidden. Onyx has no speaker verification.
A transcript produced by anyone or anything near the microphone (another
person, a recording, a video) is indistinguishable from the owner speaking.
The owner was shown this and chose voice-alone opening with no confirmation
step (2026-08-19). This module therefore implements exactly that: it does
not authenticate the speaker, and the mitigations it does carry — the exact
multi-word phrase, bounded lifetime, operation cap, root containment, the
always-explicit set and the kill switch — bound the blast radius rather than
prevent a spoofed opening.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Final, Mapping

FEATURE_FLAG: Final = "ONYX_VOICE_SESSION_AUTHORITY_V1"
ENABLED_VALUE: Final = "true"
MAX_ROOTS: Final = 16
MAX_LIFETIME_MS: Final = 8 * 60 * 60 * 1000
MIN_LIFETIME_MS: Final = 60 * 1000
MAX_OPERATIONS: Final = 10_000
MAX_ID_BYTES: Final = 256
MAX_TRIGGER_BYTES: Final = 512
MIN_TRIGGER_WORDS: Final = 3
_CONSTRUCTION_KEY = object()

# Operations an open envelope may authorize without interrupting the owner:
# reading, writing and local development over the authorized roots, plus web
# search. This is exactly the owner's chosen scope (2026-08-19).
ENVELOPE_OPERATIONS: Final = frozenset(
    {
        ("file_controller", "list"),
        ("file_controller", "read"),
        ("file_controller", "find"),
        ("file_controller", "info"),
        ("file_controller", "disk_usage"),
        ("file_controller", "largest"),
        ("file_controller", "create_file"),
        ("file_controller", "create_folder"),
        ("file_controller", "write"),
        ("file_controller", "copy"),
        ("file_controller", "move"),
        ("file_controller", "rename"),
        ("file_processor", "analyze"),
        ("file_processor", "describe"),
        ("file_processor", "explain"),
        ("file_processor", "extract_text"),
        ("file_processor", "format"),
        ("file_processor", "info"),
        ("file_processor", "list"),
        ("file_processor", "review"),
        ("file_processor", "run"),
        ("file_processor", "stats"),
        ("file_processor", "summarize"),
        ("file_processor", "test"),
        ("file_processor", "validate"),
        ("file_processor", "word_count"),
        ("code_helper", "explain"),
        ("code_helper", "run"),
        ("web_search", "search"),
        ("web_search", "news"),
        ("web_search", "research"),
    }
)

# Never authorizable by an envelope, under any roots, at any time. These
# always return to the owner. `file_controller.delete` is here deliberately:
# deletion stays explicit even inside an authorized root.
ALWAYS_EXPLICIT: Final = frozenset(
    {
        ("file_controller", "delete"),
        ("file_controller", "organize_desktop"),
        ("browser_control", "*"),
        ("computer_control", "*"),
        ("desktop_control", "*"),
        ("computer_settings", "*"),
        ("send_message", "*"),
        ("dev_agent", "*"),
        ("game_updater", "*"),
    }
)

_PATH_ARGUMENT_KEYS: Final = (
    "path",
    "source",
    "destination",
    "target",
    "directory",
    "folder",
    "file",
    "output",
    "input",
)


class VoiceSessionAuthorityV1Error(RuntimeError):
    pass


class VoiceSessionAuthorityV1ContractError(ValueError):
    pass


def _text(value: object, maximum: int, *, field_name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise VoiceSessionAuthorityV1ContractError(f"{field_name} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise VoiceSessionAuthorityV1ContractError(f"{field_name} contract violation")
    return value


def _integer(value: object, *, field_name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise VoiceSessionAuthorityV1ContractError(f"{field_name} contract violation")
    return value


def _absolute_root(value: object, *, field_name: str) -> str:
    raw = _text(value, MAX_ID_BYTES, field_name=field_name)
    candidate = PurePath(raw)
    if not candidate.is_absolute():
        raise VoiceSessionAuthorityV1ContractError(f"{field_name} must be absolute")
    if any(part in {"..", "."} for part in candidate.parts):
        raise VoiceSessionAuthorityV1ContractError(f"{field_name} traversal rejected")
    return os.path.normcase(os.path.normpath(raw))


@dataclass(frozen=True, slots=True)
class VoiceSessionAuthorityFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise VoiceSessionAuthorityV1ContractError(
                "feature gate must be exact bool"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "VoiceSessionAuthorityFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class SessionEnvelopeV1:
    envelope_id: str
    roots: tuple[str, ...]
    opened_at_ms: int
    expires_at_ms: int
    operation_cap: int


@dataclass(frozen=True, slots=True)
class AuthorityDecisionV1:
    outcome: str
    reason: str

    def __post_init__(self) -> None:
        if self.outcome not in ("allow", "defer", "deny"):
            raise VoiceSessionAuthorityV1ContractError("unknown decision outcome")


def _resolve_candidate(raw: object) -> str | None:
    """Normalize a path argument, or return None when it is unusable."""
    if type(raw) is not str or not raw or "\x00" in raw:
        return None
    candidate = PurePath(raw)
    if not candidate.is_absolute():
        return None
    if any(part in {"..", "."} for part in candidate.parts):
        return None
    return os.path.normcase(os.path.normpath(raw))


def _within(root: str, candidate: str) -> bool:
    """True when candidate is root itself or a descendant of it.

    Compares whole path components so a sibling whose name merely starts with
    the root (``C:\\Work2`` against ``C:\\Work``) is never treated as inside.
    """
    if candidate == root:
        return True
    root_parts = PurePath(root).parts
    candidate_parts = PurePath(candidate).parts
    return (
        len(candidate_parts) > len(root_parts)
        and candidate_parts[: len(root_parts)] == root_parts
    )


class VoiceSessionAuthorityV1:
    """Deterministic, hermetic voice-opened session authority."""

    __slots__ = ("_trigger", "_envelope", "_operations_used", "_killed")

    def __init__(self, *, construction_key: object, trigger_phrase: str) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise VoiceSessionAuthorityV1ContractError(
                "use create_voice_session_authority_v1"
            )
        phrase = _text(trigger_phrase, MAX_TRIGGER_BYTES, field_name="trigger_phrase")
        normalized = " ".join(phrase.lower().split())
        if len(normalized.split(" ")) < MIN_TRIGGER_WORDS:
            raise VoiceSessionAuthorityV1ContractError(
                "trigger phrase must be unambiguous (multi-word)"
            )
        self._trigger = normalized
        self._envelope: SessionEnvelopeV1 | None = None
        self._operations_used = 0
        self._killed = False

    # ── kill switch ────────────────────────────────────────────────────────

    def engage_kill_switch(self) -> None:
        """Deny everything and close any open envelope. Irreversible here."""
        self._killed = True
        self._envelope = None

    @property
    def kill_switch_engaged(self) -> bool:
        return self._killed

    # ── envelope lifecycle ─────────────────────────────────────────────────

    def open_from_transcript(
        self,
        transcript: object,
        roots: object,
        *,
        envelope_id: str,
        now_ms: int,
        lifetime_ms: int,
        operation_cap: int,
    ) -> SessionEnvelopeV1:
        """Open an envelope from a spoken instruction.

        The transcript must contain the exact multi-word trigger phrase. This
        does NOT authenticate the speaker: Onyx has no speaker verification,
        and the owner accepted that exposure (2026-08-19).
        """
        if self._killed:
            raise VoiceSessionAuthorityV1ContractError(
                "kill switch is engaged; no envelope may open"
            )
        spoken = _text(transcript, MAX_TRIGGER_BYTES, field_name="transcript")
        if self._trigger not in " ".join(spoken.lower().split()):
            raise VoiceSessionAuthorityV1ContractError(
                "transcript does not carry the exact trigger phrase"
            )
        if type(roots) not in (list, tuple) or not roots:
            raise VoiceSessionAuthorityV1ContractError("roots must be a non-empty sequence")
        if len(roots) > MAX_ROOTS:
            raise VoiceSessionAuthorityV1ContractError("roots exceed the cap")
        normalized: list[str] = []
        for item in roots:
            root = _absolute_root(item, field_name="root")
            if root in normalized:
                raise VoiceSessionAuthorityV1ContractError("duplicate root")
            normalized.append(root)
        opened = _integer(now_ms, field_name="now_ms", minimum=0, maximum=2**63 - 1)
        lifetime = _integer(
            lifetime_ms,
            field_name="lifetime_ms",
            minimum=MIN_LIFETIME_MS,
            maximum=MAX_LIFETIME_MS,
        )
        cap = _integer(
            operation_cap, field_name="operation_cap", minimum=1, maximum=MAX_OPERATIONS
        )
        envelope = SessionEnvelopeV1(
            envelope_id=_text(envelope_id, MAX_ID_BYTES, field_name="envelope_id"),
            roots=tuple(normalized),
            opened_at_ms=opened,
            expires_at_ms=opened + lifetime,
            operation_cap=cap,
        )
        self._envelope = envelope
        self._operations_used = 0
        return envelope

    def close(self) -> None:
        self._envelope = None
        self._operations_used = 0

    def active_envelope(self, now_ms: int) -> SessionEnvelopeV1 | None:
        envelope = self._envelope
        if envelope is None or self._killed:
            return None
        if now_ms >= envelope.expires_at_ms:
            return None
        if self._operations_used >= envelope.operation_cap:
            return None
        return envelope

    @property
    def operations_used(self) -> int:
        return self._operations_used

    # ── decision surface ───────────────────────────────────────────────────

    @staticmethod
    def _always_explicit(tool: str, action: str) -> bool:
        return (tool, action) in ALWAYS_EXPLICIT or (tool, "*") in ALWAYS_EXPLICIT

    def evaluate(
        self, tool: object, action: object, arguments: object, now_ms: int
    ) -> AuthorityDecisionV1:
        """Decide without side effects. `consume` records a used allowance."""
        if self._killed:
            return AuthorityDecisionV1("deny", "kill switch engaged")
        tool_name = _text(tool, MAX_ID_BYTES, field_name="tool")
        action_name = _text(action, MAX_ID_BYTES, field_name="action")
        if self._always_explicit(tool_name, action_name):
            return AuthorityDecisionV1("defer", "always-explicit operation")
        envelope = self.active_envelope(now_ms)
        if envelope is None:
            return AuthorityDecisionV1("defer", "no live envelope")
        if (tool_name, action_name) not in ENVELOPE_OPERATIONS:
            return AuthorityDecisionV1("defer", "operation is outside the envelope scope")
        if type(arguments) is not dict:
            return AuthorityDecisionV1("defer", "arguments are not inspectable")
        for key in _PATH_ARGUMENT_KEYS:
            if key not in arguments:
                continue
            candidate = _resolve_candidate(arguments[key])
            if candidate is None:
                return AuthorityDecisionV1("defer", f"unsafe path argument '{key}'")
            if not any(_within(root, candidate) for root in envelope.roots):
                return AuthorityDecisionV1("defer", f"path '{key}' is outside the roots")
        return AuthorityDecisionV1("allow", f"envelope {envelope.envelope_id}")

    def consume(self, now_ms: int) -> None:
        """Record one used allowance; closes the envelope at the cap."""
        envelope = self.active_envelope(now_ms)
        if envelope is None:
            return
        self._operations_used += 1

    def governance_hook(self, tool: object, arguments: object) -> tuple[bool, str] | None:
        """Adapter for `permission_broker.set_governance_authorization_hook`.

        Returns True only for an allowed envelope operation, False only when
        the kill switch is engaged, and None for everything else so the
        existing approval path is used unchanged.
        """
        args = arguments if type(arguments) is dict else {}
        action = args.get("action", "")
        now_ms = int(args.get("__now_ms", 0))
        try:
            decision = self.evaluate(tool, action, args, now_ms)
        except VoiceSessionAuthorityV1ContractError:
            return None
        if decision.outcome == "deny":
            return False, f"Permission denied: {decision.reason}."
        if decision.outcome == "allow":
            self.consume(now_ms)
            return True, f"voice-session-authority:{decision.reason}"
        return None


def create_voice_session_authority_v1(
    trigger_phrase: str,
) -> VoiceSessionAuthorityV1:
    return VoiceSessionAuthorityV1(
        construction_key=_CONSTRUCTION_KEY, trigger_phrase=trigger_phrase
    )


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "ENVELOPE_OPERATIONS",
    "ALWAYS_EXPLICIT",
    "MAX_LIFETIME_MS",
    "MAX_OPERATIONS",
    "VoiceSessionAuthorityFeatureGateV1",
    "SessionEnvelopeV1",
    "AuthorityDecisionV1",
    "VoiceSessionAuthorityV1",
    "VoiceSessionAuthorityV1Error",
    "VoiceSessionAuthorityV1ContractError",
    "create_voice_session_authority_v1",
]
