# ADR-0056 — Guild workflow templates and run projections V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

A9.1 accepted the role/authority registry; A9.2 accepted story, QA-verdict
and handoff contracts. The remaining descriptive gap is the workflow itself:
the AEXOS Story Development Cycle as validated data, binding stages to
required operations, authorized roles and story-lifecycle states. This ADR
records that third slice, completing the guild's descriptive substrate so
the first executable slice (A9.4) has nothing structural left to invent.

## Decision

Add `core/guild_workflow_v1.py`, default-off (`ONYX_GUILD_WORKFLOW_V1`),
deterministic, hermetic; entry-bound to the A9.2 four-file acceptance tuple;
consuming exact `GuildRegistrySnapshotV1` and `GuildStoryLedgerSnapshotV1`
instances. It enforces, structurally:

1. **Templates as byte-pinned data.** `WorkflowTemplateV1` ingests AEXOS
   workflow definitions (source bytes + SHA-256, tamper-rejected) with
   ordered unique stages; each `WorkflowStageV1` binds a
   `required_operation` and a `story_status_at_completion`; completion
   statuses must strictly progress through the A9.2 lifecycle and end at
   `done`.
2. **Runs as exact prefixes.** A `WorkflowRunV1` names a known template and
   story; its completed stages must be an exact template prefix; each
   assignee must hold the stage's required operation under the registry,
   with exclusive owner sets respected.
3. **Run/story coupling.** The story's recorded status must equal the
   completion status of the last completed stage (`draft` when none) —
   workflow progress and story lifecycle cannot diverge.
4. **No execution.** Projections only (`run_stage`, `is_run_complete`);
   there is no dispatch/execution/session surface (machine-asserted).

The module calls no model, opens no network, spawns no process, persists
nothing and takes no action.

## Consequences

- The full AEXOS discipline — who may do what (A9.1), how work is recorded
  and gated (A9.2), and how stages flow (A9.3) — now exists as accepted,
  entry-chained, default-off contracts. A9.4 binds execution to this
  substrate without defining structure.
- Templates are data: the canonical SDC and any future workflow load
  without contract changes, byte-pinned to their AEXOS sources.
- Any regression in stage/authority coupling, run/story coupling, template
  gates, entry-bind or the cumulative gate fails the slice verifier.

## Alternatives considered

- Hard-coding the SDC stages as a module constant: rejected — Article IV
  (No Invention); the workflow is first-party AEXOS data and is ingested,
  not restated.
- Validating verdict/handoff placement per stage here: rejected — A9.2
  already gates verdicts and handoffs; duplicating placement rules would
  create two owners for one invariant.
- Allowing runs over stories absent from the ledger snapshot: rejected —
  unanchored runs are exactly the drift this slice exists to prevent.
