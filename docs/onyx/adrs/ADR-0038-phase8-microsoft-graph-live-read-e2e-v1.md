# ADR-0038 — Phase 8 Microsoft Graph Live Read E2E V1

- Status: candidate
- Date: 2026-07-23
- Depends on: accepted Phase 8 Microsoft Graph OAuth V1

## Decision

Add an exactly default-off live read-only E2E successor behind
`ONYX_PHASE8_MICROSOFT_GRAPH_LIVE_READ_E2E_V1`. V1 composes the frozen OAuth V1
and Graph Read V1 contracts without modifying them and adds three things:

1. A secret-free onboarding contract that reads only public identifiers
   (Entra application/client ID, tenant, authorized test-account address) from
   the environment and fails closed if any credential-shaped variable
   (`*_CLIENT_SECRET`, `*_PASSWORD`, `*_REFRESH_TOKEN`, `*_ACCESS_TOKEN`) is
   present. No client secret or user credential can enter the repository or
   the process through this contract.
2. A throttle-aware transport wrapper that honors `429 Retry-After` exactly,
   uses deterministic bounded backoff (2s, 4s) when the header is absent,
   bounds retries at two waits before raising a typed error, never retries a
   non-429 response, and records redacted observations (route, path, status,
   sanitized OAuth error code, retry delay, attempt) — never payloads, tokens
   or query strings.
3. A probe harness producing a typed redacted report over six behaviors:
   sign-in/read, access expiry forcing refresh, refresh rotation, revocation
   classification (`invalid_grant`/`interaction_required`/`consent_required`),
   provider failure without automatic retry, and rate-limit Retry-After
   honoring.

## Honesty contract

- Each probe records `mode`: `live` or `injected_fault`. Declaring `live`
  requires the real stdlib HTTPS transport by exact type; an injected
  transport cannot label its evidence live.
- The report lists `probes_missing` explicitly and sets `live_verified` only
  when every probe ran live. Provider failure and real throttling cannot be
  forced against the live service on demand, so their behavior is proven by
  deterministic contract tests and live reports name them as missing rather
  than claiming them.
- The report never contains bearer tokens, refresh tokens, device codes,
  payload bodies or query strings.

## Scope and authority

The transport remains GET-only through the frozen bearer transport's route
allowlist. No provider mutation, task, notification, Drive/OneDrive/Office
route, startup, voice, UI or dashboard wiring is added. The operator runner
`scripts/run_phase8_microsoft_graph_live_read_e2e_v1.py` executes only when
invoked manually with the flag and onboarding environment set, uses an
isolated per-run control-plane sandbox, keeps the refresh token in the OS
native vault and writes a redacted JSON report under `runtime/`.

## Consequences

- Once the owner completes the authorized Entra registration and test-account
  onboarding, live read-only E2E evidence can be produced without any code
  change.
- Until then the live capability remains `BLOCKED_BY_ACCESS`; the local
  contract is the only accepted claim.
- The bounded-retry divergence from the provider's "retry until success"
  guidance is deliberate and documented in the research note.

## Rollback

Leave `ONYX_PHASE8_MICROSOFT_GRAPH_LIVE_READ_E2E_V1` unset. The factory
returns before entry verification, onboarding, alias access or network
construction. Deleting the successor files restores the accepted OAuth V1
surface untouched.
