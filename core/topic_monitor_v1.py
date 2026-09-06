"""Watch the subjects the owner cares about and surface only what is new.

The owner names a few topics once; Onyx checks them on a schedule and mentions
anything that has actually appeared since the last look.  The whole value is in
the word *new* -- a monitor that re-announces yesterday's headline every morning
gets muted within a week, and then it protects nothing.

Design points that follow from that:

**Deduplicated by content, not position.**  A headline is remembered by digest,
so the same story re-ordered on the source page is still recognised as seen.

**Rate limited per topic.**  Each topic carries its own next-allowed time, so a
noisy source cannot pull the whole monitor into a tight loop.

**Hermetic.**  The clock and the fetcher are injected; the contract is testable
without a network and cannot silently depend on one.  A fetcher that fails
leaves the topic exactly as it was, to be retried on the next pass -- a failed
lookup must never be recorded as "nothing new".
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

FEATURE_FLAG = "ONYX_TOPIC_MONITOR_V1"
ENABLED_VALUE = "1"

MAX_TOPICS = 20
MAX_TOPIC_CHARS = 80
MAX_HEADLINES_PER_CHECK = 10
MAX_REMEMBERED_PER_TOPIC = 200
MIN_INTERVAL_MS = 15 * 60 * 1000
DEFAULT_INTERVAL_MS = 6 * 60 * 60 * 1000

Fetcher = Callable[[str], list[str]]
"""Takes a topic and returns current headlines, most recent first."""


class TopicMonitorV1Error(ValueError):
    """Raised for a malformed request, never for a fetcher failure."""


def _digest(headline: str) -> str:
    return hashlib.sha256(" ".join(headline.split()).casefold().encode()).hexdigest()[:16]


@dataclass
class _Watch:
    topic: str
    interval_ms: int
    next_due_ms: int = 0
    seen: list[str] = field(default_factory=list)

    def remember(self, digests: list[str]) -> None:
        self.seen.extend(digests)
        if len(self.seen) > MAX_REMEMBERED_PER_TOPIC:
            del self.seen[: len(self.seen) - MAX_REMEMBERED_PER_TOPIC]


@dataclass
class TopicMonitorV1:
    """A bounded set of watched subjects with per-topic rate limiting."""

    default_interval_ms: int = DEFAULT_INTERVAL_MS
    _watches: dict[str, _Watch] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not MIN_INTERVAL_MS <= self.default_interval_ms:
            raise TopicMonitorV1Error("default interval is below the floor")

    # ── managing subjects ───────────────────────────────────────────────────

    @staticmethod
    def _normalise(topic: object) -> str:
        if type(topic) is not str:
            raise TopicMonitorV1Error("a topic must be text")
        clean = " ".join(topic.split())
        if not clean or len(clean) > MAX_TOPIC_CHARS:
            raise TopicMonitorV1Error("a topic must be short and non-empty")
        return clean

    def watch(self, topic: str, *, interval_ms: int | None = None) -> str:
        """Start watching a subject; watching it again only adjusts the pace."""
        clean = self._normalise(topic)
        interval = self.default_interval_ms if interval_ms is None else interval_ms
        if type(interval) is not int or interval < MIN_INTERVAL_MS:
            raise TopicMonitorV1Error("interval is below the floor")
        key = clean.casefold()
        if key in self._watches:
            # Report the name as stored, not as just typed, so the owner is
            # never told they are watching two spellings of one subject.
            self._watches[key].interval_ms = interval
            return self._watches[key].topic
        if len(self._watches) >= MAX_TOPICS:
            raise TopicMonitorV1Error(
                f"already watching {MAX_TOPICS} subjects; drop one first"
            )
        self._watches[key] = _Watch(clean, interval)
        return clean

    def unwatch(self, topic: str) -> bool:
        return self._watches.pop(self._normalise(topic).casefold(), None) is not None

    @property
    def topics(self) -> tuple[str, ...]:
        return tuple(watch.topic for watch in self._watches.values())

    def due(self, now_ms: int) -> tuple[str, ...]:
        return tuple(
            watch.topic for watch in self._watches.values()
            if now_ms >= watch.next_due_ms
        )

    # ── checking ────────────────────────────────────────────────────────────

    def poll(self, fetcher: Fetcher, now_ms: int) -> dict[str, list[str]]:
        """Check every due subject and return only genuinely new headlines.

        A topic that raises is left untouched and stays due, so a transient
        outage is retried rather than being silently recorded as quiet.
        """
        if type(now_ms) is not int:
            raise TopicMonitorV1Error("now_ms must be an integer")
        fresh: dict[str, list[str]] = {}
        for watch in self._watches.values():
            if now_ms < watch.next_due_ms:
                continue
            try:
                headlines = fetcher(watch.topic)
            except Exception:  # noqa: BLE001 - a bad source must not end the pass
                continue
            if type(headlines) is not list:
                continue
            watch.next_due_ms = now_ms + watch.interval_ms
            known = set(watch.seen)
            new_items: list[str] = []
            new_digests: list[str] = []
            for headline in headlines[:MAX_HEADLINES_PER_CHECK]:
                if type(headline) is not str or not headline.strip():
                    continue
                marker = _digest(headline)
                if marker in known or marker in new_digests:
                    continue
                new_digests.append(marker)
                new_items.append(" ".join(headline.split()))
            watch.remember(new_digests)
            if new_items:
                fresh[watch.topic] = new_items
        return fresh

    def summary(self, fresh: dict[str, list[str]]) -> str:
        """One short line per subject, or nothing at all when nothing is new."""
        if not fresh:
            return ""
        lines = []
        for topic, items in fresh.items():
            lines.append(f"{topic}: " + "; ".join(items))
        return "\n".join(lines)
