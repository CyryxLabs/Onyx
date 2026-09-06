"""Structured, cited, read-only web research for Onyx opportunities."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Final, Mapping, Protocol, Sequence
from urllib.parse import urlparse


SCHEMA: Final = "OnyxWebOpportunityResearch.v1"
MAX_RESULTS: Final = 20
MAX_QUERY_CHARS: Final = 500
MAX_TEXT_CHARS: Final = 4_000
MODES: Final = frozenset({"search", "news"})
_INSTRUCTION_SIGNALS: Final = (
    ("instruction_override", re.compile(r"\bignore (?:all |the )?(?:previous|prior) instructions?\b", re.I)),
    ("authority_impersonation", re.compile(r"\b(?:system|developer) message\s*:", re.I)),
    ("tool_coercion", re.compile(r"\b(?:execute|run)\s+(?:this\s+)?(?:command|tool)\b", re.I)),
)


class WebOpportunityResearchV1Error(RuntimeError):
    pass


class WebOpportunityResearchV1ContractError(ValueError):
    pass


class WebOpportunityResearchV1Denied(PermissionError):
    pass


class SearchProviderV1(Protocol):
    def search(
        self, query: str, *, mode: str, max_results: int
    ) -> Sequence[Mapping[str, object]]: ...


@dataclass(frozen=True, slots=True)
class ResearchEvidenceV1:
    evidence_id: str
    url: str
    publisher: str
    title: str
    snippet: str
    published_at: str | None
    retrieved_at: str
    instruction_signals: tuple[str, ...]
    content_trust: str = "untrusted_web_data"
    actionable: bool = False


@dataclass(frozen=True, slots=True)
class WebResearchReceiptV1:
    schema: str
    status: str
    query_sha256: str
    mode: str
    evidence: tuple[ResearchEvidenceV1, ...]
    provider_called: bool
    model_called: bool
    mutation_performed: bool


class DdgsSearchProviderV1:
    """Lazy DDGS adapter; no search result URL is subsequently fetched."""

    def search(
        self, query: str, *, mode: str, max_results: int
    ) -> Sequence[Mapping[str, object]]:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        try:
            with DDGS() as client:
                iterator = (
                    client.news(query, max_results=max_results)
                    if mode == "news"
                    else client.text(query, max_results=max_results)
                )
                return tuple(dict(item) for item in iterator)
        except Exception as exc:
            raise WebOpportunityResearchV1Error("web search provider failed") from exc


def _text(value: object, label: str, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str:
        return ""
    text = " ".join(value.split())
    if len(text) > maximum or "\x00" in text:
        raise WebOpportunityResearchV1Denied(f"{label} exceeded its bound")
    return text


def _public_url(value: object) -> tuple[str, str]:
    text = _text(value, "url", 2_048)
    parsed = urlparse(text)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise WebOpportunityResearchV1Denied("search result URL is invalid")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise WebOpportunityResearchV1Denied("search result URL is invalid")
    return text, parsed.hostname.casefold()


def _signals(text: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in _INSTRUCTION_SIGNALS if pattern.search(text))


class WebOpportunityResearchV1:
    def __init__(
        self,
        provider: SearchProviderV1 | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._provider = DdgsSearchProviderV1() if provider is None else provider
        if not hasattr(self._provider, "search") or not callable(clock):
            raise WebOpportunityResearchV1ContractError("provider or clock is invalid")
        self._clock = clock

    def research(
        self, query: object, *, mode: str = "search", max_results: int = 8
    ) -> WebResearchReceiptV1:
        normalized = _text(query, "query", MAX_QUERY_CHARS)
        if not normalized:
            raise WebOpportunityResearchV1ContractError("query is required")
        if _signals(normalized):
            raise WebOpportunityResearchV1Denied("query failed the intent security scan")
        if mode not in MODES:
            raise WebOpportunityResearchV1ContractError("mode is invalid")
        if type(max_results) is not int or not 1 <= max_results <= MAX_RESULTS:
            raise WebOpportunityResearchV1ContractError("max_results is outside its bound")
        retrieved = self._clock()
        if not isinstance(retrieved, datetime) or retrieved.tzinfo is None:
            raise WebOpportunityResearchV1ContractError("clock must return aware datetime")
        retrieved_at = retrieved.astimezone(timezone.utc).isoformat()
        raw = self._provider.search(normalized, mode=mode, max_results=max_results)
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise WebOpportunityResearchV1Denied("provider results are invalid")
        if len(raw) > max_results:
            raise WebOpportunityResearchV1Denied("provider exceeded the result cap")
        evidence: list[ResearchEvidenceV1] = []
        seen_urls: set[str] = set()
        for item in raw:
            if not isinstance(item, Mapping):
                raise WebOpportunityResearchV1Denied("provider result shape drift")
            url, host = _public_url(item.get("url") or item.get("href"))
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title = _text(item.get("title"), "title")
            snippet = _text(item.get("body") or item.get("snippet"), "snippet")
            if not title:
                continue
            publisher = _text(item.get("source"), "publisher", 256) or host
            published = _text(item.get("date"), "published_at", 128) or None
            digest = hashlib.sha256(
                f"{url}\0{title}\0{retrieved_at}".encode("utf-8")
            ).hexdigest()
            evidence.append(
                ResearchEvidenceV1(
                    "web_" + digest[:32],
                    url,
                    publisher,
                    title,
                    snippet,
                    published,
                    retrieved_at,
                    _signals(f"{title} {snippet}"),
                )
            )
        return WebResearchReceiptV1(
            SCHEMA,
            "completed" if evidence else "no_results",
            hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            mode,
            tuple(evidence),
            True,
            False,
            False,
        )


__all__ = [
    "DdgsSearchProviderV1",
    "ResearchEvidenceV1",
    "SCHEMA",
    "SearchProviderV1",
    "WebOpportunityResearchV1",
    "WebOpportunityResearchV1ContractError",
    "WebOpportunityResearchV1Denied",
    "WebOpportunityResearchV1Error",
    "WebResearchReceiptV1",
]
