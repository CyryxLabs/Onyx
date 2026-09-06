# ADR-0055 — Guild handoff and story contracts V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

A9.1 accepted the guild role-profile registry and constitutional authority
matrix (`VE-GUILD-PROFILES-V1-E6-001`). Before any workflow engine may
execute anything (A9.3), the AEXOS story-driven development discipline itself
must exist as validated data: stories with the fixed lifecycle, QA verdicts
bound to the constitutional `quality_verdicts` authority, the bounded QA
loop, and compact bounded handoffs. This ADR records that second slice.

## Decision

Add `core/guild_handoff_v1.py`, a default-off (`ONYX_GUILD_HANDOFF_V1`),
deterministic, hermetic contract entry-bound to the A9.1 four-file acceptance
tuple, importing the registry snapshot type from `core.guild_profiles_v1`.
It enforces, structurally:

1. **Fixed lifecycle.** `draft → approved → in_progress → in_review → done`
   with the single loop edge `in_review → in_progress`; full transition
   history required, must start at `draft`, land on the recorded status, and
   contain only allowed edges.
2. **QA gate.** `done` requires ≥1 `approve` verdict and no `blocked`
   verdict; every verdict's reviewer must hold `quality_verdicts` in the
   supplied `GuildRegistrySnapshotV1` (exact type); loop edges must be
   covered by `reject` verdicts; rejects capped at 5 (the AEXOS QA-loop
   maximum); a blocked story must remain `in_review`.
3. **Bounded handoffs.** Distinct existing roles, known story, ≤5 decisions,
   ≤10 files, ≤3 blockers, non-empty next action, hard 4,000-byte total
   budget (the AEXOS agent-handoff compaction rule).
4. **No execution.** Stories and handoffs describe; there is no
   dispatch/execution/session surface (machine-asserted).

The module calls no model, opens no network, spawns no process, persists
nothing and takes no action. Deliberate narrowing against the draft story:
per-stage assignee operation requirements are deferred to the workflow
engine (A9.3), which owns stage semantics; V1 validates role existence and
the constitutional QA authority only.

## Consequences

- The guild's work-management substrate exists with the same evidence rigor
  as its authority substrate; A9.3 can entry-bind to this slice and gain
  execution semantics without inventing story/handoff structure.
- Editing accepted documents remains guarded: this slice's first candidate
  run also surfaced that the documentation-authority transition chain
  (Phase 5 successor transitions) must be advanced (V52) whenever
  `CAPABILITY_MATRIX.md`/`VERIFICATION_EVIDENCE.md` legitimately change —
  recorded as operational knowledge.
- Any regression in the lifecycle, QA gates, handoff bounds, entry-bind or
  the cumulative gate fails the slice verifier.

## Alternatives considered

- Ordered verdict/transition interleaving validation: rejected for V1 —
  count-based coverage (loop edges ≤ rejects) is the honest simple gate; an
  ordered event log belongs to the workflow engine.
- Encoding stage-op authority here: rejected — stage semantics are the
  engine's contract; premature encoding would freeze names the engine must
  own.
- Allowing `blocked` stories to keep transitioning: rejected — blocked is an
  escalation state; movement resumes only through later governed slices.
