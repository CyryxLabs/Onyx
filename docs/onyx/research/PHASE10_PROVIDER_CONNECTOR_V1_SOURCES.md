# Phase 10 Provider Connector V1 — sources and design basis

A governed, read-only connector contract. It reuses the hardened route-pin and
strict-origin patterns proven by the accepted Phase 9 live-ingestion connector
(`VE-P9-LIVE-INGESTION-V1-E6-001`). No real network is exercised — the contract
is verified with an injected transport only.

## PRD basis

- `plans/onyx-advanced-entity-redesign.md` Phase 10 item 1: start with one
  official provider and a test account after OAuth/app-review approval.
- Phase 10 guards: read/draft before publish; first publish per account is
  explicitly approved; never scrape private data or evade policy.

## Design decisions

- **Read-only, no publish.** The session exposes `fetch_account_status` only;
  there is no publish/post method. Publishing is a later owner-approved,
  access-gated slice.
- **Route-pinned + strict origin.** The approved provider registry declares a
  bare-lowercase-ASCII-host `api_origin` and an absolute, query-free
  `status_path`; the HTTPS client is redirect-disabled and rejects any URL whose
  scheme/host/port/userinfo/path/query/fragment or timeout does not match exactly
  (the Phase 9 userinfo-escape hardening is reused).
- **Identity attributed from the registry (anti-spoof).** `provider_id`,
  `platform` and scopes come from the trusted registry, never the response, and a
  response whose `handle` differs from the registry-declared `expected_handle` is
  denied — a spoofed response cannot impersonate the account.
- **Bounded, no auto-retry.** Response size, follower range and recent-post-id
  count are capped; there is no retry.
- **Owner-gated live fetch.** Even when enabled, a real network call requires
  OAuth/app-review, a test account, credentials and consent; the contract is
  exercised only with an injected `FakeHttp` transport and stays
  `BLOCKED_BY_ACCESS` for live use.
- **Entry-bound to the accepted editorial-calendar slice.** Construction is
  denied unless the four-file Phase 10 editorial-calendar acceptance tuple is
  byte-exact.
