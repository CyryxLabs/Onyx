# ADR-0013: Phase 6 V4 authenticated state and terminable process isolation

Status: Candidate — default-off, not accepted, not live

Date: 2026-07-22

## Context

Independent review rejected V3 because expired compute recovery did not use an
exact compare-and-swap fence, SQLite validation authenticated object names but
not their definitions, the frozen MissionStore API normalized caller input
lossily, and timed-out daemon workers could remain alive after their core was
discarded. V1-V3, including V3's MissionStore dependency, must remain immutable.

V4 must preserve V3's lineage accounting, deterministic materialization,
generation fencing and process-race positives without changing accepted/live
surfaces.

## Decision

### Authenticated coordination schema

V4 uses a new `.v4-coordination.sqlite3` sidecar. Its canonical signature is
generated from the declared DDL in a pristine in-memory database and includes:

- normalized `sqlite_master` SQL for every table, index and trigger;
- `PRAGMA table_xinfo`, `foreign_key_list`, `index_list` and `index_xinfo`;
- exact `user_version`, singleton metadata version, integrity check and foreign
  key check.

An existing database is authenticated before any repair or schema write. Any
same-name column, index, constraint or trigger divergence fails closed. Tests
replace same-name objects and add a same-name-table column to prove rejection.

### Expired-only CAS recovery

Each compute lease carries an unguessable token, exact deadline and monotonically
increasing generation. Recovery selects only rows whose persisted deadline is
already expired, ordered through `budget_expired_idx`, with the caller's one
global `LIMIT`. Each selected row is then cleared only if account, token,
deadline and generation still match and the deadline is still expired. Renewal
changes both deadline and generation, so a lease renewed between selection and
CAS cannot be cleared.

Terminal recovery/compaction uses the exact
`(terminal, updated_at, plan_id)` index. `EXPLAIN QUERY PLAN` tests require the
declared indexes and prohibit a temporary B-tree for both expired recovery and
terminal compaction.

### Exact mission input binding

V3's reviewed `core/missions.py` is frozen. V4 therefore introduces
`StrictMissionMaterializerV4` as the only V4 route to its additive
`MissionStore.create_idempotent()` API. Before any MissionStore write it:

- requires canonical non-empty title text of at most 240 characters;
- requires an exact step field set and rejects unknown fields;
- serializes every caller input, including field presence, allowlist order and
  budgets, to canonical JSON;
- transactionally binds the logical materialization key to both the full input
  and its SHA-256 digest in a dedicated ledger.

Exact replay converges. Any differing full input fails before another mission
write. V4 continues to use generation/owner fences immediately before and after
mission creation. Real spawned-process stale-before-create and
stale-after-create tests converge on one bound, approvable and executable
mission.

### Terminable computation and lifecycle

All planner, critic, repair planner, runner, verifier and recovery computation
admitted through V4 executes in a spawned, non-daemon child process. A deadline
overrun synchronously terminates and joins the child before returning
`BUDGET_EXHAUSTED`; no late return can commit and the next call starts a clean
process. The executor owns an explicit close sentinel, context-manager lifecycle
and best-effort destructor. `close()` joins or terminates the worker and is
idempotent.

Twelve complete create/invoke/close cycles must leave zero thread and child
process delta. The full V4 facade is also tested through plan, fenced
materialization, approval, isolated runner, isolated verifier and close.

Only returned values are authoritative. Admitted callbacks must be spawn-
pickleable and may not directly mutate host authority; provider adapters that
cannot meet that contract require an explicit provider cancellation API before
admission.

### Artifact root

V4 reuses the V2 root algorithm: exclude the manifest; encode canonical POSIX
path, NUL and lowercase SHA-256 as UTF-8; sort complete records; join with LF
and no trailing LF; SHA-256 the resulting bytes.

## Consequences

- Only exact `ONYX_PHASE6_AGENTIC_CORE_V4=true` enables explicit construction.
- Process isolation has a cold-start cost, while persistent child IPC is small;
  termination provides a real lifecycle boundary unavailable to Python threads.
- Frozen V1-V3 artifacts and live `main.py`, UI, dashboard, permission broker,
  Phase 5 and configuration remain unchanged.
- No provider, network, external coding agent or subprocess tool capability is
  activated. Multiprocessing is used only to isolate admitted computation.
- V4 remains unaccepted and not live until independent gates approve its frozen
  checkpoint.

## Rejected alternatives

- Reusing V3's poisoned daemon worker: rejected because discarded core instances
  can accumulate live threads.
- Clearing any active lease during restart: rejected because a live lease is not
  evidence of process death.
- Name-only SQLite validation: rejected because same-name definitions can change.
- Editing frozen MissionStore to repair V3: rejected because V1-V3 must remain
  byte-exact.
- Silently truncating or dropping fields before replay comparison: rejected
  because lossy normalization is not idempotency.
