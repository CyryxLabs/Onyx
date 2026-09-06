# ADR-0007: Default-off control-plane schema v3 migration checkpoint

Status: Accepted for isolated M2b-b verification; not activated.

## Decision

Add `core/control_plane_v3.py` as an explicit, owner-capability migration around the existing schema-v2 control plane and M2b-a ledger anchor. The module is absent from startup, tools, missions, providers and UI. `ONYX_M2B_LEDGER_V3` is strict/default-off, and the production opener remains unavailable until M2b-c supplies reviewed host ownership and writers.

An exact v2 database is migrated transactionally. The six M2a domain tables are retained byte/logically as sealed `legacy_v2_*` history, while typed canonical v3 tables are created under their original names. Canonical rows, revisions, event history, head revisions, integrity commits and anchor bookkeeping are append-only: inserts are contract-validated and updates/deletes are denied. Legacy history denies insert/update/delete.

The migration re-derives typed entities, normalized claim links and relations, request state history, event sequences and revisioned projections from verified v2 chains without timestamp ordering. It then computes an exact DDL fingerprint and a type-tagged streaming root from the same locked SQLite transaction. The M2b-a anchor is prepared before SQLite commit, finalized only against a canonical read-only reopen, and recorded separately.

Integrity/intent/finalization tables are excluded from that SQLite state root to avoid circularity, but are not merely protected by SQLite triggers. Before prepare, the migration writes the exact integrity commit and anchor intent and deterministically projects the one future finalization row. A namespaced canonical SHA-256 binds table names, column names, cardinality and every type-tagged field (including IDs, timestamps and NULLs). Eight explicitly versioned 32-bit limbs of that digest are placed in the M2b-a `entity_counts` map and therefore authenticated by the external HMAC journal. The real finalization row must later equal the projection byte-for-byte; normal open never projects a missing row. An offline writer cannot change a bookkeeping timestamp, recompute all dependent IDs and restore exact DDL without diverging from the external anchor.

## Consequences and limits

- Existing v2 `WorkspaceRegistry` and `DomainLedgerRepository` writers reject user-version 3. M2b-b adds no v3 operational writer.
- A v3 database is not exposed unless its exact normalized DDL, metadata, three-row migration journal, typed mappings, root, all three exact bookkeeping rows and external anchor all agree.
- Fresh v3 uses the same empty-v2 transformation as populated migration, producing the same semantic schema.
- Crash recovery distinguishes SQLite-committed and anchor-committed states. Ambiguous, restored, tampered or raced state fails closed.
- Exact reopen validation and root/bookkeeping reconstruction scan the database and are `O(N)` in stored rows; this migration checkpoint is not an operational hot-path design.
- This module is a migration-only validator with a private, explicitly enabled test factory. It has no production opener, repository or writer API.
- Public migration boundaries normalize SQLite, host I/O and ledger-anchor failures to stable messages without path/detail leakage. `KeyboardInterrupt` and `SystemExit` propagate through the v3 boundary and the underlying anchor port/key/head read/write boundaries.
- M2b-c must redesign the canonical repository/write transaction around anchor prepare/finalize, crash recovery and bounded verification. Reusing this full-database validator on every operational write is not accepted by this ADR.
- This checkpoint does not provide process isolation from arbitrary same-user/same-process code, anchor rotation, runtime activation, dispatch authorization or UI integration. Those remain later gates.

## Rollback

Before SQLite commit, rollback restores exact v2 and reconciles a prepared anchor. After SQLite commit, schema v3 is durable and intentionally remains unexposed until deterministic anchor recovery/finalization completes. There is no destructive automatic v3-to-v2 downgrade.
