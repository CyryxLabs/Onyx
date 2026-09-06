# Phase 10 Editorial Calendar V1 — E6 acceptance

- Evidence ID: `VE-P10-EDITORIAL-CALENDAR-V1-E6-001`
- Decision date: `2026-07-25`
- Decision: **ACCEPTED — default-off editorial calendar + approval-ledger contract**
- Candidate manifest: `4b2fcce6cab138dbc788e7f5ba16214adf894b6cf37566229ffc91b3f8de683a`
- Artifact root: `415bbc4de20811c3d7caac47dacb8a01cf50a4ed1660f9670ee5278136411939`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0`. This is the second Phase 10
slice: a default-off, deterministic, hermetic editorial-calendar and
approval-ledger contract, entry-bound to the accepted Phase 10 brand passport
(`6f218e78…`). It plans posts against caller-vouched authorized accounts, with a
fixed `draft -> pending_approval -> approved -> scheduled` lifecycle in which
`published` is not a representable status and no publish method exists; reaching
`approved` or `scheduled` requires an explicit positive approval record (the
first-publish-per-account approval gate); every post carries a unique idempotency
key and an injected-clock future schedule; and `is_ready_to_publish` is a
readiness predicate only. The module calls no model, opens no network, spawns no
process, persists nothing and takes no action. The gate reproduced **538 passed
tests and 80 passed subtests, 0 failed and 0 errors** across twenty-five fresh
Python processes; eight skips are inherited, documented platform-specific Phase 7
contracts.

The three independent reviews ran adversarially. Integrity returned PASS: the
artifact root `415bbc4d` and all eight candidate artifacts recompute exactly, the
accepted brand-passport entry-bind is genuine, and no predecessor was modified.
Functional returned PASS: the approval gate is enforced (an `approved`/`scheduled`
post without a positive approval is rejected), `published` is structurally
unrepresentable, and the reviewer's one design question — that a post may reach
`scheduled` without a disclosure flag — was considered and kept: disclosure is a
publish-*readiness* requirement enforced by `is_ready_to_publish`, which the later
publish slice must consult, not a scheduling requirement. Quality returned PASS:
the module mirrors the accepted Phase 10 brand-passport idioms (sealed factory,
entry-bind, frozen dataclasses, byte-bounded text contract, injected clock), and
the verifier machine-checks the source invariants, forbids network/process/
publish authority tokens, asserts `published` is not a status, and reproduces the
twenty-five-file cumulative gate with a per-file sum check.

Scope is deliberately **planning and approval only**. No live provider
connection, publishing, analytics or audience data is bound or claimed. The first
real publish per account remains a later owner-approved, access-gated slice
(`BLOCKED_BY_ACCESS` until OAuth/app-review plus a test account). This acceptance
live-wires no component, adds no action authority, and does not claim the full
Onyx PRD complete.
