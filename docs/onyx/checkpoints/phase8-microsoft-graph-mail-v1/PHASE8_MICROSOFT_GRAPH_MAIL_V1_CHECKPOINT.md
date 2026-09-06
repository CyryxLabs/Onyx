# Phase 8 Microsoft Graph Mail V1 checkpoint

This exactly default-off candidate adds the highest-risk Phase 8 mutation —
sending mail — gated by an HMAC-signed, expiring, one-shot grant bound to the
exact frozen email-draft digest AND the exact recipient/cc audience. The send
is create-server-draft then send, capturing the provider `internetMessageId`
so the outcome is reconcilable against Sent Items; an uncertain outcome
consumes the grant and must be reconciled before any resend. The write-token
path fixes the Calendar V1 live defect by treating refresh-token rotation as
best-effort.

Eighteen focused tests cover exact gating, accepted-Calendar entry binding,
sealed factory construction, order-independent audience keying,
denial-before-network for signature/account/draft/audience tamper,
content-swap denial under a copied digest, digest fidelity against the frozen
read module, reply-draft and invalid-recipient denial, missing send scope,
grant expiry, the send happy path with receipt redaction and reconciliation,
same-session and cross-session (durable-ledger) one-shot replay denial,
throttle/rejection without auto-retry at both draft and send, uncertain-outcome
grant consumption and Sent Items reconciliation (found and absent),
unreconciled-receipt honesty, best-effort rotation tolerating an oversized
token, OData-injection internetMessageId rejection, route pinning of the mail
client and source-invariant scanning.

The cumulative selection contains 381 passing tests and 80 passing subtests
across eighteen fresh processes, with eight inherited and explained
platform-specific skips and zero failure/error.

Limits: the Entra registration must carry delegated `Mail.ReadWrite` and
`Mail.Send` consent, so live send E2E is pending and requires an explicitly
confirmed run. No attachments, reply, reply-all, forward, delete, folder move,
shared-mailbox, task, Drive/Office, runtime wiring, Phase 8 aggregate exit or
full PRD completion is claimed.
