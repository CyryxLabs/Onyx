# Phase 8 Microsoft Graph Tasks V1 — Official Sources

To Do task create/read and permission pages verified against Microsoft Learn
for this candidate on 2026-07-24; throttling and refresh-token pages were
re-verified on 2026-07-23 for the accepted live-read predecessor and are
unchanged. The notification router is pure local logic with no provider
dependency.

## To Do task create and read

- [Create task](https://learn.microsoft.com/en-us/graph/api/todotasklist-post-tasks?view=graph-rest-1.0)
  defines `POST /me/todo/lists/{todoTaskListId}/tasks` with `title`,
  `importance`, optional `body` (`contentType`/`content`) and `dueDateTime`
  (`dateTime`/`timeZone`), returning `201 Created` with the task including
  `id`. Delegated permission: `Tasks.ReadWrite`.
- [Get task](https://learn.microsoft.com/en-us/graph/api/todotask-get?view=graph-rest-1.0)
  (`GET /me/todo/lists/{listId}/tasks/{taskId}`) is the reconciliation
  read-back used to verify the created title/importance.
- [List tasks](https://learn.microsoft.com/en-us/graph/api/todotasklist-list-tasks?view=graph-rest-1.0)
  documents reading a list's tasks; V1 does not enumerate lists, it targets an
  exact list id supplied by the caller.

## Permissions and least privilege

- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
  distinguishes `Tasks.Read` from `Tasks.ReadWrite`. V1 requests exactly
  `Tasks.ReadWrite`, `User.Read`, `offline_access` and validates the granted
  `Tasks.ReadWrite` scope before creating, denying if absent.

## Throttling and reliability (inherited)

- [Microsoft Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling):
  V1 never auto-retries a task create on 429; the caller reconciles and issues
  a fresh grant. Uncertain transport outcomes require reconciliation before
  any retry, per the PRD's uncertain-response rule.

## Notification routing (local design, no provider)

- The PRD (Phase 8, item on tasks/notifications) calls for routing
  notifications by urgency, quiet hours, workspace and device. V1 implements
  this as deterministic pure functions over typed items and a quiet-hours
  policy, producing deliver/defer/suppress decisions with reasons. No provider
  notification API is used; device/quiet-hours/workspace identity is caller
  policy.

## Local limitations

- The Entra registration must carry delegated `Tasks.ReadWrite` with consent;
  live task-create E2E is pending that consent plus an explicitly confirmed
  run.
- No task update, delete, complete, recurrence, list creation, reminder
  delivery transport or provider push notifications.
- The refresh-token rotation store is best-effort in-module to tolerate the
  frozen vault byte cap.
