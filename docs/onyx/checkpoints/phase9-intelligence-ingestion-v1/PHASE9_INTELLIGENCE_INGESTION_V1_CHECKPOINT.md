# Phase 9 intelligence ingestion V1 checkpoint

This exactly default-off candidate opens Phase 9 (intelligence and opportunity
radar) with the ingestion-normalisation contract. Behind the flag
`ONYX_PHASE9_INTELLIGENCE_INGESTION_V1`, a pure deterministic session accepts
already-collected raw items and, for each, records publication and event time
separately in UTC (denying a future publication), computes an integer freshness
in hours from an injected clock, assigns a recycled-story content signature over
the normalised (category, headline) tokens, types every claim against the closed
fact/inference/scenario/recommendation set, tags source health against a fixed
tier ladder, and marks a consequential claim corroborated only when it cites a
source distinct from the item's own. It returns a frozen `IngestionResultV1`
record with per-item duplicate linkage (earliest publication canonical), the
uncorroborated-consequential list, the unverified source count and per-category
counts.

The slice fetches no source, opens no network, calls no model, persists nothing
and takes no action — it can never turn a headline into a trade. It is built
through a sealed factory that returns `None` when the flag is unset and
otherwise entry-binds to the accepted Phase 8 exit evidence by SHA-256.

Eighteen focused tests cover exact gating and default-off, sealed-factory and
Phase 8 exit entry-binding (both the missing-evidence and the hash-drift denial
branches), temporal separation and claim typing, recycled-story dedup keeping
the earliest publication with an item-id tie-break on equal publication,
cross-category and Unicode/non-Latin-script non-collision, consequential-claim
corroboration (including self-citation not counting and non-consequential claims
never flagged), source-health tiers and unverified counting, freshness (including
the zero boundary), future-publication denial with future-event acceptance,
malformed-input rejection (batch/category/claim-type/consequential/text
byte-length/NUL/timestamp/duplicate-id/claim bounds, non-dict claim,
corroborating-source-id type and count bounds, non-int clock), determinism and
side-effect freedom, and a source scan proving no network/model/action
primitives.

The cumulative selection reproduces 439 passing tests and 80 passing subtests
across twenty-one fresh Python processes, with eight inherited, explained
platform-specific skips and zero failure/error.

Limits: contract only. No live source fetching, opportunity scoring,
conflicting-claim detection, model-assisted claim understanding, World Monitor
connector (licence-gated) or runtime wiring is added, and no Phase 9 exit or
full Onyx PRD completion is claimed.
