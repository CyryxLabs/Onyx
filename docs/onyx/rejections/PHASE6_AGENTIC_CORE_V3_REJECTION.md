# Phase 6 Agentic Core V3 rejection record

Status: **REJECTED — preserved byte-for-byte; never accepted or activated**

Date: 2026-07-22

The independent gate rejected V3. Its core, tests, MissionStore dependency,
ADR, checkpoint and manifest remain frozen exactly as reviewed. This additive
record is not part of the V3 artifact root.

## Blocking findings

1. `recover_compute()` selected every active account instead of only expired
   deadlines, and cleared leases without an exact token/deadline/generation
   compare-and-swap. A living or renewed lease could therefore be reclaimed.
2. Coordination validation authenticated only object names and version, not the
   canonical SQLite schema. Same-name column, index, constraint or trigger
   changes were not proven to fail closed before use.
3. The frozen MissionStore idempotency API truncated titles before comparison
   and tolerated mapping fields outside the expected step contract, allowing
   distinct caller inputs to converge after lossy normalization.
4. A timed-out call permanently occupied V3's single daemon thread. Creating
   and discarding multiple core instances could still accumulate poisoned
   workers, and there was no explicit close/join lifecycle.
5. Recovery/compaction query plans were not proven against the exact requested
   terminal index and global-limit semantics.

## Disposition

- V3 remains strict default-off and must not be wired live.
- Its lineage charging, deterministic materialization identity, generation
  fencing, real two-process race tests and bounded recovery direction remain
  useful evidence.
- Corrections are additive in V4 and require new independent functional,
  integrity and quality gates before activation.
