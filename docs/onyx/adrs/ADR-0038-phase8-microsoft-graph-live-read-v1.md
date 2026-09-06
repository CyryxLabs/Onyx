# ADR-0038 — Phase 8 Microsoft Graph Live Read V1

- Status: candidate
- Date: 2026-07-23
- Depends on: accepted Phase 8 Microsoft Graph OAuth V1

## Decision

Add an exactly default-off resilient GET transport between the accepted OAuth
session and the accepted calendar/mail read adapter. The successor honors a
valid `Retry-After` value, otherwise uses bounded exponential backoff for
retryable GET failures, refreshes the delegated session exactly once after a
`401`, and classifies terminal authentication, authorization, throttling and
provider-availability outcomes.

The transport records only route, status, attempt count, bounded wait,
request ID and terminal class. It never stores request queries, response
payloads, message bodies, bearer tokens or refresh tokens in telemetry.

## Scope and authority

The accepted read and OAuth files remain unchanged. Live Read V1 accepts only
the existing `GET /me`, `GET /me/calendarView`, `GET /me/messages` and
`GET /me/messages/{id}` routes. Caller headers are limited to the two values
already used by the accepted adapter: `Prefer` and `ConsistencyLevel`.

Automatic retries are limited to safe GET operations. `403` is terminal.
`401` permits one forced refresh and one retry. `429` and selected
provider-side `5xx` responses consume a small attempt and delay budget. A
provider delay exceeding the local budget is not shortened; the request
returns a terminal rate-limit outcome instead of retrying too early.

## Consequences

- The live read path now has bounded operational behavior for expiry,
  rejection, throttling and provider outages.
- The same transport composes directly with the accepted executive brief.
- No Entra registration, test account or live-provider result is fabricated.
- No mutation, startup, V13, voice, Orb, dashboard or UI authority is added.
- E6 remains pending until an authorized app registration and test account run
  the live endpoint suite.

## Rollback

Leave `ONYX_PHASE8_MICROSOFT_GRAPH_LIVE_READ_V1` unset. The factory returns
before predecessor verification, session access, sleep or network activity.
