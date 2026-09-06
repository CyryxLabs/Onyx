# Capability delta — Phase 10 editorial calendar V1

| Field | Before | After |
| --- | --- | --- |
| Editorial calendar / approval ledger | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (contract, default-off) |
| Evidence | — | `VE-P10-EDITORIAL-CALENDAR-V1-E6-001` |
| Authority added | — | None — plan + approve only; no publish method, `published` unrepresentable |
| Publishing | `BLOCKED_BY_ACCESS` | `BLOCKED_BY_ACCESS` (unchanged; later gated slice) |

**What changed.** Onyx can plan an approval-gated editorial calendar against
authorized brand accounts: idempotent, future-scheduled posts whose `approved`
and `scheduled` states require an explicit positive approval record, ready to be
consumed by a later publish slice.

**What did not change.** No live provider connection, no publishing, no
analytics, no audience data. The first real publish per account remains
`BLOCKED_BY_ACCESS` until an OAuth/app-review + test-account slice is separately
built and accepted. This delta adds no runtime wiring and no action authority.
