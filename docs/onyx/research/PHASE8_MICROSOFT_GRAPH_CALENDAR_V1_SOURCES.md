# Phase 8 Microsoft Graph Calendar V1 — Official Sources

Event-creation and permission pages verified against Microsoft Learn for this
candidate on 2026-07-24; throttling and refresh-token pages were re-verified
on 2026-07-23 for the accepted Live Read E2E predecessor and are unchanged.

## Event creation

- [Create event](https://learn.microsoft.com/en-us/graph/api/user-post-events?view=graph-rest-1.0)
  defines `POST /me/events` with `subject`, `start`/`end`
  (`dateTime` + `timeZone`), `location.displayName` and `body`
  (`contentType`/`content`), returning `201 Created` with the event object
  including `id` and `webLink`. Delegated permission: `Calendars.ReadWrite`.
- [Get event](https://learn.microsoft.com/en-us/graph/api/event-get?view=graph-rest-1.0)
  (`GET /me/events/{id}`) is the reconciliation read-back used to verify the
  created subject/start/end.
- Events created without `attendees` produce no invitation; adding attendees
  triggers meeting-request sends, which is why V1 structurally denies
  attendee drafts.

## Permissions and incremental consent

- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
  distinguishes `Calendars.Read` from `Calendars.ReadWrite`.
- [Refresh tokens](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)
  and the v2.0 token semantics allow a refresh-token grant to request any
  scope the client has consent for; V1 exchanges the stored refresh token for
  a `Calendars.ReadWrite` access token and validates the granted scope
  exactly, denying the mutation when the write scope is absent (e.g. consent
  not yet granted).

## Throttling and reliability (inherited)

- [Microsoft Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling):
  V1 never auto-retries a mutation on 429 — duplicate-creation risk outweighs
  retry convenience; the caller receives a typed error and must issue a fresh
  grant. Uncertain transport outcomes require provider-state reconciliation
  before any retry, per the PRD's uncertain-response rule.

## Local limitations

- The Entra registration does not yet carry `Calendars.ReadWrite`; live
  mutation E2E is pending that consent plus an explicitly confirmed run.
- Availability computation is UTC-only in V1 and treats event times from the
  accepted read contract; non-UTC calendars require a later successor.
- No recurring-event, update, delete, invitation or shared-calendar support.
