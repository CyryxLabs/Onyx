# Phase 8 Microsoft Graph Read V1 — Official Sources

Verified against Microsoft Learn on 2026-07-23.

## Calendar

- [List calendarView](https://learn.microsoft.com/en-us/graph/api/user-list-calendarview?view=graph-rest-1.0)
  defines the bounded time-window route used by the adapter:
  `GET /me/calendarView?startDateTime=...&endDateTime=...`.
- The least delegated permission is `Calendars.ReadBasic`; `Calendars.Read`
  and `Calendars.ReadWrite` are higher-privilege alternatives.

## Mail

- [List messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0)
  defines `GET /me/messages`, `$select`, `$top` and provider-owned
  `@odata.nextLink` paging. The adapter caps results and accepts next links
  only for the exact original v1.0 route and Graph origin.
- [Get message](https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0)
  defines `GET /me/messages/{id}`. `Mail.ReadBasic` cannot expose the message
  body, so the adapter requires `Mail.Read` or `Mail.ReadWrite` before a body
  read.
- [Use the `$search` query parameter](https://learn.microsoft.com/en-us/graph/search-query-parameter)
  defines message-collection search and the quoted search expression. The
  adapter rejects quotes, backslashes and control characters in owner-supplied
  search text before wrapping the value.

## Permission boundary

- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
  distinguishes read-basic, read and read-write delegated permissions. V1 has
  no write transport method and never treats a read-write token as mutation
  authority.

## Local contract decisions

- Only global Microsoft Graph `https://graph.microsoft.com/v1.0/` routes are
  accepted in this first provider proof.
- Responses and message bodies are untrusted provider data.
- Page count is capped at five and normalized item count at 250.
- The account, workspace, principal, scopes, rotation deadline and revocation
  state are re-attested before and after provider reads.
- Calendar and email drafts are local immutable values with
  `mutation_authority=false`; no provider draft, create, send, update or delete
  route exists in V1.
