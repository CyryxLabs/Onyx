# Phase 8 Microsoft Graph Tasks V1 — E6 acceptance

- Evidence ID: `VE-P8-MICROSOFT-GRAPH-TASKS-V1-E6-001`
- Decision date: `2026-07-24`
- Decision: **ACCEPTED — default-off notification router + exact-grant To Do task create contract**
- Candidate manifest: `44337ca6fdd348cd8ff7010d8ffeeb6fd6bc3167b4b80f0e3a08888b1bc859a8`
- Artifact root: `984f32cf236bac4b9ef1c4ad0a63bcf9a1384c19a0fdc8feae5720d0334f6508`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=3` (advisory only). All three
independent reviews (functional, integrity, quality) returned PASS on the first
pass — the slice incorporated every lesson from the accepted Calendar and Mail
predecessors (length-prefixed grant payload, recomputed content digest,
injected durable nonce ledger consumed before mutation, best-effort refresh
rotation, no auto-retry, route pinning). The gate rehashed eight candidate
artifacts and reproduced **403 passed tests, 80 passed subtests, 0 failed and
0 errors** in nineteen fresh Python processes. Eight skips are the previously
accepted platform-specific Phase 7 checks.

Accepted scope: (1) a pure deterministic notification router that routes typed
items by urgency, midnight-wrapping quiet hours, workspace policy and device
into deliver/defer/suppress decisions with explicit reasons and no side effect;
and (2) a Microsoft To Do task-create mutation gated by an HMAC-signed,
expiring (≤10 min), one-shot `TaskCreateGrantV1` bound to the exact task-draft
content digest, target list and account, with the send path recomputing the
content digest, the grant consumed through an injected nonce ledger before any
provider mutation, write-scope (`Tasks.ReadWrite`) acquisition with exact
granted-scope validation and best-effort rotation, a reconcilable
`POST /me/todo/lists/{id}/tasks` with a typed receipt and read-back
reconciliation (honest `reconciled=false`), and uncertain-outcome
reconcile-before-retry with no auto-retry on 429.

Open P3 advisories, none acceptance-blocking: the nonce is consumed before the
write-token step, so a denied/uncertain pre-mutation attempt burns the one-shot
grant (fail-closed; a fresh grant is then required); the read-back
reconciliation compares title and importance only (the sent payload is
digest-bound, so content integrity is still guaranteed); and `workspace_id`/
`principal_id` are HMAC-authenticated but not checked against session state
(the account is bound and verified, and the `integrity_key` must be scoped per
(workspace, principal) as documented in ADR-0042).

V1 remains exactly default-off and unwired. Live task-create E2E requires the
Entra app to carry delegated `Tasks.ReadWrite` with consent and an explicitly
confirmed run; cross-session one-shot replay protection requires the host to
inject a durable, atomic nonce ledger (the in-memory default protects only
within one session). The notification router is pure local logic. It adds no
task update/delete/complete, list mutation, provider push, reminder-delivery
transport, calendar/mail authority beyond the accepted predecessors, no
startup/voice/UI/dashboard wiring, no Phase 8 aggregate exit and no full Onyx
PRD completion.
