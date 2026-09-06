# Phase 5.2 Approval Inbox V11 checkpoint

Status: **candidate — default-off, read-only, external acceptance pending**

V11 is a clean-room review projection. It preserves V1-V10 as rejected historical
candidates and does not import them, Session Grants or Capability Nexus. The
host owns a bootstrap-only `ONYX_APPROVAL_INBOX_V11` gate, flag epoch, exact
source and monotonic clock. No live/startup/UI/dashboard path imports V11.

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
same-epoch equivocation invalidates cached state. The source integrity high-water
retains exactly one current epoch digest: accepting a newer epoch atomically
replaces the prior digest, while same-current equivocation and every older-epoch
rollback still latch. A deterministic 10,000-epoch test proves the integrity
state, snapshot cache and view cache remain constant-cardinality. Exact snapshot reuse preserves
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

- Focused: 61 passed in 10.253s.
- Combined Approval Inbox V1-V11: 652 passed in 43.192s.
- Frozen V2-V7 R11 fixtures resolve exactly two mutable documentation paths
  directly from exact V9 content-addressed snapshots bound as V11 artifacts.
  The plugin never reads those live paths and never edits predecessors or live
  documentation. R11 root/acceptance inputs and its extra workflow are also
  direct V11 authorities with fixed digests.
- Relevant regressions: 172 passed plus 265 subtests in 14.120s.
- Static gates: compile, Ruff lint/format, whitespace and scoped diff check passed in 0.490s.
- Live reachability scan: 26 files, no V11 flag/module reference.
- Parent, worker and historical plugin authoritative paths reject noncanonical
  spelling, case aliases, containment escapes and root/ancestor/final symlink,
  junction or reparse components before each read, hash or process launch.
  Historical copies use fresh plugin-owned temporary roots, exclusive
  nonpreexisting regular-file targets and verified cleanup; live cardinality is
  fixed at 26.
- Mutable matrix/evidence inputs are represented only by exact content-addressed snapshots and an exact mapping; live projection paths are excluded from the artifact manifest.

V11 remains unaccepted and default-off until three independent external reviews
pass. This checkpoint grants no Phase 5 exit or live activation.
