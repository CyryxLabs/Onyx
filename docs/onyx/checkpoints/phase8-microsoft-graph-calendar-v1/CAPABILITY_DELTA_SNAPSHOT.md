# Capability delta — Phase 8 Microsoft Graph Calendar V1

## Added behind one exact default-off flag

- Deterministic UTC conflict detection and earliest-first free-slot
  computation over the frozen `CalendarEventV1` contract.
- HMAC-signed, expiring (≤10 min), one-shot `EventMutationGrantV1` bound to
  the exact frozen draft digest, workspace, principal and account.
- Route-pinned mutation client: `POST /v1.0/me/events` only, reconciliation
  `GET` only, identity token `POST` only.
- Write-scope access-token acquisition from the vault refresh token with exact
  granted-scope validation and vault rotation.
- Typed creation receipt (event id, provider request-id, digest) with
  immediate read-back reconciliation and honest `reconciled=false` reporting.
- Uncertain-outcome contract: consumed grant, typed `Uncertain` error and
  provider-state search before any fresh-grant retry; no mutation auto-retry
  on 429.
- Structural denial of attendee drafts (invitations are a later, stricter
  successor).

## Not added

- Live mutation E2E (requires `Calendars.ReadWrite` consent on the Entra app
  and an explicitly confirmed run).
- Recurring events, update, delete, cancellation, shared calendars,
  invitations.
- Mail send, tasks, notifications, Drive/OneDrive/Office.
- Startup, V13, voice, dashboard or UI wiring.
- Phase 8 aggregate exit or full PRD completion.
