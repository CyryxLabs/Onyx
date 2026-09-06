# Story ONYX-GUILD-A9.3 — Guild SDC Workflow Templates & Run Projections V1

**Status:** Done (accepted 2026-08-17, `VE-GUILD-WORKFLOW-V1-E6-001`, root
`48043dee…`; acceptance verifier reproduced the full 30-file gate
752/0/0/17/96; autonomous-session honesty boundary recorded)
**Epic:** Onyx Engineering Guild (A9 expanded)
**Predecessor:** `VE-GUILD-HANDOFF-V1-E6-001` (A9.2, root `104efcc6…`)

## Story

As the Cyryx Labs owner, I want Onyx to hold **validated workflow templates
(the AEXOS Story Development Cycle as byte-pinned data) and workflow-run
projections** that bind template stages to required operations, authorized
roles and story-lifecycle states — completing the guild's descriptive
substrate so the first executable slice (A9.4) has nothing left to invent.

## Design

Module `core/guild_workflow_v1.py`, flag `ONYX_GUILD_WORKFLOW_V1`,
default-off, deterministic, hermetic; entry-bound to the A9.2 four-file
acceptance tuple; consumes exact `GuildRegistrySnapshotV1` (A9.1) and
`GuildStoryLedgerSnapshotV1` (A9.2) instances.

- `WorkflowStageV1`: `stage_id`, `required_operation` (operation grammar),
  `story_status_at_completion` ∈ the A9.2 lifecycle.
- `WorkflowTemplateV1`: `template_id`, ordered unique stages,
  `source_ref` + `source_sha256` + supplied bytes (AEXOS workflow YAML,
  byte-pinned like profiles); completion statuses must be non-regressing in
  lifecycle order and end at `done`.
- `WorkflowRunV1`: `run_id`, `template_id`, `story_id`, ordered
  `completed_stages`, each with `assigned_role_id`; stages must be an exact
  prefix of the template; each assignee must hold the stage's required
  operation under the registry (exclusive owner-sets respected); the
  story's recorded status must equal the completion status of the last
  completed stage (or `draft` when none).
- Sealed `GuildWorkflowV1` / `create_guild_workflow_v1`; projections
  `run_stage`, `is_run_complete`. **No dispatch/execution surface.**

## Acceptance criteria

1. [x] Contracts exactly as designed, default-off, hermetic.
2. [x] Stage/authority coupling: assignee lacking the required operation
       (incl. exclusive-owner violations) → rejected.
3. [x] Run/story coupling: status mismatch, unknown template/story, stage
       skip or reorder → rejected.
4. [x] Template gates: dup stages, unknown status, regressing completion
       order, not ending at done, tampered bytes → rejected.
5. [x] Entry-bind to A9.2 tuple; 35 adversarial tests; 30-file gate
       reproduced 752/0/0/17/96 (root `48043dee…`); E6 seal
       `VE-GUILD-WORKFLOW-V1-E6-001` with honesty boundary.
6. [x] Matrix/ledger updates batched into the next documentation-authority
       pass (V53) — recorded in the acceptance scope exclusions.

## File List (final)

- `docs/stories/ONYX-GUILD-A9.3.story.md`, `core/guild_workflow_v1.py`,
  `tests/test_guild_workflow_v1.py`, `scripts/verify_guild_workflow_v1.py`,
  `scripts/verify_guild_workflow_v1_acceptance.py`,
  `docs/onyx/adrs/ADR-0056-guild-workflow-v1.md`,
  `docs/onyx/research/GUILD_WORKFLOW_V1_SOURCES.md`,
  `docs/onyx/checkpoints/guild-workflow-v1/` (4 files),
  `docs/onyx/acceptance/VE-GUILD-WORKFLOW-V1-E6-001.md` + `.manifest.json`,
  `docs/onyx/VE-ACCEPTANCE-GUILD-WORKFLOW-V1-E6-001.sha256` (all new)

## Out of scope

Dispatch/execution (A9.4), sessions/grants/budgets/decommission (A9.5),
non-engineering packs, live calls, runtime wiring.

## File List

- `docs/stories/ONYX-GUILD-A9.3.story.md` (this story)

## Change Log

- 2026-08-18: Opened after A9.2 acceptance, same autonomous session.
