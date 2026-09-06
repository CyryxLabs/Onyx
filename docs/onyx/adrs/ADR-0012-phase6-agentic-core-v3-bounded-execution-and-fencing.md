# ADR-0012: Phase 6 V3 bounded execution, fenced materialization and indexed recovery

Status: Candidate — default-off, not accepted, not live

Date: 2026-07-22

## Context

Independent review rejected V2 because a synchronous planning component could
outlive the lineage compute deadline, materialization leases had no fencing
generation or exact MissionStore idempotency contract, and restart recovery
depended on broad scans without terminal retention. V1 and V2 artifacts are
immutable and remain rejected. V3 must close these gaps without replacing the
existing MissionStore executor or changing `main.py`, UI, dashboard, permission
broker, Phase 5, live configuration or provider routing.

## Decision

V3 remains an isolated composition over V1's frozen plan/evidence store and
V2's exact planner-adapter identity check. A dedicated V3 SQLite coordination
sidecar owns only compute reservations, generation fences and indexed recovery
metadata.

### Lineage-wide bounded execution

The request compute account exists before planner invocation and is then bound
to the resulting root plan. Planner, critic, repair planner, every step runner,
verifier and explicit recovery execute inside the same persisted lineage-wide
account. Every admitted interval is charged in `finally`-equivalent completion
logic using the greater of monotonic and wall elapsed time, including callback
exceptions. The callback receives no time beyond the account remainder.

Potentially hung synchronous calls use one bounded daemon worker with a queue
of one. If its deadline expires, its admission token is cleared, the executor
is permanently poisoned, and no replacement worker is spawned. The late return
has no state-commit path. Mission execution additionally cancels MissionStore
authority before terminally projecting `BUDGET_EXHAUSTED`. A verifier timeout
cannot project completion even if the underlying mission already succeeded.
Reconstruction of the isolated core is the explicit recovery boundary after a
worker is poisoned.

### Deterministic idempotent mission creation

MissionStore gains the additive `create_idempotent()` API. It derives a stable
mission and step identity from an exact materialization key and creates the
mission, steps, audit events and awaiting-approval transition in one
`BEGIN IMMEDIATE` transaction. Concurrent exact replays converge on the same
mission. Reusing the key for different immutable content fails closed. No
existing creation or execution API is changed and live `main.py` does not call
the new method.

V3's materialization key is the immutable plan ID. The coordination sidecar
records a monotonically increasing generation and a random owner token. The
owner renews and checks its exact generation/token immediately before and after
idempotent creation. Final binding is conditional on the same fence. A stale
owner cannot renew, bind, cancel, overwrite or tombstone the winner; it only
observes the deterministic winner. Real spawned-process tests force expiry at
both pre-create and post-create interleavings and require one executable bound
mission.

### Indexed recovery and retention

Recovery reads only bounded `runtime_plans` candidates ordered by a declared
partial/indexed queue. Persisted in-flight compute recovery is separately
bounded and indexed. Exact schema, index and trigger inventory is validated on
every open and fails closed on divergence. Query-plan tests prove SQLite uses
the runtime and active-budget recovery indexes.

`compact()` deletes at most the requested number of expired terminal
coordination rows after the retention interval. It does not delete V1's
immutable plan/evidence records or MissionStore missions.

### Artifact-root algorithm

V3 reuses the specified V2 algorithm: exclude the manifest; encode each
canonical relative POSIX path, NUL and lowercase SHA-256 as UTF-8; sort complete
records ascending; join with LF and no trailing LF; SHA-256 the resulting
bytes. The final test independently hashes each listed artifact and recomputes
the root.

## Consequences

- Only exact `ONYX_PHASE6_AGENTIC_CORE_V3=true` enables explicit construction;
  no accepted or live surface imports V3.
- A timed-out synchronous callback can occupy one daemon thread until it
  returns, but cannot create additional workers or commit a late result.
- Admitted callbacks must not mutate authoritative state directly; only their
  returned values are eligible for a post-deadline commit check.
- MissionStore remains the sole executor and approval authority. V3 does not
  approve work, bypass permissions, enable providers, use network/subprocess or
  activate an external coding agent.
- V3 is not accepted or live until independent functional, integrity and
  quality gates approve its frozen checkpoint.

## Rejected alternatives

- Starting a fresh daemon thread after each timeout: rejected because hung
  callbacks would leak resources without bound.
- Treating cancellation as thread termination: rejected because Python cannot
  safely kill an arbitrary thread.
- Discovering missions by title after creation: rejected because titles are not
  a durable idempotency identity.
- Allowing a stale owner to cancel or tombstone: rejected because it can destroy
  the winner after a lease race.
- Full projection or mission scans on recovery: rejected because restart cost
  grows without an explicit bound.
