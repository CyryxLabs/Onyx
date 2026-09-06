# Phase 5.2 Approval Inbox V9 checkpoint

Status: **candidate — default-off, read-only, external acceptance pending**

V9 is a clean-room review projection. It preserves V1-V8 as rejected historical
candidates and does not import them, Session Grants or Capability Nexus. The
host owns a bootstrap-only `ONYX_APPROVAL_INBOX_V9` gate, flag epoch, exact
source and monotonic clock. No live/startup/UI/dashboard path imports V9.

Every return from a host epoch callback re-enters the gate lock and gives an
already-terminal revocation precedence over the callback value. Page,
continuation, preview and handoff publication hold the gate and projection
locks through their linearization point, then recheck terminal state, exact
source generation/epoch and current snapshot/view membership. A newer source
commit therefore cannot be followed by stale output or stale cache
repopulation from an older concurrent capture.

## Authority boundary

Every page, review item, calm-batch preview and handoff states
`authority_granted=False`, `approval_action_available=False` and
`execution_available=False`. There is no approve, deny, approval-revoke, grant,
dispatch, execute or persistence surface. A handoff contains review identifiers
only and instructs a future approval service to re-resolve every host action
field immediately before any authorization decision.

## Validity and batching

The terminal machine is `DISABLED -> READY -> STALE | REVOKED |
INTEGRITY_LATCHED`. A changed feature epoch, clock rollback, source rollback or
same-epoch equivocation invalidates cached state. Exact snapshot reuse preserves
its original local creation/deadline and returned proofs, so refresh never
extends TTL. Source callbacks are bounded single-flight and execute outside the
projection lock.

Pagination tokens bind snapshot, view/query/filter/sort, page size, offset,
ordered item set and fixed deadline. Review proofs bind the complete action and
context fingerprint plus safe human-review fields. Calm batches require exact
returned `(item_id, review_proof)` pairs; selection order is canonicalized.
Duplicate item IDs, action request IDs, action fingerprints and idempotency
identities fail closed. High, critical, always-explicit or otherwise ineligible
items cannot enter a batch.

## Stored evidence

- Focused: 46 passed in 1.081s.
- Combined Approval Inbox V1-V9: 542 passed in 28.975s.
- Relevant regressions: 172 passed plus 265 subtests in 26.489s.
- Static gates: compile, Ruff lint/format, whitespace and scoped diff check passed in 0.551s.
- Live reachability scan: 26 files, no V9 flag/module reference.
- Parent and worker authoritative paths reject noncanonical spelling, case aliases, containment escapes and root/ancestor/final symlink, junction or reparse components before each read, hash or process launch; live cardinality is fixed at 26.
- Mutable matrix/evidence inputs are represented only by exact content-addressed snapshots and an exact mapping; live projection paths are excluded from the artifact manifest.

V9 remains unaccepted and default-off until three independent external reviews
pass. This checkpoint grants no Phase 5 exit or live activation.
