# Phase 8 Microsoft Graph Live Read E2E V1 — Official Sources

Throttling and refresh-token pages were re-fetched and re-verified against
Microsoft Learn on 2026-07-23 for this candidate. The remaining pages were
verified on 2026-07-23 for the accepted OAuth V1 predecessor and their
contracts are unchanged in this candidate.

## Throttling and 429 Retry-After (re-verified 2026-07-23)

- [Microsoft Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling)
  states that when throttled, Graph returns HTTP `429 Too Many Requests` with
  a `Retry-After` response header carrying a suggested wait in seconds; that
  clients must avoid immediate retries; that the fastest recovery is to wait
  the `Retry-After` seconds and then retry; and that when no `Retry-After`
  header is provided, an exponential backoff retry policy is recommended.
- This candidate honors `Retry-After` exactly through an injected sleeper,
  uses deterministic bounded exponential backoff (2s, 4s) when the header is
  absent, and never retries a non-429 response. It deliberately bounds retries
  (two waits, then a typed error) instead of the documentation's
  "retry until it succeeds", because an unbounded loop is not acceptable in a
  fail-closed evidence harness; the bound is recorded in the report.
- [Microsoft Graph service-specific throttling limits](https://learn.microsoft.com/en-us/graph/throttling-limits)
  documents per-service limits; all read resources used here provide
  `Retry-After` except where indicated.

## Refresh lifecycle, rotation and revocation (re-verified 2026-07-23)

- [Refresh tokens in the Microsoft identity platform](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)
  states that refresh tokens replace themselves with a fresh token upon every
  use, that old tokens are not automatically revoked and must be deleted
  securely after acquiring a new one, that the service can revoke refresh
  tokens at any time (user action, admin action, credential change), and that
  apps must handle revocation gracefully by returning to interactive sign-in.
- The frozen OAuth V1 predecessor already persists only the latest vault
  token, treats refresh failure as honest disconnected state and never deletes
  the vault credential destructively. This candidate adds the revocation
  probe: a refresh denial whose OAuth error is `invalid_grant`,
  `interaction_required` or `consent_required` is classified as
  revoked/expired and requires interactive re-consent.
- [Microsoft Entra authentication error codes](https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes)
  documents `invalid_grant` (e.g. AADSTS50173, AADSTS70000 series) as the
  error family returned for expired/revoked grants.

## Device authorization and account verification (verified for OAuth V1)

- [OAuth 2.0 device authorization grant](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code)
  remains the sign-in protocol; the frozen OAuth V1 implementation is reused
  unchanged.
- [Get user](https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0)
  (`GET /me`, delegated `User.Read`) remains the signed-in account
  verification route.

## Public-client registration (verified for OAuth V1)

- [Quickstart: register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)
  and
  [Public and confidential client applications](https://learn.microsoft.com/en-us/entra/identity-platform/msal-client-applications)
  define the authorized registration this candidate onboards: a public native
  client with the device-code flow enabled and no client secret. The
  onboarding contract reads only public identifiers (client ID, tenant,
  test-account address) from the environment and fails closed if any
  credential-shaped variable is present.

## Local limitations

- No Entra application registration, client ID, tenant consent or test
  account exists in this candidate; live execution remains
  `BLOCKED_BY_ACCESS` until the owner completes
  `docs/onyx/PHASE8_MICROSOFT_GRAPH_LIVE_ONBOARDING.md`.
- Provider failure (5xx) and real throttling cannot be forced on demand
  against the live service; their behavior is deterministically proven by the
  focused contract tests, and live reports list unexecuted probes in
  `probes_missing` instead of claiming them.
- The live runner is an operator evidence tool; it adds no startup, voice, UI
  or dashboard wiring.
