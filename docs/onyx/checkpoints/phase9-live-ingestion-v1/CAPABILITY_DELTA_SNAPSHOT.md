# Capability delta — Phase 9 live ingestion V1

## Added behind one exact default-off flag

- A route-pinned, redirect-disabled HTTPS GET client that accepts only
  `https://<origin><path>` for an operator-approved source, with bounded
  response size and no auto-retry.
- An approved source registry contract (`ApprovedSourceV1`: source_id, health
  tier, category, bare-host origin, absolute query-free path) validated on
  construction, with duplicate-id rejection.
- `fetch(source_id)` that GETs an approved source, parses a strict neutral feed
  shape into ingestion-ready raw items, bounds the item count, and returns
  upstream attribution — with source id and health tier taken from the trusted
  registry, never from the fetched feed.

## Not added

- Any real network fetch against live sources — owner-gated (source
  registration, egress, consent) and deferred; default-off keeps it inert.
- Claim typing, deduplication or corroboration (the accepted ingestion contract
  performs these on the connector's output).
- Opportunity scoring, model-assisted parsing, or opportunity clustering.
- World Monitor connector — remains `BLOCKED_BY_LICENSE`.
- Any mutation, action, model call or persistence — a fetched item is data only
  and can never become a trade.
- Startup, V13, voice, dashboard or UI wiring; Phase 9 exit; full PRD completion.
