"""Continuity must survive a rotation without ever growing without limit."""
from __future__ import annotations

import pytest

from core import session_continuity_v1 as continuity
from core.session_continuity_v1 import (
    MAX_BRIEF_CHARS,
    MAX_TURNS,
    MAX_TURN_CHARS,
    SessionContinuityV1,
    SessionContinuityV1Error,
)


def _joining(existing: str, transcript: str) -> str:
    return f"{existing} | {transcript}".strip(" |")


def _filled(session: SessionContinuityV1, count: int) -> SessionContinuityV1:
    for index in range(count):
        session.record("owner" if index % 2 == 0 else "assistant", f"turn {index}")
    return session


# ── contract ────────────────────────────────────────────────────────────────

def test_feature_is_declared_default_off() -> None:
    assert continuity.FEATURE_FLAG == "ONYX_SESSION_CONTINUITY_V1"


@pytest.mark.parametrize("keep,after", [(0, 10), (10, 10), (10, 5), (5, MAX_TURNS + 1)])
def test_window_bounds_are_enforced_at_construction(keep, after) -> None:
    with pytest.raises(SessionContinuityV1Error):
        SessionContinuityV1(keep_recent=keep, compress_after=after)


def test_unknown_role_is_refused() -> None:
    with pytest.raises(SessionContinuityV1Error):
        SessionContinuityV1().record("system", "hello")


def test_empty_turn_is_refused() -> None:
    for text in ("", "   ", "\n"):
        with pytest.raises(SessionContinuityV1Error):
            SessionContinuityV1().record("owner", text)


# ── boundedness ─────────────────────────────────────────────────────────────

def test_a_single_enormous_turn_is_truncated_not_accepted() -> None:
    session = SessionContinuityV1()
    session.record("owner", "x" * (MAX_TURN_CHARS * 3))
    assert len(session.turns[0].text) == MAX_TURN_CHARS


def test_record_cannot_grow_without_limit_even_uncompressed() -> None:
    """A full working day must not accumulate unbounded memory."""
    session = _filled(SessionContinuityV1(), MAX_TURNS + 50)
    assert len(session.turns) == MAX_TURNS
    assert session.turns[-1].text == f"turn {MAX_TURNS + 49}"


def test_brief_is_capped(monkeypatch) -> None:
    session = _filled(SessionContinuityV1(keep_recent=2, compress_after=6), 6)
    assert session.compress(lambda _b, _t: "y" * (MAX_BRIEF_CHARS * 3)) is True
    assert len(session.brief) == MAX_BRIEF_CHARS


# ── compression ─────────────────────────────────────────────────────────────

def test_compression_waits_for_the_threshold() -> None:
    session = _filled(SessionContinuityV1(keep_recent=2, compress_after=6), 5)
    assert session.should_compress() is False
    assert session.compress(_joining) is False
    session.record("owner", "one more")
    assert session.should_compress() is True
    assert session.compress(_joining) is True


def test_compression_keeps_the_recent_window_verbatim() -> None:
    session = _filled(SessionContinuityV1(keep_recent=3, compress_after=8), 8)
    session.compress(_joining)
    assert [t.text for t in session.turns] == ["turn 5", "turn 6", "turn 7"]
    assert "turn 0" in session.brief and "turn 4" in session.brief


def test_repeated_compression_folds_into_the_existing_brief() -> None:
    session = SessionContinuityV1(keep_recent=2, compress_after=5)
    _filled(session, 5)
    session.compress(_joining)
    first = session.brief
    _filled(session, 5)
    session.compress(_joining)
    assert session.compressions == 2
    assert first.split(" | ")[0] in session.brief


def test_a_failing_summariser_never_discards_the_conversation() -> None:
    """Degraded continuity is acceptable; a silently emptied history is not."""
    def explode(_brief, _transcript):
        raise RuntimeError("provider down")

    session = _filled(SessionContinuityV1(keep_recent=2, compress_after=6), 6)
    before = [t.text for t in session.turns]
    assert session.compress(explode) is False
    assert [t.text for t in session.turns] == before
    assert session.compressions == 0


@pytest.mark.parametrize("produced", ["", "   ", None, 42, [1]])
def test_an_unusable_summary_is_rejected(produced) -> None:
    session = _filled(SessionContinuityV1(keep_recent=2, compress_after=6), 6)
    assert session.compress(lambda _b, _t: produced) is False
    assert session.brief == ""
    assert len(session.turns) == 6


# ── handover ────────────────────────────────────────────────────────────────

def test_a_first_session_gets_no_misleading_preamble() -> None:
    assert SessionContinuityV1().continuity_brief() == ""


def test_handover_carries_both_the_brief_and_the_recent_window() -> None:
    session = _filled(SessionContinuityV1(keep_recent=2, compress_after=6), 6)
    session.compress(_joining)
    session.record("owner", "what were we doing?")
    brief = session.continuity_brief()
    assert "Earlier in this conversation:" in brief
    assert "Most recent exchanges:" in brief
    assert "what were we doing?" in brief
    assert "Owner:" in brief and "Onyx:" in brief


def test_reset_forgets_everything() -> None:
    session = _filled(SessionContinuityV1(keep_recent=2, compress_after=6), 6)
    session.compress(_joining)
    session.reset()
    assert session.continuity_brief() == ""
    assert session.turns == () and session.brief == ""
