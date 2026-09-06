# Capability delta — Phase 9 intelligence ingestion V1

## Added behind one exact default-off flag

- Deterministic ingestion-normalisation of already-collected raw intelligence
  items: separate publication and event UTC timestamps with future-publication
  denial and integer freshness-in-hours from an injected clock.
- Recycled-story deduplication by normalised (category, headline) content
  signature, with the earliest-publication item canonical and later restatements
  linked as duplicates.
- Closed claim typing (fact / inference / scenario / recommendation) and
  consequential-claim corroboration (a distinct source is required; self-citation
  does not count), surfacing the uncorroborated-consequential list.
- Fixed source-health tier ladder with an unverified-source count and
  per-category counts.

## Not added

- Live/primary source fetching — deferred to a later gated ingestion surface.
- Transparent opportunity scoring (pain/urgency/payability/timing/moat/risk/…).
- Conflicting-claim detection and general open-text/NLP claim understanding.
- World Monitor connector — remains `BLOCKED_BY_LICENSE`.
- Any network, model call, persistence, trading or other action.
- Startup, V13, voice, dashboard or UI wiring; Phase 9 exit; full PRD completion.
