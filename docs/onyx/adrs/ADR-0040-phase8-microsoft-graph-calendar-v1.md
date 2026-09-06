# ADR-0040 — Phase 8 Microsoft Graph Calendar V1 (availability + exact-grant mutation)

- Status: candidate
- Date: 2026-07-24
- Depends on: accepted Phase 8 Live Read E2E V1 (and transitively OAuth V1/Read V1)

## Decision

Add the first Phase 8 provider mutation behind exact default-off
`ONYX_PHASE8_MICROSOFT_GRAPH_CALENDAR_V1`, strictly in PRD order:

1. **Deterministic availability** — pure `find_conflicts` and `free_slots`
   functions over the frozen `CalendarEventV1` read contract. UTC-only in V1;
   cancelled events ignored; bounded inputs; earliest-first slot algorithm.
2. **Exact-grant single-event creation** — `EventMutationGrantV1` is an
   HMAC-signed, expiring (≤10 min), one-shot authority bound to the exact
   frozen `LocalEventDraftV1.draft_sha256`, workspace, principal and account.
   Any byte change to the draft invalidates the grant; a used nonce can never
   authorize again.
3. **Receipt and reconciliation** — a successful `POST /me/events` yields a
   typed receipt (provider event id, request-id, digest) and is immediately
   reconciled by reading the event back and comparing subject/start/end
   instants; mismatch is reported honestly as `reconciled=false`.
4. **Uncertain outcomes fail toward reconciliation** — a transport failure at
   the mutation boundary raises `GraphCalendarV1Uncertain`; the consumed grant
   is not reusable and `reconcile_uncertain` must search provider state before
   any fresh-grant retry. Provider 429 never auto-retries a mutation.
5. **Write-scope token acquisition** — the session exchanges the vault refresh
   token for a `Calendars.ReadWrite` access token (incremental-consent
   semantics), validates the granted scope exactly, keeps the access token
   process-local and rotates the refresh token into the vault.

## Key-management invariant

The grant binds `workspace_id` and `principal_id` cryptographically, not
against session state (the session is legitimately account-scoped by the
accepted onboarding shape). Therefore the signing `integrity_key` MUST be
derived per (workspace, principal); a key shared across workspaces or
principals would make those fields informational only. This is the caller's
responsibility and is recorded on `EventMutationGrantV1`.

## Deferred hardening (tracked for the live-mutation successor)

- Persisted one-shot nonce ledger (current ledger is per-session in memory;
  cross-restart replay is bounded by the ≤10-minute TTL and yields at worst a
  non-destructive duplicate that reconciliation surfaces).
- Surfacing the provider `Retry-After` value on a 429 mutation rejection
  (correctness of no-auto-retry already holds; this is ergonomics only).
- Steering an oversized 201 response body to the uncertain path rather than a
  denial (unrealistic for an event-create response).

## Authority boundary

- The mutation transport is route-pinned: `POST` only to the exact path
  `/v1.0/me/events`; `GET` only to `/v1.0/me/events/{id}` and
  `/v1.0/me/calendarView`; identity `POST` only to the token endpoint.
- Drafts with attendees are **denied twice**: at grant issuance and again at
  creation. An invitation is an external send with a stricter gate and belongs
  to a later successor with its own evidence.
- The grant HMAC payload uses a length-prefixed, domain-separated field
  encoding so no field-content combination can collide with a different field
  split; identity fields reject empty, over-length and control-character
  values at issuance.
- No update, delete, cancellation, shared-calendar, mail or Drive authority;
  no startup/voice/UI/dashboard wiring; frozen predecessors untouched.

## Live dependency

Live execution additionally requires the Entra app to carry delegated
`Calendars.ReadWrite` with consent, and an explicitly confirmed live mutation
run. Until then the capability is contract-proven only.

## Rollback

Leave the flag unset; the factory returns before entry verification. The
module composes only public frozen contracts and can be deleted standalone.
