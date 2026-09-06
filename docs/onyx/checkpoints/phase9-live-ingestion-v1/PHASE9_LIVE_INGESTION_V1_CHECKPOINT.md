# Phase 9 live ingestion V1 checkpoint

This exactly default-off candidate adds the live/official-source ingestion
connector, the third Phase 9 slice. Behind the flag
`ONYX_PHASE9_LIVE_INGESTION_V1`, a session is built only from an injected
approved source registry (a sealed tuple of `ApprovedSourceV1` records pinning
`source_id`, health `tier`, `category`, bare-host `origin` and absolute
query-free `path`), a route-pinned HTTPS client and a clock. The client
(`StdlibLiveIngestionHttpV1`) disables redirects and accepts only
`https://<origin><path>` for an approved source, with bounded response size and
no auto-retry. `fetch(source_id=…)` resolves an approved source, GETs its feed,
parses a strict neutral feed shape, bounds the item count, and returns a
`FetchResultV1` of ingestion-ready raw items plus upstream attribution — with
each item's `source_id`, health `tier` and `category` attributed from the
trusted registry, never from the fetched feed. The approved `origin` is
grammar-validated as a bare lowercase ASCII host and the `path` as an absolute
ASCII dot-segment-free path, so the route pin's `netloc == origin == hostname`
equality cannot be defeated by a userinfo, port or unicode registry entry.

The connector composes the accepted intelligence ingestion contract, which
consumes its output unchanged. It has no mutation, action, model or persistence
primitive, so a fetched item is data only and can never become a trade. The
factory returns `None` when the flag is unset and otherwise entry-binds to the
accepted opportunity scoring evidence by SHA-256.

**The real network fetch against live sources is not exercised by this
acceptance.** It requires the owner to register approved sources and permit
network egress; the default-off flag and the injected-registry requirement keep
the connector inert until then — the same owner-gating posture the accepted
Phase 8 live connector runs used.

Eighteen focused tests cover exact gating and default-off, sealed-factory and
opportunity-scoring entry-binding (both missing-evidence and hash-drift
branches), approved-source validation (tier, category, and hardened host and
path grammar rejecting userinfo, port, unicode, empty labels, dot-segments and
protocol-relative paths), registry validation (type, emptiness, non-record,
duplicate id), source-health attribution from the registry with a feed that
tries to self-report a higher tier and a spoofed id, category being
registry-authoritative (a feed label is ignored), composition of the fetched
output into the accepted ingestion contract, unknown-source and non-200
rejection, feed shape-drift denial (non-list items, item cap and its accepting
boundary, non-dict item, non-list claims, empty id, NUL title), route pinning of
the client before any network (cross-origin, cross-path, scheme downgrade,
query, fragment and wrong timeout), behavioural proof that the opener suppresses
redirects (every redirect handler returns `None`), the real client's
success/oversize/HTTPError/URLError decode paths via a fake opener, strict-JSON
size/duplicate-key/non-object/invalid enforcement, response-dataclass status and
payload validation, the non-int clock guard, and a source scan confirming
redirects are disabled and no mutation/action/auto-retry primitive is present.

The cumulative selection reproduces 472 passing tests and 80 passing subtests
across twenty-three fresh Python processes, with eight inherited, explained
platform-specific skips and zero failure/error.

Limits: contract only. The live network fetch is owner-gated and deferred. No
claim typing/dedup/corroboration (the accepted ingestion contract does this), no
opportunity scoring, no model-assisted parsing, no World Monitor connector
(licence-gated) and no runtime wiring is added, and no Phase 9 exit or full Onyx
PRD completion is claimed.
