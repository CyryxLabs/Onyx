# ADR-0002: Use workspace and evidence sidecars around existing stores

- Status: Implemented fixture-only/default-off; pending activation review
- Date: 2026-07-14
- Decision owners: Cyryx Labs / Onyx owner

## Context

`core/missions.py` schema v3 and `memory/store.py` schema v1 are working local SQLite stores but do not contain the full workspace, evidence, claim, action receipt, autonomy, connector or layered-memory semantics required by the master plan. Adding all fields directly would create high-risk migrations and couple the stable worker/search paths to unfinished domains. A second mission or memory engine would split authority.

## Decision

Create one local `runtime/control_plane.sqlite3` sidecar owned by a control-plane repository/service. It stores:

- workspace registry/policies and credential/browser/artifact aliases;
- one-to-one mission context keyed by existing mission ID;
- typed/versioned evidence, claims, action requests/receipts and event envelopes;
- grants and autonomy envelopes;
- capability/operator descriptors and health projections;
- memory metadata, source, supersession and contradiction links keyed to existing memory IDs or artifact hashes;
- migration/export/delete journals.

Existing mission rows remain execution truth; existing memory rows remain the compatibility content store; existing tool audit remains the authorization/action audit. The sidecar references their IDs and verified hashes but does not duplicate their authority. Cross-database references are validated in application services because SQLite cannot enforce foreign keys across files.

Artifacts are content-addressed under a workspace root. Their canonical relative path is exactly `<first-two-lowercase-sha256>/<lowercase-sha256>`: the digest is normalized/validated as 64 lowercase hexadecimal characters and the prefix must equal its first two characters before root joining. Secrets remain in the OS vault and sidecars contain aliases only.

## Schema rules

- Every domain row has `schema_version`, stable ID, `workspace_id`, timestamps and lifecycle status.
- External actions have unique idempotency keys and immutable normalized payload hashes.
- Evidence/claim/action provenance is append-only; corrections use supersession/contradiction links.
- Grants/envelopes are immutable; revocation is a separate append-only record.
- No sensitive payload, token, cookie, payment/passport number or private key is stored.
- Missing, unknown, inactive or malformed workspace/context fails closed for every enhanced/new call. Only a versioned legacy adapter may select `legacy-default`, and only when it receives a trusted host-owned legacy-caller marker that user/model/document/connector/remote payloads cannot set.

## Why one sidecar database

It isolates experimental domain migrations from working mission/memory schemas while retaining transactional integrity among new control-plane records. Multiple domain databases would complicate policy checks and recovery. One sidecar is not a second engine: it cannot claim/execute missions or authorize/dispatch actions.

## Migration

1. **M1a:** create only schema metadata, empty tables/indexes and the migration journal transactionally. Create no workspace/domain row or `legacy-default`; do not inspect or backfill mission/memory context.
2. Stop for review and prove deterministic schema, flags-off equivalence and rollback. Starting implementation or creating M1a is not activation; activation means enabling the Phase 4 feature flag for runtime use and satisfying the Phase 4 exit gate.
3. **M1b:** only after M1a review acceptance, create `WorkspaceRegistry` and the `legacy-default` compatibility row through the explicit versioned `LegacyWorkspaceAdapter`, then backfill verified mission/memory context references idempotently from current IDs/hashes. Ambiguous assignments remain explicitly pending review; no generic fallback assigns them.
4. Dual-read in shadow mode and prove legacy API equivalence through the explicit versioned legacy adapter/trusted caller marker; enhanced calls missing workspace fail closed.
5. Enable workspace-aware adapters for new explicitly scoped records only after Phase 4 exit evidence is accepted.
6. Migrate legacy assignments only after explicit owner review.

No existing database, credential or legacy source is deleted. A completed migration records source identity/hash, version, counts and read-back verification.

### M1b implementation checkpoint (not activation)

The current development tree contains a default-off M1b checkpoint around the inert sidecar. Control-plane schema v2 adds a transactional backfill run ledger, lease owner/expiry/heartbeat with a fencing epoch, reviewed-candidate staging, and a canonical digest over the verified run's complete auditable row plus result payload. `WorkspaceRegistry` requires an explicit active workspace for enhanced calls; generic lookup cannot select `legacy-default`. Only the host-bound `LegacyWorkspaceAdapter` can create or resolve that compatibility workspace.

The opt-in reader snapshots the fixed host-owned mission/memory source family without invoking either legacy store, validates supported schema and logical identities, stages safe completed mission references, and leaves live/unverifiable missions and ambiguous memory candidates `pending_review`. A run becomes `verified` only after a separate read-only integrity, foreign-key, count and hash read-back. Verified replay also recomputes the sealed run-row/result digest and all semantic invariants, so source, lease, timestamp, count, payload or graph tampering fails closed. Incomplete, changed, divergent or failed runs cannot authorize enhanced references. Snapshot-root creation is cross-process coordinated and an existing root is validated rather than re-hardened.

This checkpoint does not alter startup, activate shadow dual-read, migrate owner data, or satisfy the Phase 4 exit gate. Both workspace and backfill flags remain off by default, and the canonical Windows control-plane path remains subject to the separately recorded M1a platform gate.

### M2a shadow repository checkpoint (not an operational ledger)

The development tree contains a separate default-off `core/domain_ledger.py` repository over the evidence, claim, action-request, action-receipt, event and projection tables already present in physical schema v2. It is bound to one explicit active non-legacy workspace, stores only canonical bounded redacted metadata and type-framed hashes, and emits entity plus event-envelope plus mutable projection-head updates atomically. Claims use immutable revisions; relations require exact workspace and mission scope. Requests are dry-run shadows only. Unknown or partial observations require append-only reconciliation and cannot trigger retry or mission success.

M2a does not import or modify startup, `MissionStore`, `permission_broker`, `tool_audit`, dispatch, providers or UI. It adds no physical migration and no migration-journal row. Application-level validation and the projection head detect isolated drift and ordinary loss, but a principal able to rewrite SQLite coherently can delete a valid chain suffix and replace the mutable head. Consequently M2a is fixture-only shadow infrastructure and must not be activated or described as authoritative. A separately reviewed M2b schema-v3 migration with database-enforced append-only records and a protected chain anchor is mandatory before any operational integration.

### M2b-a native anchor infrastructure checkpoint (not schema v3 or activation)

`ADR-0006` records a separate default-off host anchor and native-vault primitive.
It adds no table, trigger, migration-journal row, startup import or runtime call.
The canonical production database port intentionally remains unavailable. Its
tests exercise an isolated capability-guarded HMAC journal/head state machine,
including pending-first bootstrap recovery and fail-closed divergence handling.

This checkpoint does not cure schema v2's coherent-rewrite limitation and is
not an operational ledger. The native vault is scoped to the OS user, not an
independent hardware or privilege boundary: arbitrary code in the same Python
process can monkeypatch the runtime, and another process under the same OS user
can ultimately access that user's vault. Schema v3/database-enforced
immutability and all integration remain separate M2b-b review gates.

## Rollback

Disable `control_plane_v1` and workspace-aware adapter flags. The existing stores and APIs continue normally. Preserve the sidecar for diagnosis/export; deletion requires a separate verified owner-approved cleanup. Never write vault secrets to JSON or flatten workspace records back into global memory.

## Failure behavior

- Sidecar unavailable/corrupt: enhanced workspace/grant/connector mutations stop; legacy operations may continue only where they do not depend on enhanced semantics.
- Missing referenced core record: quarantine sidecar row and surface a repair finding.
- Unknown schema/policy version: deny enhanced operation.
- External outcome unknown: retain receipt and move mission to reconciliation/waiting; never retry blindly.

## Verification

- Fixture migration for mission schemas v1/v2/v3 and memory v1 is idempotent and non-destructive.
- Core database hashes/record values are unchanged by sidecar backfill.
- Pairwise workspace tests yield zero unauthorized records across memory, artifacts, aliases, profiles, missions and grants.
- Filters run before lexical/vector/graph ranking.
- Sidecar corruption/dropout cannot grant access or alter mission state.
- Export/delete jobs enumerate all stores and residuals.
- Flags-off rollback passes the full current suite without data restoration.

## Rejected alternatives

- Add all fields to `missions`/`memories` immediately: too much migration and coupling risk.
- Separate database per new feature: fragmented policy/recovery and excessive operational complexity.
- Encode workspace/evidence only inside JSON metadata: weak constraints, hard indexing and easy policy mistakes.
- Vector database as memory authority: similarity cannot enforce authorization, validity or provenance.

## Revisit triggers

Revisit when scale, concurrent workloads or cross-device sync exceed SQLite evidence, but only after preserving the same typed contracts and proving a versioned export/import/rollback path.
