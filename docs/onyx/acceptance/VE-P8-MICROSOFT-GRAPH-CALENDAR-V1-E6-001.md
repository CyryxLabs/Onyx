# Phase 8 Microsoft Graph Calendar V1 — E6 acceptance

- Evidence ID: `VE-P8-MICROSOFT-GRAPH-CALENDAR-V1-E6-001`
- Decision date: `2026-07-24`
- Decision: **ACCEPTED — default-off availability + exact-grant single-event mutation contract**
- Candidate manifest: `e28bf370f81ac991d4a384d02783aa809d6afc59a5036f75852679679a5962e4`
- Artifact root: `4f0e1e3ae48a77f3c113a5ade1bb6e7e5f770bcbe9617ca8389edfce85029c3a`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=8` (advisory only). The first
independent functional review returned six P3 findings; the two high-value ones
(NUL/field-boundary ambiguity in the signed grant payload, and an unbounded
`free_slots` input) were fixed with new adversarial tests, the grant identity
fields are now validated at issuance, attendee drafts are denied at issuance as
well as creation, and the key-management invariant (per-workspace/principal
`integrity_key`) plus deferred hardening are documented; the fixes were
independently re-confirmed closed and the integrity and quality reviews
re-verified the corrected bytes. The gate rehashed eight candidate artifacts
and reproduced **363 passed tests, 80 passed subtests, 0 failed and 0 errors**
in seventeen fresh Python processes. Eight skips are the previously accepted
platform-specific Phase 7 checks.

Accepted scope: deterministic UTC conflict detection and earliest-first
free-slot computation over the frozen `CalendarEventV1` contract; an
HMAC-signed, expiring (≤10 min), one-shot `EventMutationGrantV1` bound by a
length-prefixed, domain-separated payload to the exact frozen draft digest,
workspace, principal and account; write-scope (`Calendars.ReadWrite`)
access-token acquisition from the vault refresh token with exact granted-scope
validation and vault rotation; route-pinned single-event creation
(`POST /v1.0/me/events` only) with a typed receipt, immediate read-back
reconciliation and honest `reconciled=false` reporting; and an uncertain-outcome
contract that consumes the grant, raises a typed `Uncertain` error and requires
provider-state reconciliation before any fresh-grant retry, with no mutation
auto-retry on 429. Attendee drafts are denied at both issuance and creation.

Open P3 advisories, none acceptance-blocking: dead-code/projection nits; a
per-session (not persisted) nonce ledger whose cross-restart replay is bounded
by the ≤10-minute TTL and yields at worst a non-destructive duplicate that
reconciliation surfaces; the provider `Retry-After` value not being surfaced on
a 429 mutation rejection; and an oversized 201 body surfacing as a denial
rather than the uncertain path. These are tracked in ADR-0040 for the
live-mutation successor.

V1 remains exactly default-off and unwired. Live mutation E2E requires the
Entra app to carry delegated `Calendars.ReadWrite` consent and an explicitly
confirmed run; until then this is contract evidence only. It adds no recurring
events, update, delete, cancellation, shared-calendar, invitation, mail send,
task, notification or Drive/Office authority; no startup/voice/UI/dashboard
wiring; no Phase 8 aggregate exit and no full Onyx PRD completion.
