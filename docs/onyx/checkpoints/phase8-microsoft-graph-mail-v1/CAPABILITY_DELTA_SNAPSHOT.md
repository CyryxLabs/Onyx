# Capability delta — Phase 8 Microsoft Graph Mail V1

## Added behind one exact default-off flag

- HMAC-signed, expiring, one-shot `MailSendGrantV1` bound to the exact frozen
  email-draft digest and a canonical order-independent recipient/cc audience
  key; the send path recomputes the draft content digest, so a send cannot
  reach an unapproved audience or carry substituted subject/body.
- Durable one-shot enforcement via an injected `NonceLedgerV1` consumed before
  any provider mutation; with a durable ledger a captured grant cannot be
  replayed by a fresh session to deliver a duplicate mail.
- Reply drafts and non-email recipient addresses denied.
- Route-pinned mail transport: create draft (`POST /me/messages`), send
  (`POST /me/messages/{id}/send`), Sent Items reconciliation
  (`GET /me/mailFolders/sentitems/messages`), identity token `POST`.
- Write-scope (`Mail.ReadWrite`/`Mail.Send`) access-token acquisition with
  exact granted-scope validation and best-effort refresh-token rotation
  (fixes the Calendar V1 oversized-token live defect in-module).
- Reconcilable two-step send capturing the provider `internetMessageId`; typed
  receipt with read-back Sent Items reconciliation and honest
  `reconciled=false`.
- Uncertain-outcome contract: consumed grant, typed `Uncertain` error, and
  Sent Items reconciliation before any resend; no send auto-retry on 429.

## Not added

- Live send E2E (requires `Mail.ReadWrite` + `Mail.Send` consent on the Entra
  app and an explicitly confirmed run).
- Attachments, reply, reply-all, forward, delete, folder move, shared mailbox.
- Calendar mutation beyond the accepted Calendar V1, tasks, notifications,
  Drive/OneDrive/Office.
- Startup, V13, voice, dashboard or UI wiring.
- Phase 8 aggregate exit or full PRD completion.
