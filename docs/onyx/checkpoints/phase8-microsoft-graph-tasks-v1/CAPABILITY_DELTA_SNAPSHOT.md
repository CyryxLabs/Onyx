# Capability delta — Phase 8 Microsoft Graph Tasks V1

## Added behind one exact default-off flag

- Deterministic notification router (pure, no provider): routes typed items by
  urgency, midnight-wrapping quiet hours, workspace policy and device into
  deliver/defer/suppress decisions with explicit reasons.
- HMAC-signed, expiring, one-shot `TaskCreateGrantV1` bound to the exact
  task-draft content digest, target list and account; the create path
  recomputes the content digest and denies mismatch.
- Durable one-shot enforcement via an injected `NonceLedgerV1` consumed before
  any provider mutation.
- Route-pinned To Do transport: create (`POST /me/todo/lists/{id}/tasks`),
  read-back reconciliation (`GET .../tasks/{id}`), identity token `POST`.
- Write-scope (`Tasks.ReadWrite`) acquisition with exact granted-scope
  validation and best-effort refresh-token rotation.
- Typed receipt with read-back reconciliation and honest `reconciled=false`;
  uncertain-outcome reconcile-before-retry; no auto-retry on 429.

## Not added

- Live task-create E2E (requires `Tasks.ReadWrite` consent and a confirmed
  run).
- Task update, delete, complete, recurrence, list creation/deletion.
- Provider push notifications or a reminder-delivery transport (the router is
  decision-only).
- Calendar mutation beyond accepted Calendar V1, mail send beyond accepted
  Mail V1, Drive/OneDrive/Office.
- Startup, V13, voice, dashboard or UI wiring.
- Phase 8 aggregate exit or full PRD completion.
