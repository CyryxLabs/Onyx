# Phase 6 Agentic Core V1 rejection record

Status: **REJECTED — preserved byte-for-byte; never accepted or activated**

Date: 2026-07-22

The independent gate rejected the isolated V1 candidate. Its source, tests,
ADR, checkpoint and manifest remain frozen exactly as reviewed. This record is
additive and is not part of the V1 artifact root.

## Blocking findings

1. `max_compute_seconds` was validated as plan metadata but not enforced as a
   lineage-wide compute wall budget across steps, repair and restart recovery.
   Per-step timeouts could therefore permit cumulative compute overrun.
2. Materialization used only an in-process lock. Two core instances could both
   create a MissionStore mission before either immutable binding became visible;
   create-before-bind failures had no durable orphan tombstone.
3. The planner trusted `PlanningProposalV1.adapter_id` after invocation and did
   not compare that self-asserted identity with an independently captured
   descriptor of the adapter that was actually invoked.
4. The checkpoint recorded an artifact root without defining the canonical
   byte algorithm or shipping an acceptance test that recomputed it.

## Disposition

- V1 remains strict default-off and must not be wired live.
- None of V1's positive provider-free, MissionStore, scope, evidence, kill or
  external-adapter boundaries are withdrawn.
- Corrections are implemented only in the additive V2 candidate and require new
  independent functional, integrity and quality gates before activation.
