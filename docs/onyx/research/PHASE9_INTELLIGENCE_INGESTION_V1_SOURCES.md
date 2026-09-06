# Phase 9 Intelligence Ingestion V1 — Design sources

This slice is a pure deterministic transform with no external provider, so there
is no provider API to cite. The design basis and the requirements it implements
are recorded here for auditability; verified on 2026-07-24.

## Requirement basis

- Onyx PRD, Phase 9 "Intelligence and opportunity radar", item 2: record
  publication time and event time; deduplicate recycled stories; separate fact,
  inference, scenario and recommendation; corroborate consequential claims where
  possible (`plans/onyx-advanced-entity-redesign.md`).
- Phase 9 verification guards: citation correctness, temporal freshness, source
  health and duplicate-story evaluations must pass; never turn geopolitical or
  financial headlines into autonomous trading actions.

## Temporal metadata

- Publication time and event time are modelled as distinct fields, mirroring the
  long-standing separation between an item's publication timestamp and the time
  of the event it describes (e.g. `article:published_time` versus event/occurred
  timestamps in schema.org `Event.startDate`). V1 normalises both to timezone-
  aware UTC ISO-8601 via the standard-library `datetime.fromisoformat` parser
  and denies a publication time later than the injected clock. The parser
  accepts an ISO-8601 date-only value and coerces it to `00:00:00+00:00`; a
  naive timestamp is stamped UTC. Sub-day precision is therefore not required,
  and a future *event* time is permitted (only a future *publication* time is
  denied).

## Deduplication tokenisation

- The content signature tokenises the case-folded headline with the Unicode
  word class (`\w+`), so non-Latin-script headlines (Cyrillic, CJK, Arabic and
  similar) tokenise to their own content rather than collapsing to an empty
  signature. Symbol-only headlines fall back to the whitespace-collapsed title,
  so distinct punctuation/emoji headlines remain distinct.

## Claim taxonomy and corroboration

- The closed claim taxonomy (fact / inference / scenario / recommendation)
  follows the analytic tradecraft distinction between reported fact, analytic
  inference, hypothetical scenario and prescriptive recommendation. It is a
  fixed enumeration, not a model inference, so it is deterministic and testable.
- Corroboration follows the multi-source-confirmation principle: a consequential
  claim is treated as corroborated only when it cites at least one source
  distinct from the item's own source. Self-citation does not corroborate.

## Recycled-story deduplication

- Duplicate detection uses a normalised content signature over the lower-cased
  alphanumeric tokens of the (category, headline) pair, so restated headlines
  collapse to one canonical item (earliest publication wins) while identical
  headlines in different categories stay distinct.

## Deliberately out of scope

- No live source fetching, no opportunity scoring, no conflicting-claim
  detection, no World Monitor connector (licence-gated), and no model-assisted
  claim understanding — each is a later gated successor.
