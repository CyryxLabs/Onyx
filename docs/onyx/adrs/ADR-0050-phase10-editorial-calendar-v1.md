# ADR-0050 — Phase 10 editorial calendar and approval ledger V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

Phase 10 item 2 of the Onyx PRD calls for an editorial calendar and experiment
ledger with an explicit approval discipline: the first publish per account is
approved, and later publishes require an approved window, idempotency and a
verified post ID. The first Phase 10 slice established the authorized-account
inventory (`VE-P10-BRAND-PASSPORT-V1-E6-001`). This ADR records the second slice:
the editorial calendar and approval ledger over those authorized accounts, still
with no publishing authority.

## Decision

Add `core/phase10_editorial_calendar_v1.py`, a default-off
(`ONYX_PHASE10_EDITORIAL_CALENDAR_V1`), deterministic, hermetic planner
entry-bound to the accepted brand-passport four-file acceptance tuple.

Structural properties:

1. **No publishing.** The status lifecycle is
   `draft -> pending_approval -> approved -> scheduled`. `published` is not a
   representable status, and the class exposes no publish method. Publishing is a
   later owner-approved, access-gated slice.
2. **Approval gate.** A post in `approved` or `scheduled` status must carry an
   explicit approval record with `approved=True`; otherwise the build is
   rejected. This encodes the PRD first-publish-per-account approval rule.
3. **Idempotency and authorized targets.** Every post carries a unique
   idempotency key, and may target only an account the caller vouched for as
   authorized (derived from the accepted brand-passport inventory).
4. **Deterministic time.** `now_utc` is injected; a post must be scheduled
   strictly in the future. `is_ready_to_publish` is a readiness predicate only
   (scheduled + approved + disclosure + future) and never acts.

The module calls no model, opens no network, spawns no process, persists nothing
and takes no action.

## Consequences

- Onyx can plan and approval-gate an editorial calendar against authorized
  accounts, producing the idempotent, approved, scheduled records a later publish
  slice will consume — without any ability to publish here.
- The slice claims no live provider connection, no publishing, no analytics and
  no audience data; it enables no autonomous social behaviour.
- Any regression in the lifecycle, the approval gate, the entry-bind or the
  cumulative gate fails the slice verifier.

## Alternatives considered

- Modelling `published` as a status with a disabled publish path: rejected —
  publishing must be structurally unrepresentable at this layer, returning only
  as a separately accepted, access-gated slice.
- Reading the wall clock for "now": rejected — it would make the contract
  non-deterministic and unreproducible; the clock is injected instead.
- Deriving authorized accounts by importing the brand registry at runtime:
  rejected for this slice — the calendar takes a caller-vouched allow-set, keeping
  it hermetic and independently testable; binding the two registries is a later
  composition concern.
