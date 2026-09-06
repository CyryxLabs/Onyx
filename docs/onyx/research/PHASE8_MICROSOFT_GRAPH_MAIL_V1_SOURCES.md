# Phase 8 Microsoft Graph Mail V1 — Official Sources

Send/draft and permission pages verified against Microsoft Learn for this
candidate on 2026-07-24; throttling and refresh-token pages were re-verified on
2026-07-23 for the accepted live-read predecessor and are unchanged.

## Draft creation and send

- [Create Message](https://learn.microsoft.com/en-us/graph/api/user-post-messages?view=graph-rest-1.0)
  defines `POST /me/messages` to create a draft with `subject`, `body`
  (`contentType`/`content`), `toRecipients` and `ccRecipients`
  (`emailAddress.address`), returning `201 Created` with the message including
  `id` and the server-assigned `internetMessageId`. Delegated permission:
  `Mail.ReadWrite`.
- [Send message (send draft)](https://learn.microsoft.com/en-us/graph/api/message-send?view=graph-rest-1.0)
  defines `POST /me/messages/{id}/send`, returning `202 Accepted` with no body.
  Delegated permission: `Mail.Send`. This two-step create-then-send flow is
  chosen over `POST /me/sendMail` because it yields an `internetMessageId`
  before the send, making the outcome reconcilable against Sent Items.
- [List messages in a mail folder](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0)
  supports `GET /me/mailFolders/sentitems/messages?$filter=internetMessageId eq '…'`,
  the reconciliation query. Delegated permission: `Mail.Read`.

## Permissions and least privilege

- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
  distinguishes `Mail.Read` from `Mail.ReadWrite` and `Mail.Send`. V1 requests
  exactly `Mail.ReadWrite`, `Mail.Send`, `User.Read`, `offline_access` and
  validates the granted `Mail.Send` scope before sending, denying if absent.

## Throttling and reliability (inherited)

- [Microsoft Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling):
  V1 never auto-retries a send on 429 — duplicate-delivery risk outweighs
  retry convenience; the caller must reconcile Sent Items and issue a fresh
  grant. Uncertain transport outcomes require Sent Items reconciliation before
  any resend, per the PRD's uncertain-response rule.

## Local limitations

- The Entra registration must carry delegated `Mail.ReadWrite` and `Mail.Send`
  with consent; live send E2E is pending that consent plus an explicitly
  confirmed run.
- V1 sends plain-text bodies to an exact audience only; no attachments, reply,
  reply-all, forward, delete, folder move or shared-mailbox support.
- The refresh-token rotation store is best-effort in-module to tolerate the
  frozen vault's byte cap (the live defect found in Calendar V1).
