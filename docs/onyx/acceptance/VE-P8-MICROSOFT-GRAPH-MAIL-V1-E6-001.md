# Phase 8 Microsoft Graph Mail V1 — E6 acceptance

- Evidence ID: `VE-P8-MICROSOFT-GRAPH-MAIL-V1-E6-001`
- Decision date: `2026-07-24`
- Decision: **ACCEPTED — default-off exact-recipient, content-verified mail draft/send contract**
- Candidate manifest: `98f9cc7c75cf496275ab326af352d3332cd8f604b702c8047f405df264034acf`
- Artifact root: `73875e708fbd9684cddec51fb34cb327b958c7e851f5035f37cbce9540cf30f0`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=2` (advisory only). The first
independent functional review returned one P1 (cross-session grant replay →
duplicate send) and one P2 (draft content not verified — subject/body swappable
under a copied digest), plus two P3s. All were fixed: an injected
`NonceLedgerV1` is consumed as the first step of `send` before any provider
mutation (durable-ledger one-shot across sessions); the send path recomputes
the frozen canonical draft-content digest and denies any mismatch; the
`internetMessageId` regex now rejects quotes (OData injection); reply drafts and
non-email recipients are denied. New adversarial tests cover each, and the
integrity and quality reviews re-verified the corrected bytes. The gate rehashed
eight candidate artifacts and reproduced **381 passed tests, 80 passed
subtests, 0 failed and 0 errors** in eighteen fresh Python processes. Eight
skips are the previously accepted platform-specific Phase 7 checks.

Accepted scope: an HMAC-signed, expiring (≤10 min), one-shot `MailSendGrantV1`
bound by a length-prefixed, domain-separated payload to the exact frozen
`LocalEmailDraftV1.draft_sha256`, a canonical order-independent recipient/cc
audience key, and account/workspace/principal; the send path additionally
recomputes the draft content digest so no substituted subject/body or audience
can be sent; write-scope (`Mail.ReadWrite`/`Mail.Send`) acquisition with exact
granted-scope validation and best-effort refresh-token rotation; a reconcilable
two-step send (`POST /me/messages` capturing `internetMessageId`, then
`POST /me/messages/{id}/send`) with a typed receipt and Sent Items
reconciliation (honest `reconciled=false` on a miss); and an uncertain-outcome
contract that consumes the grant before mutation and requires Sent Items
reconciliation before any resend, with no send auto-retry on 429. Reply drafts,
non-email recipients and attachments are denied.

Open P3 advisories, none acceptance-blocking: the default in-memory nonce
ledger protects only within one live session — cross-session, cross-restart
one-shot protection requires the host to inject a durable, atomic ledger (an
explicit host-integration invariant, analogous to the per-(workspace,
principal) `integrity_key` scoping invariant, documented on
`InMemoryNonceLedgerV1` and in ADR-0041); and the candidate verifier relies on
pytest return codes rather than asserting per-file failed/errors counts.

V1 remains exactly default-off and unwired. Live send E2E requires the Entra
app to carry delegated `Mail.ReadWrite` and `Mail.Send` with consent and an
explicitly confirmed live send; until then this is contract evidence only. It
adds no reply, reply-all, forward, delete, folder move, shared-mailbox,
attachment, calendar mutation beyond accepted Calendar V1, task/notification or
Drive/Office authority; no startup/voice/UI/dashboard wiring; no Phase 8
aggregate exit and no full Onyx PRD completion.
