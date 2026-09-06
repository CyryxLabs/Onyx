# ADR-0051 — Phase 10 provider connector V1 (hermetic contract)

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

Phase 10 item 1 of the Onyx PRD is to start with one official provider and a
test account after OAuth/app-review approval. The first two Phase 10 slices
established the authorized-account inventory
(`VE-P10-BRAND-PASSPORT-V1-E6-001`) and the approval-gated editorial calendar
(`VE-P10-EDITORIAL-CALENDAR-V1-E6-001`). This ADR records the third slice: a
governed, read-only provider connector, exercised only as a hermetic contract.

## Decision

Add `core/phase10_provider_connector_v1.py`, a default-off
(`ONYX_PHASE10_PROVIDER_CONNECTOR_V1`) route-pinned, read-only connector
entry-bound to the accepted editorial-calendar four-file acceptance tuple. It
reuses the hardened patterns from the accepted Phase 9 live-ingestion connector.

Structural properties:

1. **Read-only, no publish.** The session exposes only `fetch_account_status`;
   there is no publish/post method. Publishing is a later owner-approved,
   access-gated slice.
2. **Route-pinned + strict origin.** `ApprovedProviderV1` declares a
   bare-lowercase-ASCII-host `api_origin` and an absolute, query-free
   `status_path`. `StdlibProviderConnectorHttpV1` is redirect-disabled and
   rejects any URL whose scheme/host/port/userinfo/path/query/fragment or timeout
   does not match exactly.
3. **Identity from the registry (anti-spoof).** `provider_id`, `platform` and
   scopes are attributed from the trusted registry, never from the response, and
   a response whose `handle` differs from the registry-declared `expected_handle`
   is denied.
4. **Bounded, no auto-retry.** Response size, follower range and recent-post-id
   count are capped; there is no retry.
5. **Owner-gated live fetch.** A real network call requires OAuth/app-review, a
   test account, credentials and consent; the contract is exercised only with an
   injected transport and stays `BLOCKED_BY_ACCESS` for live use.

The module opens no network in evidence, spawns no process, persists nothing and
takes no action beyond a route-pinned read.

## Consequences

- Onyx gains a governed, tamper-evident way to read one approved provider's
  account status (verification, follower count, recent post ids) for a
  registry-declared test account — the read half the PRD requires before any
  draft or publish slice.
- The slice claims no publishing, no audience research and no community action;
  it enables no autonomous social behaviour, and the live fetch is owner-gated.
- Any regression in the route pin, the anti-spoof handle check, the payload
  bounds, the entry-bind or the cumulative gate fails the slice verifier.

## Alternatives considered

- Putting the account handle in the request path/query: rejected — it would make
  the route pin dynamic and weaken the exact-match guarantee; the connector reads
  a fixed status endpoint and verifies the returned handle against the registry.
- Trusting the response's provider/platform fields: rejected — identity must come
  from the trusted registry so a spoofed or compromised endpoint cannot relabel
  the account.
- Exercising a real provider fetch in the contract: rejected — a live call is an
  owner decision (OAuth/app-review + test account) outside the default-off
  contract scope; the contract is verified with an injected transport only.
