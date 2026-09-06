# ADR-0037 — Phase 8 Microsoft Graph OAuth V1

- Status: candidate
- Date: 2026-07-23
- Depends on: accepted Phase 8 Microsoft Graph Read V1

## Decision

Add an exactly default-off delegated OAuth successor for the accepted Microsoft
Graph GET-only adapter. V1 uses the Microsoft identity platform device
authorization protocol for a public native client, verifies the signed-in
account through `GET /me`, persists only the refresh token through the existing
native-vault abstraction and retains the access token only in process memory.

The implementation is protocol-level and uses the Python standard library
because `requirements.txt` is part of a frozen accepted predecessor. A future
version may adopt Microsoft Authentication Library after an explicit dependency
and packaging review; it must preserve this contract and pass the same gates.

## Scope and authority

The accepted read adapter remains unchanged. OAuth V1 requests only
`User.Read`, `offline_access`, one delegated calendar-read scope and one
delegated mail-read scope. It rejects write scopes, binds the tenant, account,
workspace, principal and credential alias, and re-attests the alias before
token or provider operations.

The refresh token is stored behind an opaque native-vault reference. A rotated
refresh token replaces the prior vault value only after provider and account
validation. Access tokens are never persisted. Python strings are immutable, so
dropping a bearer-token reference cannot guarantee an in-place memory wipe;
process isolation and short access-token lifetime remain part of the boundary.

Device-code completion is one-shot. Once the token endpoint returns success,
the local pending session is consumed even if scope, account or vault
validation rejects the payload. Transient refresh failures clear the cached
access reference but retain the vault refresh token so the state is honestly
disconnected without destructive re-consent.

## Consequences

- Onyx gains a testable OAuth onboarding and refresh-token lifecycle contract.
- The bearer transport remains GET-only and route-limited to the accepted
  Microsoft Graph read surface.
- No application/client ID, tenant consent or test account is provisioned by
  this candidate.
- No startup, voice, UI, dashboard or V13 live wiring is added.
- No event creation, provider draft, mail send or other mutation authority is
  added.
- Live identity and Graph E2E remain a separate access-gated successor.

## Rollback

Leave `ONYX_PHASE8_MICROSOFT_GRAPH_OAUTH_V1` unset. The factory returns before
entry verification, alias access, vault construction or network activity.

