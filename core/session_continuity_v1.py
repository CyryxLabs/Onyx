"""Keep a conversation coherent across provider session boundaries.

A live voice session does not last a working day.  The provider rotates the
connection every few minutes, and a rotation that loses its resumption handle
starts from nothing -- the owner has to re-explain what they were doing.

This keeps a bounded record of the conversation and folds the older part into a
short brief, so a brand-new session can be opened already knowing what is going
on.  Two properties make that safe to rely on:

**Bounded by construction.**  Turns, characters and brief length all have hard
caps.  A long day cannot grow this without limit, and a single enormous turn is
truncated rather than accepted.

**Hermetic.**  Compression calls an injected summariser, so the contract is
testable without a provider and cannot silently depend on one being reachable.
If the summariser fails, the previous brief is kept and the recent turns are
retained verbatim -- degraded continuity, never a lost conversation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

FEATURE_FLAG = "ONYX_SESSION_CONTINUITY_V1"
ENABLED_VALUE = "1"

MAX_TURNS = 400
MAX_TURN_CHARS = 4_000
MAX_BRIEF_CHARS = 2_000
DEFAULT_KEEP_RECENT = 12
DEFAULT_COMPRESS_AFTER = 40

_ROLES = frozenset({"owner", "assistant"})

Summariser = Callable[[str, str], str]
"""Takes (existing brief, transcript to fold in) and returns the new brief."""


class SessionContinuityV1Error(ValueError):
    """Raised for a malformed request, never for a summariser failure."""


@dataclass(frozen=True)
class Turn:
    role: str
    text: str

    def __post_init__(self) -> None:
        if self.role not in _ROLES:
            raise SessionContinuityV1Error(f"unknown role: {self.role!r}")
        if type(self.text) is not str or not self.text.strip():
            raise SessionContinuityV1Error("a turn must carry text")

    def rendered(self) -> str:
        speaker = "Owner" if self.role == "owner" else "Onyx"
        return f"{speaker}: {self.text}"


@dataclass
class SessionContinuityV1:
    """A bounded, compressible record of the current conversation."""

    keep_recent: int = DEFAULT_KEEP_RECENT
    compress_after: int = DEFAULT_COMPRESS_AFTER
    _brief: str = ""
    _turns: list[Turn] = field(default_factory=list)
    _compressions: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.keep_recent <= MAX_TURNS:
            raise SessionContinuityV1Error("keep_recent is out of range")
        if not self.keep_recent < self.compress_after <= MAX_TURNS:
            raise SessionContinuityV1Error(
                "compress_after must exceed keep_recent and stay within bounds"
            )

    # ── recording ───────────────────────────────────────────────────────────

    def record(self, role: str, text: str) -> None:
        """Append one turn, truncating anything unreasonably long."""
        clean = " ".join(str(text).split())[:MAX_TURN_CHARS]
        self._turns.append(Turn(role, clean))
        # A hard ceiling independent of compression, so an un-compressed
        # session still cannot grow without limit.
        if len(self._turns) > MAX_TURNS:
            del self._turns[: len(self._turns) - MAX_TURNS]

    @property
    def turns(self) -> tuple[Turn, ...]:
        return tuple(self._turns)

    @property
    def brief(self) -> str:
        return self._brief

    @property
    def compressions(self) -> int:
        return self._compressions

    def should_compress(self) -> bool:
        return len(self._turns) >= self.compress_after

    # ── compression ─────────────────────────────────────────────────────────

    def compress(self, summariser: Summariser) -> bool:
        """Fold everything older than the recent window into the brief.

        Returns ``True`` when the record was compressed.  A summariser that
        raises, or returns something unusable, leaves the conversation exactly
        as it was: the older turns are kept rather than discarded against an
        empty brief.
        """
        if not self.should_compress():
            return False
        older = self._turns[: -self.keep_recent]
        if not older:
            return False
        transcript = "\n".join(turn.rendered() for turn in older)
        try:
            produced = summariser(self._brief, transcript)
        except Exception:  # noqa: BLE001 - degraded continuity beats data loss
            return False
        if type(produced) is not str or not produced.strip():
            return False
        self._brief = " ".join(produced.split())[:MAX_BRIEF_CHARS]
        del self._turns[: -self.keep_recent]
        self._compressions += 1
        return True

    # ── handing over to a new session ───────────────────────────────────────

    def continuity_brief(self) -> str:
        """What a freshly opened session needs in order to carry on.

        Empty when there is nothing to carry, so a first session is never
        given a misleading preamble about a conversation that never happened.
        """
        recent = [turn.rendered() for turn in self._turns[-self.keep_recent:]]
        if not self._brief and not recent:
            return ""
        parts: list[str] = []
        if self._brief:
            parts.append(f"Earlier in this conversation: {self._brief}")
        if recent:
            parts.append("Most recent exchanges:\n" + "\n".join(recent))
        return "\n\n".join(parts)

    def reset(self) -> None:
        """Forget everything; used when the owner starts a new subject."""
        self._brief = ""
        self._turns.clear()
        self._compressions = 0
