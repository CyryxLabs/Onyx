# ADR-0041 — Phase 8 Microsoft Graph Mail V1 (draft/send with exact-recipient grant)

- Status: candidate
- Date: 2026-07-24
- Depends on: accepted Phase 8 Calendar V1 (and transitively the live-read/OAuth/read chain)

## Decision

Add the highest-risk Phase 8 mutation — sending mail — behind exact default-off
`ONYX_PHASE8_MICROSOFT_GRAPH_MAIL_V1`:

1. **Exact-recipient, content-verified grant** — `MailSendGrantV1` is an
   HMAC-signed, expiring (≤10 min), one-shot authority bound by a
   length-prefixed, domain-separated payload to the exact frozen
   `LocalEmailDraftV1.draft_sha256` **and** a canonical order-independent,
   casefolded digest of the exact recipient and cc sets (`recipient_key`). The
   send path additionally **recomputes the draft's content digest** and denies
   any mismatch, so a grant cannot authorize a substituted subject/body under a
   copied digest field. Reply drafts and non-email recipient addresses are
   denied. A send can never reach an audience or carry content the grant did
   not approve.
2. **Reconcilable send** — the send is performed as create-server-draft
   (`POST /me/messages`, capturing the provider-assigned `internetMessageId`)
   then send (`POST /me/messages/{id}/send`). The captured `internetMessageId`
   makes the outcome verifiable against Sent Items.
3. **Receipt and reconciliation** — a successful send yields a typed receipt
   (message id, internetMessageId, recipient_key, request-id) and is
   reconciled by a Sent Items `$filter` on `internetMessageId`; a miss is
   reported honestly as `reconciled=false`.
4. **Durable one-shot, uncertain outcomes fail toward reconciliation** — the
   grant nonce is consumed through an injected `NonceLedgerV1` as the first
   step of `send`, before any provider mutation. With a durable, atomic ledger
   this makes the grant one-shot **across sessions and restarts**: a second
   session handed the same still-valid grant is denied before creating any
   draft, so no duplicate mail is sent. `reconcile_uncertain` searches Sent
   Items by `internetMessageId` before any resend. No mutation auto-retry on
   429. The default `InMemoryNonceLedgerV1` protects only within one live
   object; the caller MUST supply a durable ledger for cross-session
   protection (documented on the class).
5. **Write-scope token acquisition (defect-corrected)** — the session exchanges
   the vault refresh token for a `Mail.ReadWrite`/`Mail.Send` access token,
   validates the granted scope exactly, and — unlike frozen Calendar V1 —
   treats the refresh-token rotation store as best-effort, so an oversized
   rotated token (the live defect found on 2026-07-24) cannot abort the send.

## Authority boundary

- Route-pinned transport: `POST /v1.0/me/messages`,
  `POST /v1.0/me/messages/{id}/send`, `GET
  /v1.0/me/mailFolders/sentitems/messages`, identity token `POST` only.
- No reply, reply-all, forward, delete, folder-move, attachment or
  shared-mailbox authority in V1; attachments are structurally excluded.
- No startup/voice/UI/dashboard wiring; frozen predecessors untouched.

## Key-management invariant

The grant binds `workspace_id` and `principal_id` cryptographically, not
against session state; the signing `integrity_key` MUST be scoped per
(workspace, principal). Cross-session, cross-restart one-shot replay protection
requires the caller to supply a durable, atomic `NonceLedgerV1`; the in-memory
default protects only within a single live session.

## Live dependency

Live execution requires the Entra app to carry delegated `Mail.ReadWrite` and
`Mail.Send` with consent, and an explicitly confirmed live send. Until then the
capability is contract-proven only.

## Rollback

Leave the flag unset; the factory returns before entry verification. The module
composes only public frozen contracts and can be deleted standalone.
