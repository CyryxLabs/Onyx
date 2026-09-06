# Phase 5.2 Approval Inbox V15 checkpoint

Status: **candidate — default-off, read-only, external acceptance pending**

V15 is a clean-room review projection. It preserves V1-V14 as rejected historical
candidates and does not import their core implementation, Session Grants or
Capability Nexus. The
host owns a bootstrap-only `ONYX_APPROVAL_INBOX_V15` gate, flag epoch, exact
source and monotonic clock. No live/startup/UI/dashboard path imports V15.

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

- Focused: 130 passed in 45.294s.
- Combined Approval Inbox V1-V15: 1032 passed in 182.326s.
- Frozen V2-V7 R11 fixtures resolve exactly two mutable documentation paths
  directly from exact V9 content-addressed snapshots bound as V15 artifacts.
  The plugin never reads those live paths and never edits predecessors or live
  documentation. R11 root/acceptance inputs and its extra workflow are also
  direct V15 authorities with fixed digests.
- Relevant regressions: 172 passed plus 265 subtests in 41.409s.
- Static gates: deterministic in-memory compile, AST parse and whitespace checks
  passed in 0.257s. Ruff and py_compile are deliberately not
  imported or executed from the live environment.
- Live reachability scan: 26 files, no V15 flag/module reference.
- Parent, worker and historical plugin authoritative paths reject noncanonical
  spelling, case aliases, containment escapes and root/ancestor/final symlink,
  junction or reparse components before each read, hash or process launch.
  Historical copies use fresh plugin-owned temporary roots, exclusive
  nonpreexisting regular-file targets and verified cleanup; live cardinality is
  fixed at 26.
- Historical Git checks use a private minimal metadata tree containing only the
  frozen R11 HEAD. The live `.git`, hooks, config, alternates and object database
  are never consumed. The combined child runs under one process-tree deadline,
  Python `-I -S -B`, a sanitized environment and an exclusive clean materialized
  root with pytest autoload, conftest and ambient configuration prohibited.
- Every workspace source, test, helper, package initializer and data authority
  used by the three suites is copied from a bundle hash into that clean root.
  Third-party application dependencies are a separately enumerated file-level
  host TCB and are copied into a private dependency tree; site-packages, `.pth`,
  user-site, cwd and script-directory are never import authority. Loaded module
  origins are audited after each run.
- The parent deadline is 900 seconds and the three child suites share a
  600-second post-materialization process-tree deadline. Timeout still fails
  closed and terminates descendants; dependency copying is outside that child
  execution budget.
- The combined plugin and all six V2-V7 verifier modules execute from exact
  re-gated, digest-bound source bytes under private names. Conventional
  `sys.modules`, dotted import hooks and preloaded modules are not authority.
- Mutable matrix/evidence inputs are represented only by exact content-addressed snapshots and an exact mapping; live projection paths are excluded from the artifact manifest.

## Explicit limitations

- File identity/hash checks are non-atomic and require a stable, nonconcurrently
  mutated authoritative workspace during verification; they are not an
  operating-system handle-based TOCTOU boundary.
- The live reachability result covers exactly `main.py`, `ui.py`,
  `scripts/launch_onyx.pyw`, and current top-level `actions/*.py` and
  `dashboard/*.py` files (26 paths). It is not a proof about
  unscanned extensions, non-Python launchers or future files.
- The digest-bound ZIP closes pytest, its protected import namespaces and direct
  runtime dependencies. Application dependencies are not claimed hermetic:
  their exact host files are the declared TCB, revalidated and copied before
  each verifier run. The Python executable, exact validated stdlib import
  directories/ZIPs and loaded OS DLLs are also a declared host TCB; the generic
  `sys.base_prefix` root is excluded from child import authority. V15 does not
  claim a hermetic Python distribution.
- Internal Git compatibility implements only the frozen V13/V15 HEAD identity,
  fixed version identity and deterministic whitespace check needed by the
  historical suites. It does not certify or expose a general Git repository.

V15 remains unaccepted and default-off until three independent external reviews
pass. This checkpoint grants no Phase 5 exit or live activation.
