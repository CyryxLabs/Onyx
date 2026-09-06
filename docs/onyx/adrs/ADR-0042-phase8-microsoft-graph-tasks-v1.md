# ADR-0042 — Phase 8 Microsoft Graph Tasks V1 (To Do create + notification routing)

- Status: candidate
- Date: 2026-07-24
- Depends on: accepted Phase 8 Mail V1 (and the full Phase 8 chain)

## Decision

Add the Phase 8 tasks-and-notifications slice behind exact default-off
`ONYX_PHASE8_MICROSOFT_GRAPH_TASKS_V1`, in two parts:

1. **Deterministic notification router** — pure, no provider, no network. It
   routes typed `NotificationItemV1` items by urgency, quiet hours
   (`QuietHoursPolicyV1`, midnight-wrapping), workspace policy and device into
   `deliver` / `defer` / `suppress` decisions, each with an explicit reason.
   Rules in order: unpermitted workspace or device → suppress; outside quiet
   hours → deliver; inside quiet hours → deliver at/above the urgency
   threshold, else defer to the next non-quiet window.
2. **To Do task create mutation** — an HMAC-signed, expiring (≤10 min),
   one-shot `TaskCreateGrantV1` bound by a length-prefixed, domain-separated
   payload to the exact frozen task-draft content digest, the target list and
   account/workspace/principal. The send path recomputes the draft content
   digest and denies any mismatch. The grant nonce is consumed through an
   injected `NonceLedgerV1` before any provider mutation (durable ledger →
   cross-session one-shot). Create is `POST /me/todo/lists/{id}/tasks`; a typed
   receipt is reconciled by reading the task back; uncertain outcomes consume
   the grant and require reconciliation before retry; no auto-retry on 429. The
   write-token path validates the granted `Tasks.ReadWrite` scope and rotates
   the refresh token best-effort (the corrected pattern).

## Authority boundary

- Route-pinned transport: `POST /v1.0/me/todo/lists/{id}/tasks`,
  `GET /v1.0/me/todo/lists/{id}/tasks/{id}`, identity token `POST` only.
- No task update, delete, complete, list creation/deletion, calendar or mail
  authority; no startup/voice/UI/dashboard wiring; frozen predecessors
  untouched.
- The notification router has no side effects and issues no provider call; it
  only computes decisions the caller may act on.

## Key-management and durability invariants

The grant binds `workspace_id`/`principal_id` cryptographically; the
`integrity_key` MUST be scoped per (workspace, principal). Cross-session,
cross-restart one-shot protection requires the host to inject a durable, atomic
`NonceLedgerV1`; the in-memory default protects only within one session.

## Live dependency

Live task creation requires the Entra app to carry delegated `Tasks.ReadWrite`
with consent and an explicitly confirmed run. Until then the mutation is
contract-proven only. The notification router is pure local logic and needs no
provider access.

## Rollback

Leave the flag unset; the factory returns before entry verification. The module
composes only public frozen contracts and can be deleted standalone.
