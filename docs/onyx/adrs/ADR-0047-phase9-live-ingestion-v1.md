# ADR-0047 — Phase 9 live ingestion V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

Phase 9 item 1 of the Onyx PRD requires primary/official-source-first ingestion
for the radar categories, with upstream/source-health attribution. Unlike the
accepted ingestion-normalisation and opportunity-scoring slices — pure
deterministic transforms — this is a live network surface: it must fetch from
external sources. The PRD guards require least privilege, source health, and a
strict prohibition on turning signals into autonomous actions; and the project
constitution treats real outbound fetching as an owner-gated operation
(registration, credentials, consent), exactly as the Phase 8 live connector runs
were.

## Decision

Add a default-off, route-pinned `phase9-live-ingestion-v1` connector behind the
exact flag `ONYX_PHASE9_LIVE_INGESTION_V1`. A session is constructed only from
an injected **approved source registry** — a sealed tuple of `ApprovedSourceV1`
records, each pinning a `source_id`, health `tier`, `category`, bare-host
`origin` and absolute query-free `path` — plus an HTTP client and a clock. The
route-pinned HTTPS client (`StdlibLiveIngestionHttpV1`) disables redirects and
accepts only `https://<origin><path>` for an approved source, with bounded
response size and no auto-retry. `fetch(source_id=…)` resolves an approved
source, GETs its feed, parses a strict neutral feed shape, bounds the item
count, and returns a `FetchResultV1` of ingestion-ready raw items plus upstream
attribution. Crucially, each item's `source_id` and health `tier` are attributed
from the **trusted registry**, never from the fetched feed, so a feed cannot
inflate its own trust or impersonate another source. The factory returns `None`
when the flag is unset and otherwise entry-binds to the accepted opportunity
scoring evidence by SHA-256.

## Consequences

- The connector's contract (route pinning, approved-source allowlist,
  registry-attributed source health, bounded strict parsing, no auto-retry) is
  fully verified with an injected transport.
- The **real network fetch against live sources is not part of this acceptance**:
  it requires owner registration of approved sources, network egress and
  consent, and remains a separately gated operation — the default-off flag and
  injected registry keep it inert until then.
- Claim typing, deduplication and corroboration remain the job of the accepted
  ingestion contract, which consumes this connector's output unchanged;
  opportunity scoring is a separate accepted slice; the licence-gated World
  Monitor connector stays out of scope.
- A fetched item is data only. The connector has no mutation, action, model or
  persistence primitive, so it can never turn a signal into a trade.

## Alternatives considered

- Trusting the feed's self-reported source id, tier or category: rejected —
  source health and categorisation are governance properties and must come from
  the operator-approved registry, not from the fetched content. The registry
  `origin` and `path` are grammar-validated (bare lowercase ASCII host; absolute
  ASCII dot-segment-free path) so a crafted or mistyped registry entry cannot
  route the pinned request off the intended host via userinfo, port or unicode.
- Following redirects to discover feeds: rejected — redirects are disabled and
  the origin/path is pinned, so a compromised or hostile endpoint cannot
  redirect the fetch off the approved surface.
- Running normalisation inside the connector: rejected — keeping fetch and
  normalisation as separate accepted slices avoids flag entanglement and keeps
  each contract independently auditable.
