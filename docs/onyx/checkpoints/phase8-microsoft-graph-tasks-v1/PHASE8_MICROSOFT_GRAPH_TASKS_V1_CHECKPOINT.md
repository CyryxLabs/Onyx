# Phase 8 Microsoft Graph Tasks V1 checkpoint

This exactly default-off candidate adds the Phase 8 tasks-and-notifications
slice: (1) a pure deterministic notification router (urgency, midnight-wrapping
quiet hours, workspace and device → deliver/defer/suppress with reasons), and
(2) a To Do task-create mutation gated by an HMAC one-shot grant bound to the
exact task-draft content digest and list, consumed through an injected nonce
ledger before any provider mutation, with a typed receipt, read-back
reconciliation, uncertain reconcile-before-retry and no auto-retry on 429. The
write-token path validates `Tasks.ReadWrite` and rotates best-effort.

Twenty-two focused tests cover midnight-wrapping quiet hours, outside/inside
quiet-hours routing, workspace/device suppression, urgency thresholds,
notification-item contracts, exact gating, accepted-Mail entry binding, sealed
factory construction, the task-create happy path with receipt redaction and
reconciliation, denial-before-network for signature/account/draft/content/list
tamper, missing write scope, grant expiry, throttle without auto-retry,
uncertain-outcome grant consumption, reconciliation mismatch honesty,
cross-session durable-ledger replay denial, route pinning and source-invariant
scanning.

The cumulative selection contains 403 passing tests and 80 passing subtests
across nineteen fresh processes, with eight inherited and explained
platform-specific skips and zero failure/error.

Limits: the Entra registration must carry delegated `Tasks.ReadWrite` consent,
so live task-create E2E is pending and requires an explicitly confirmed run.
The notification router is pure local logic. No task update/delete/complete,
list mutation, provider push, calendar/mail authority, runtime wiring, Phase 8
aggregate exit or full PRD completion is claimed.
