# ADR-0048 — Phase 9 exit candidate V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

Phase 9 of the Onyx PRD adds an intelligence and opportunity radar:
primary/official-source-first ingestion across geopolitics, finance/macro,
AI/technology/cyber, startups/markets, API changes, the creator economy and
Cyryx-relevant opportunities; publication/event-time recording, recycled-story
deduplication and fact/inference/scenario/recommendation separation with
corroboration; transparent opportunity scoring across pain/economic cost,
urgency, buyer/payability, timing, competition, Cyryx advantage, time to
MVP/revenue, complexity, distribution, moat, legal/platform risk and evidence
confidence; and World Monitor only through an approved license path.

Three vertical slices were implemented additively, each exactly default-off,
deterministic (or route-pinned for the connector) and independently E6-accepted
with its own hash-bound evidence chain: intelligence ingestion V1, opportunity
scoring V1 and approved-source live ingestion V1. World Monitor was **not**
built — it remains `BLOCKED_BY_LICENSE`. This ADR records the aggregate exit
checkpoint that binds the three accepted component roots to the Phase 9 PRD
requirements without adding any new runtime authority.

## Decision

Publish an aggregate `phase9-exit-candidate-v1` checkpoint that (1) maps each
bound Phase 9 PRD requirement to the accepted `VE-*` evidence that satisfies it,
and machine-verifies that mapping (every accepted slice has exactly one
requirement citing exactly its accepted identifier), (2) pins the four-file
acceptance tuple (candidate manifest, acceptance record, acceptance metadata and
SHA anchor) of each of the three accepted slices by SHA-256, and (3) reproduces
the complete cumulative Phase 9 gate — the twenty-three inherited Phase 7
stable-core, Phase 8 connector and Phase 9 intelligence test files — in fresh
Python processes. The checkpoint adds no code module, no feature flag and no
wiring; it is a verification-only aggregation over already-frozen predecessors.

Scope is deliberately the **default-off intelligence/opportunity/live-connector
contract layer only**. The aggregate binds and claims exactly what the three
accepted E6 envelopes establish — deterministic ingestion/scoring and a
route-pinned, no-redirect, approved-source live-connector contract that performs
no real network I/O in evidence. It does **not** bind or claim any live
execution: the approved-source live ingestion run is owner-gated and unbound.
World Monitor is explicitly **excluded** — while `BLOCKED_BY_LICENSE` it has no
accepted evidence to cite, and this aggregate copies none of its UI/assets/source
and implies no Cyryx ownership. Consistent with the PRD guard, nothing here turns
geopolitical or financial headlines into autonomous trading actions.

## Consequences

- The Phase 9 **intelligence-layer** default-off implementation is claimed
  complete only for what the three accepted slices exercise as contract
  evidence: official-source-first ingestion with publication/event-time
  separation, Unicode-safe recycled-story deduplication and
  fact/inference/scenario/recommendation typing with corroboration; transparent
  twelve-dimension opportunity scoring with per-dimension direction and
  boundary-tested bands; and a strict-origin, route-pinned, redirect-disabled
  approved-source live-connector contract.
- The checkpoint explicitly does **not** claim any live execution as bound
  evidence, does not bind World Monitor (BLOCKED_BY_LICENSE), enables no
  autonomous trading, and claims no startup/voice/UI/dashboard wiring, no
  Phase 10–16 work and no full Onyx PRD completion.
- Any regression in an accepted component root, the requirement→evidence
  mapping, or the cumulative gate fails the exit verifier, so the aggregate
  cannot silently drift from its parts.

## Alternatives considered

- Re-hashing each component's full artifact closure instead of its four-file
  acceptance tuple: rejected as redundant, because each acceptance metadata file
  already binds its candidate artifact root, and the tuple is the same anchor
  the individual acceptance verifiers reproduce.
- Holding the Phase 9 exit until World Monitor ships: rejected because the
  licensed connector is externally blocked; the exit honestly scopes it out and
  binds only the built, accepted intelligence/opportunity/live-connector layer.
- Binding the owner-gated live ingestion run as evidence: rejected because a real
  approved-source fetch is an owner decision outside the default-off contract
  scope; the live slice is bound only as a hermetic, no-real-network contract.
