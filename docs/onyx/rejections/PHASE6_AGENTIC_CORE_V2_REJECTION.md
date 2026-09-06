# Phase 6 Agentic Core V2 rejection record

Status: **REJECTED — preserved byte-for-byte; never accepted or activated**

Date: 2026-07-22

The independent gate rejected V2. Its core, tests, ADR, checkpoint and manifest
remain frozen exactly as reviewed. This additive record is not part of the V2
artifact root.

## Blocking findings

1. Planner, critic, verifier and repair planning were not all executed inside a
   bounded lineage reservation/deadline. A hung synchronous adapter/verifier
   could outlive the compute budget, and V2's per-call daemon threads could
   accumulate after repeated timeouts.
2. Materialization used a renewable-time lease without a fencing generation and
   depended on post-create title discovery. Under forced expiry, a stale owner
   could create or tombstone while a new owner was winning.
3. MissionStore had no exact deterministic idempotent creation contract, so a
   stale-first/new-first interleaving could not prove exactly one bound and
   executable mission.
4. Recovery scanned broad projection/mission lists and V2 coordination tables
   had no bounded indexed queue or terminal retention/compaction contract.

## Disposition

- V2 remains strict default-off and must not be wired live.
- Its positive lineage accounting, adapter identity binding, default-off scope,
  root verifier and frozen V1 compatibility remain useful evidence.
- Corrections are additive in V3 and require new independent functional,
  integrity and quality gates before activation.
