# Guild workflow V1 checkpoint

Third Onyx Engineering Guild slice (A9.3): a default-off, deterministic,
hermetic workflow-template and run-projection contract. It adds one module,
one feature flag and no runtime wiring.

`core/guild_workflow_v1.py` (`ONYX_GUILD_WORKFLOW_V1`) is entry-bound to the
accepted Guild Handoff (A9.2) four-file acceptance tuple and consumes exact
`GuildRegistrySnapshotV1` and `GuildStoryLedgerSnapshotV1` instances. It
builds byte-pinned `WorkflowTemplateV1` records (AEXOS workflow sources;
ordered unique stages binding a required operation and a strictly
progressing story-lifecycle completion status ending at `done`) and
`WorkflowRunV1` records (exact template-prefix completed stages; each
assignee must hold the stage operation under the registry with exclusive
owner sets respected; the story's recorded status must equal the last
completed stage's declared status) into a sealed `GuildWorkflowSnapshotV1`.
Projections only (`run_stage`, `is_run_complete`); there is no dispatch,
execution, session, grant or budget surface. The module calls no model,
opens no network, spawns no process, persists nothing and takes no action.

The cumulative selection reproduces 752 passing tests and 96 passing
subtests across thirty fresh Python processes — the twenty-nine files of
the accepted A9.2 selection (per-file counts re-observed 2026-08-17) plus
this slice's thirty-five adversarial tests — with seventeen
platform-specific skips and zero failure/error.

Scope and limits: templates and run projections only. No dispatch, no
sessions/grants/budgets, no decommission mechanism, no non-engineering
packs, no model/provider calls, no startup/voice/UI/dashboard wiring, and
no claim that the full Onyx PRD is complete. Execution arrives with A9.4,
separately gated.
