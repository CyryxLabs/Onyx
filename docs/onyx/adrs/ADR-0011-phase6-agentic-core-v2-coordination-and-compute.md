# ADR-0011: Phase 6 V2 durable coordination and lineage compute authority

Status: Candidate — default-off, not accepted, not live

Date: 2026-07-22

## Context

Phase 6 V1 preserved the existing MissionStore executor and added a useful
typed planning/evidence boundary, but independent review rejected four gaps:
compute was not cumulative, materialization was not cross-instance idempotent,
proposal identity was self-asserted, and checkpoint root construction was not
reproducibly specified.

V1 artifacts are immutable. V2 must correct these gaps without changing the
accepted mission engine, Phase 5, permission broker, UI, dashboard or live
configuration.

## Decision

V2 composes V1's frozen domain serialization and evidence store, and adds a
separate SQLite coordination sidecar. The coordination sidecar owns two narrow
authorities:

1. a plan-lineage compute account with one active operation lease; and
2. one durable materialization reservation per plan plus immutable orphan
   tombstones.

### Compute budget

`max_compute_seconds` is one wall-time account shared by the root plan and all
repairs. Planning, every MissionStore runner attempt, independent verification
and explicit restart recovery charge that account. Each runner receives the
smaller of the immutable step timeout and current lineage remainder. On timeout
the daemon result is detached, the MissionStore mission is cancelled so its
late result cannot commit, and exhaustion projects the plan to terminal
`BLOCKED` with reason `BUDGET_EXHAUSTED`. A successful runner/verifier result is
not committed after the account reaches its limit.

`recover()` is an explicit restart boundary: persisted in-flight compute is
charged through the recovery instant and closed, and MissionStore remains the
authority that prevents blind replay of an uncertain step.

### Cross-instance materialization

Before MissionStore creation, V2 commits a unique store-level reservation with
a bounded lease. Concurrent instances either own that reservation, observe an
existing immutable binding, or return without creating. Mission titles carry a
deterministic plan marker. If a prior owner died after create but before bind,
the recovery owner discovers the unmatched mission, cancels it where it is
active, writes an immutable tombstone and blocks the plan. A live binding or
orphan tombstone is never replaced by a second mission.

MissionStore remains the sole mission executor. V2 does not approve missions,
open an approval window, bypass tool authorization or replay work.

### Adapter identity

Planner V2 captures the exact host-routed `ModelDescriptorV1` before invocation.
The returned exact `PlanningProposalV1.adapter_id` must equal that captured
descriptor ID. The comparison occurs before plan creation. The proposal is then
passed to the frozen V1 validator through a captured adapter that cannot invoke
the provider a second time.

### Artifact-root algorithm

The V2 checkpoint root is computed as follows:

1. Exclude `manifest.json` itself.
2. For every artifact, use its canonical relative POSIX path and lowercase
   SHA-256 hex digest.
3. Form the UTF-8 record `path + NUL + digest`.
4. Sort records by their complete Unicode string in Python's deterministic
   ascending order.
5. Join with a single LF byte and no trailing LF.
6. SHA-256 the resulting bytes.

`artifact_root_v2()` implements the algorithm. The focused test suite reads the
final manifest, independently hashes every listed byte artifact and recomputes
the root.

## Consequences

- V2 remains additive, explicit-path and strict default-off under only exact
  `ONYX_PHASE6_AGENTIC_CORE_V2=true`.
- Two SQLite files are intentional: the V1-compatible plan/evidence sidecar at
  the requested path and the derived `.v2-coordination` authority sidecar.
- Late Python threads cannot be forcibly killed safely. V2 sets cancellation,
  cancels MissionStore authority and discards late results. V2 executable tools
  remain provider-free read-only, so a detached computation has no admitted
  mutation authority.
- A process that creates a mission and is terminated before binding leaves a
  discoverable candidate. It becomes cancelled/tombstoned on reservation
  recovery and cannot be approved after cancellation.
- This candidate adds no provider, network, subprocess, Phase 5 catalog or
  external coding-agent activation.

## Rejected alternatives

- Modifying MissionStore to absorb Phase 6 reservations: rejected because that
  accepted executor is out of scope.
- Relying on a Python lock: rejected because it has no cross-instance meaning.
- Resetting compute after repair/restart: rejected because it defeats the goal
  budget.
- Trusting the proposal's adapter ID: rejected because model output is not host
  authority.
