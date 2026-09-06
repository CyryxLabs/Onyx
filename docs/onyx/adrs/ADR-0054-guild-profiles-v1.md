# ADR-0054 — Guild role-profile registry and authority matrix V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

The owner directed (2026-08-17) that Onyx gain software-architect / dev / QA /
devops / scrum-master skills so it can develop projects autonomously, with the
first-party AEXOS framework (Cyryx Labs, `aexos-engine`) as the base, replacing
whole squads across company areas over time. The target architecture reserved
this slot as Operator Cells (§4.6): versioned, governed role profiles. This ADR
records the first Engineering Guild slice: the role-profile registry and
enforceable authority matrix, with no orchestration authority.

## Decision

Add `core/guild_profiles_v1.py`, a default-off (`ONYX_GUILD_PROFILES_V1`),
deterministic, hermetic contract entry-bound to the accepted Phase 10
content-draft four-file acceptance tuple. It enforces, structurally:

1. **Constitutional floor.** `MANDATORY_CONSTITUTIONAL_EXCLUSIVES` mirrors the
   AEXOS Constitution v1.1.0 Article II exactly: `git_push`, `pr_creation` and
   `release_tag` belong to `devops`; `story_creation` to `po`/`sm`;
   `architecture_decisions` to `architect`; `quality_verdicts` to `qa`. A pack
   that omits, reassigns, under-claims or over-claims any entry is rejected.
2. **One-claim exclusivity.** Roles claiming an operation exclusively form its
   owner set; any other profile merely listing that operation among its
   allowed operations is rejected — authority cannot leak.
3. **Closed delegation graph.** Every delegation names an existing, distinct
   role that itself holds the delegated operation.
4. **Byte-pinned provenance.** Every profile and team pack supplies its exact
   AEXOS source bytes and SHA-256; mismatched bytes are rejected and the sealed
   snapshot carries a deterministic `pack_root_sha256` over all sources.
5. **No orchestration.** The registry has no dispatch/execution surface of any
   kind; `is_operation_permitted` and `delegation_target` are pure
   projections. Sessions, workflow execution, grants, budgets and decommission
   are later guild slices (A9.2–A9.5), each separately gated.

The module calls no model, opens no network, spawns no process, persists
nothing and takes no action.

## Consequences

- Onyx can hold a validated, sealed image of the AEXOS delegation discipline —
  the precondition for every later guild slice — without gaining any authority.
- Later slices (handoff/story contracts, SDC workflow engine, autopilot
  binding, governed away-mode projects) must entry-bind to this slice's
  accepted evidence, inheriting the constitutional floor.
- Any regression in the floor, the exclusivity/leak rules, the delegation
  graph, the byte pinning, the entry-bind or the cumulative gate fails the
  slice verifier.

## Alternatives considered

- Parsing AEXOS agent markdown/YAML inside the module: rejected — parsing is
  caller/tooling work; the hermetic contract validates supplied records and
  bytes, keeping the module deterministic and I/O-free.
- Hard-coding the twelve current AEXOS roles: rejected — the constitutional
  floor is the invariant; the role catalog is data, so future squad packs
  (copy, design, legal, data, traffic, ...) load without contract changes.
- Granting the registry a dispatch method behind the feature flag: rejected —
  orchestration authority must be structurally absent here and arrive only
  through later, separately accepted slices.
