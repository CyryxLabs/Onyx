# ADR-0008: Default-off operational schema-v3 domain repository

Status: Accepted for isolated M2b-c verification; not activated.

Journal lifecycle and complete-witnessing note: ADR-0009 supersedes this
record's original flat-witness design and its statement that authenticated
rotation was unavailable. The activation and privilege-boundary limits below
remain unchanged. Historical evidence `VE-M2B-C-001` is not rebound.

## Decision

Add `core/domain_ledger_v3.py` as the owner-sealed operational repository over
the canonical schema-v3 database created by ADR-0007. It preserves the exact
public M2a repository surface and dataclass contract. Construction remains
available only through an explicitly enabled private test host; startup,
missions, permissions, providers, tools, dashboard and UI do not import or
instantiate it.

Each non-idempotent mutation appends immutable canonical rows, one event, one
bounded operational commit and an anchor intent. One writer session holds the
in-process and OS anchor locks across baseline verification, SQLite
`BEGIN IMMEDIATE`, candidate preparation, durable SQLite commit, anchor
finalization, exact finalization-row publication and committed verification.
Exact replay returns the existing record without a commit. A prepared
transition is recovered deterministically at every crash seam.

Operational commits form a sequence-numbered predecessor chain rooted at the
immutable migration commit. Each commit binds the exact table, row identity and
type-tagged row digest of its bounded delta. The external anchor authenticates
the latest state root, event/row counts and operational bookkeeping digest.
Targeted reads validate the exact entity row witness (or exact immutable v2
prefix mapping) and its causal event/state relationships. Whole-ledger
`verify_integrity()` remains an explicit cold `O(N)` audit.

Snapshot candidate and projected-finalization overrides are thread-local.
Contending writers therefore serialize without clearing or observing another
writer's candidate. Lock acquisition is bounded; timeout fails closed without
publishing partial rows. The maximum wait is a ceiling, not an availability
promise.

## Consequences and limits

- The legacy v2 prefix remains immutable and readable with M2a-equivalent
  records, ordering, errors and replay/conflict behavior. M2a's request update
  may be slightly later than its receipt event; the exact legacy record and the
  independently verified event/state chain are both preserved without forcing
  timestamp equality that v2 never guaranteed.
- Normal writes use the incremental operational chain. Tests forbid the cold
  migration validator and full streaming root on the post-baseline hot path.
- Database rollback, operational suffix truncation, row-plus-witness rewrite
  and an internally self-consistent root rewrite fail against the external
  anchor or the cold chain audit.
- This repository records shadow observations only. It does not authorize,
  dispatch, retry, transition missions, call providers or bypass the existing
  permission broker.
- `ONYX_M2B_LEDGER_V3` remains strict/default-off. Production ownership and
  runtime wiring remain deliberately unavailable; this ADR does not activate
  Onyx or claim same-user/process isolation, hardware trust or release
  readiness. Authenticated checkpoint/rotation is accepted separately by
  ADR-0009 and does not change those limits.

## Rollback

Before SQLite commit, the transaction and prepared anchor roll back to the
verified baseline. After SQLite commit, recovery promotes the matching prepared
anchor and publishes the exact deterministic finalization. A database restored
to an older valid prefix is not accepted because its root/sequence diverges
from the external anchor. No destructive automatic v3-to-v2 downgrade exists.
