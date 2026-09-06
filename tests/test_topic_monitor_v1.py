"""Only genuinely new items may surface, and a failed lookup is never silence."""
from __future__ import annotations

import json
import threading
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.topic_monitor_v1 import (
    DEFAULT_INTERVAL_MS,
    MAX_HEADLINES_PER_CHECK,
    MAX_REMEMBERED_PER_TOPIC,
    MAX_TOPICS,
    MIN_INTERVAL_MS,
    TopicMonitorV1,
    TopicMonitorV1Error,
)

NOW = 1_000_000


def _static(headlines):
    return lambda _topic: list(headlines)


# -- managing subjects -------------------------------------------------------

@pytest.mark.parametrize("topic", ["", "   ", None, 7, "x" * 200])
def test_bad_topics_are_refused(topic) -> None:
    with pytest.raises(TopicMonitorV1Error):
        TopicMonitorV1().watch(topic)


def test_watching_is_case_and_space_insensitive() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("  Quantum   Computing ")
    monitor.watch("quantum computing")
    assert monitor.topics == ("Quantum Computing",)


def test_topic_count_is_capped() -> None:
    monitor = TopicMonitorV1()
    for index in range(MAX_TOPICS):
        monitor.watch(f"topic {index}")
    with pytest.raises(TopicMonitorV1Error):
        monitor.watch("one too many")


def test_interval_floor_is_enforced() -> None:
    monitor = TopicMonitorV1()
    with pytest.raises(TopicMonitorV1Error):
        monitor.watch("markets", interval_ms=MIN_INTERVAL_MS - 1)
    assert monitor.watch("markets", interval_ms=MIN_INTERVAL_MS) == "markets"


def test_unwatch_reports_whether_anything_was_removed() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    assert monitor.unwatch("MARKETS") is True
    assert monitor.unwatch("markets") is False


# -- newness -----------------------------------------------------------------

def test_first_check_returns_everything_then_nothing() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    first = monitor.poll(_static(["A rises", "B falls"]), NOW)
    assert first == {"markets": ["A rises", "B falls"]}
    later = NOW + DEFAULT_INTERVAL_MS
    assert monitor.poll(_static(["A rises", "B falls"]), later) == {}


def test_reordered_headlines_are_still_recognised_as_seen() -> None:
    """Dedup is by content; a source reshuffling its page is not news."""
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    monitor.poll(_static(["A rises", "B falls"]), NOW)
    later = NOW + DEFAULT_INTERVAL_MS
    assert monitor.poll(_static(["B falls", "A rises"]), later) == {}


def test_whitespace_and_case_do_not_make_an_item_new() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    monitor.poll(_static(["A rises"]), NOW)
    later = NOW + DEFAULT_INTERVAL_MS
    assert monitor.poll(_static(["  a   RISES  "]), later) == {}


def test_only_the_genuinely_new_item_surfaces() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    monitor.poll(_static(["A rises"]), NOW)
    later = NOW + DEFAULT_INTERVAL_MS
    assert monitor.poll(_static(["A rises", "C soars"]), later) == {
        "markets": ["C soars"]
    }


def test_duplicates_within_one_response_collapse() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    assert monitor.poll(_static(["A rises", "A rises"]), NOW) == {
        "markets": ["A rises"]
    }


# -- rate limiting -----------------------------------------------------------

def test_a_topic_is_not_rechecked_before_its_interval() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    monitor.poll(_static(["A rises"]), NOW)
    assert monitor.poll(_static(["C soars"]), NOW + 1) == {}
    assert monitor.poll(_static(["C soars"]), NOW + DEFAULT_INTERVAL_MS) == {
        "markets": ["C soars"]
    }


def test_due_reports_only_what_may_be_checked() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    assert monitor.due(NOW) == ("markets",)
    monitor.poll(_static(["A rises"]), NOW)
    assert monitor.due(NOW + 1) == ()


# -- failure handling --------------------------------------------------------

def test_a_failing_source_stays_due_and_is_never_recorded_as_quiet() -> None:
    """Treating an outage as "nothing new" hides what this exists to catch."""
    def explode(_topic):
        raise RuntimeError("source unreachable")

    monitor = TopicMonitorV1()
    monitor.watch("markets")
    assert monitor.poll(explode, NOW) == {}
    assert monitor.due(NOW) == ("markets",)
    assert monitor.poll(_static(["A rises"]), NOW) == {"markets": ["A rises"]}


@pytest.mark.parametrize("bad", [None, "a string", 42, {"a": 1}])
def test_a_malformed_response_is_ignored(bad) -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    assert monitor.poll(lambda _t: bad, NOW) == {}
    assert monitor.due(NOW) == ("markets",)


def test_non_text_headlines_are_skipped_not_fatal() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    assert monitor.poll(lambda _t: ["A rises", None, 5, "", "B falls"], NOW) == {
        "markets": ["A rises", "B falls"]
    }


# -- boundedness -------------------------------------------------------------

def test_headlines_per_check_are_capped() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets")
    fresh = monitor.poll(_static([f"item {i}" for i in range(50)]), NOW)
    assert len(fresh["markets"]) == MAX_HEADLINES_PER_CHECK


def test_memory_of_seen_items_is_bounded() -> None:
    monitor = TopicMonitorV1()
    monitor.watch("markets", interval_ms=MIN_INTERVAL_MS)
    clock = NOW
    for batch in range(40):
        clock += MIN_INTERVAL_MS
        monitor.poll(
            _static([f"b{batch} i{i}" for i in range(MAX_HEADLINES_PER_CHECK)]),
            clock,
        )
    watch = next(iter(monitor._watches.values()))
    assert len(watch.seen) <= MAX_REMEMBERED_PER_TOPIC


# -- presentation ------------------------------------------------------------

def test_nothing_new_produces_no_message_at_all() -> None:
    assert TopicMonitorV1().summary({}) == ""


def test_summary_names_each_subject() -> None:
    text = TopicMonitorV1().summary({"markets": ["A rises"], "ai": ["B ships"]})
    assert "markets: A rises" in text and "ai: B ships" in text


def test_persisted_watch_restores_its_exact_interval() -> None:
    from actions import reminder

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
        store = Path(tmp) / "watched_topics.json"
        interval = MIN_INTERVAL_MS + 1234
        with patch.object(reminder, "_topic_store_path", return_value=store):
            assert "Now watching" in reminder._topic_action(
                "watch_topic", {"topic": "markets", "interval_ms": interval}
            )
            payload = json.loads(store.read_text(encoding="utf-8"))
            assert payload["topics"][0]["interval_ms"] == interval
            restored = reminder._load_monitor()
    assert restored._watches["markets"].interval_ms == interval


@pytest.mark.asyncio
async def test_runtime_topic_search_uses_governed_tool_dispatcher() -> None:
    import main

    runtime = main.OnyxLive.__new__(main.OnyxLive)
    runtime._execute_tool = AsyncMock(
        return_value=SimpleNamespace(response={"result": "- A rises\n- B falls"})
    )
    assert await runtime._dispatch_topic_search("markets") == ["A rises", "B falls"]
    call = runtime._execute_tool.await_args.args[0]
    assert call.name == "web_search"
    assert call.args == {"query": "markets", "mode": "news"}


@pytest.mark.asyncio
async def test_runtime_periodically_polls_restored_watches_and_persists_state() -> None:
    import main

    monitor = TopicMonitorV1()
    monitor.watch("markets", interval_ms=MIN_INTERVAL_MS)
    runtime = main.OnyxLive.__new__(main.OnyxLive)
    runtime._shutdown_requested = threading.Event()
    runtime._dashboard = None
    runtime.ui = SimpleNamespace(write_log=Mock())
    runtime._dispatch_topic_search = AsyncMock(return_value=["A rises"])

    async def stop_after_first_cycle(_delay: float) -> None:
        runtime._shutdown_requested.set()

    with (
        patch("actions.reminder._load_monitor", return_value=monitor),
        patch("actions.reminder._save_monitor") as save,
        patch.object(main.asyncio, "sleep", side_effect=stop_after_first_cycle),
    ):
        await runtime._run_topic_monitor()

    runtime._dispatch_topic_search.assert_awaited_once_with("markets")
    save.assert_called_once_with(monitor)
    assert monitor.due(int(main.time.time() * 1000)) == ()


def test_manual_topic_check_cannot_call_web_search_directly() -> None:
    from actions import reminder

    monitor = TopicMonitorV1()
    monitor.watch("markets")
    with patch.object(reminder, "_load_monitor", return_value=monitor):
        result = reminder._topic_action("check_topics", {})
    assert "runtime dispatcher" in result
