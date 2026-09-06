# Phase 10 Editorial Calendar V1 — sources and design basis

Hermetic, deterministic planning contract. No external service is used, so the
basis is the governing PRD text and the approval/idempotency principles it
requires — not network APIs.

## PRD basis

- `plans/onyx-advanced-entity-redesign.md` Phase 10 item 2: evidence-backed
  strategy, funnel/KPI tree, editorial calendar and experiment ledger. This
  slice delivers the editorial calendar with its approval ledger.
- Phase 10 verification: the first publish per account is explicitly approved;
  later publishes require an approved calendar/policy window, idempotency and a
  verified platform post ID.

## Design decisions

- **Plan and approve, never publish.** The status lifecycle is
  `draft -> pending_approval -> approved -> scheduled`. `published` is not a
  representable value; publishing is a later owner-approved, access-gated slice.
  `is_ready_to_publish` is a readiness predicate only.
- **Approval gate is structural.** Reaching `approved` or `scheduled` requires an
  explicit approval record with `approved=True`, encoding the PRD's
  first-publish-per-account approval rule. A scheduled post without a positive
  approval is rejected at build.
- **Idempotency.** Every planned post carries a unique idempotency key, so the
  same intended post cannot be double-scheduled — the precondition for the later
  publish slice to be safely idempotent.
- **Authorized targets only.** A post can target only an account the caller has
  already vouched for as authorized (derived from the accepted Phase 10
  brand-passport inventory's `is_usable`); unknown accounts are rejected.
- **Deterministic time.** `now_utc` is injected, never read from a clock, so the
  contract is reproducible; a post must be scheduled strictly in the future.
- **Entry-bound to the accepted brand passport slice.** Construction is denied
  unless the four-file Phase 10 brand-passport acceptance tuple is byte-exact.
