# Phase 8 Microsoft Graph Calendar V1 checkpoint

This exactly default-off candidate adds the first Phase 8 provider mutation in
PRD order: deterministic conflict/availability computation over the frozen
read contract, and single-event creation gated by an HMAC-signed, expiring,
one-shot grant bound to the exact local draft digest, with a typed receipt,
read-back reconciliation, honest unreconciled reporting, and
reconcile-before-retry semantics for uncertain outcomes. Attendee drafts are
structurally denied because invitations are external sends with a stricter
gate.

Eighteen focused tests cover exact gating, accepted-predecessor entry binding,
sealed/complete factory construction, conflict detection with cancelled and
boundary events, non-UTC denial, deterministic bounded free slots (including
non-tuple and over-cap rejection), grant issue/tamper/expiry/one-shot
matrices, length-prefixed payload unambiguity and identity-field validation,
the full creation happy path with receipt redaction and scope-sorted refresh,
denial-before-network cases, attendee denial at both issuance and creation,
missing write scope, throttle/rejection without auto-retry, uncertain-outcome
reconciliation (found and absent), reconciliation mismatch honesty, access
token caching, route pinning of the mutation client and source-invariant
scanning.

The cumulative selection contains 363 passing tests and 80 passing subtests
across seventeen fresh processes, with eight inherited and explained
platform-specific skips and zero failure/error.

Limits: the Entra registration does not yet carry `Calendars.ReadWrite`
consent, so live mutation E2E is pending and requires an explicitly confirmed
run. No recurring events, update, delete, invitation, shared-calendar, mail
send, task, Drive/Office, runtime wiring, Phase 8 aggregate exit or full PRD
completion is claimed.
