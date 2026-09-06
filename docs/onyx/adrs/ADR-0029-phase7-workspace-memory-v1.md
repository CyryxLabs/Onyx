# ADR-0029 — Phase 7 Workspace Memory V1

Status: accepted for candidate construction; E6 pending  
Date: 2026-07-23

## Context

The existing `MemoryStore.search()` ranks across the global legacy store and
updates access counters. Calling it and filtering afterward would violate the
Phase 7 contract because unauthorized content could influence ranking and
state before workspace policy is applied.

The accepted workspace sidecar already stores reviewed memory references, but
its Phase 4 API exposes single-reference lookup rather than the policy-rich,
pre-ranking retrieval required by layered memory.

## Decision

Add a sealed, default-off `WorkspaceMemoryAdapterV1` that preserves both
existing stores and changes no live call site.

The adapter:

1. requires the exact accepted Phase 6 exit roots before enabled construction;
2. binds one active non-legacy workspace, one principal, an explicit
   non-restricted sensitivity set, one initialized `MemoryStore`, one open
   workspace registry, and a 32-64 byte host integrity key;
3. reads only metadata rows for the bound workspace;
4. verifies strict duplicate-free JSON, exact schema, row/payload identity,
   key fingerprint, HMAC, status, source availability, validity and freshness;
5. excludes cross-workspace ambiguity, wrong principals, unapproved,
   superseded/rejected, deleted/revoked, future, expired, disallowed-class and
   stale-by-default records before content access;
6. opens the existing memory database with `mode=ro` and `query_only=ON`;
7. fetches only authorized IDs, validates the exact schema and a digest of
   every returned legacy `MemoryRecord`;
8. ranks only the authorized records and returns bounded, provenance-rich
   results labeled `content_trust=untrusted_data`;
9. reattests workspace, store identity, metadata snapshot and concurrent
   `data_version` before returning;
10. never calls global `MemoryStore.search()` or `MemoryStore.list()`.

V1 intentionally provides no metadata writer, vector index, graph,
cross-workspace union, restricted-memory retrieval, candidate promotion,
contradiction writer, Founder Brief, UI, startup, or live wiring.

## Consequences

- A highly similar record in another workspace cannot enter the ranking set.
- Legacy APIs and records remain byte-compatible and authoritative for legacy
  paths.
- V1 metadata must be signed by the host and refer to the exact legacy row.
- Stale records are excluded by default and explicitly labeled when requested.
- Ambiguous multi-workspace ownership is excluded rather than guessed.
- Rollback is omission or disablement of
  `ONYX_PHASE7_WORKSPACE_MEMORY_V1`; no migration or restart is required.

## Rejected alternatives

- Global search followed by filtering: rejected because policy would run after
  ranking and access-counter mutation.
- Copying legacy memory into a second search database: rejected because it
  would create another authority and synchronization problem.
- Treating vector similarity as workspace authority: rejected; similarity is
  discovery only and may never bypass identity, sensitivity, validity or
  source policy.
- Returning restricted content through this adapter: rejected; restricted
  material remains outside general memory/model context.
