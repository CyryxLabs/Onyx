# Guild handoff V1 checkpoint

Second Onyx Engineering Guild slice (A9.2): a default-off, deterministic,
hermetic story/verdict/handoff ledger. It adds one module, one feature flag
and no runtime wiring.

`core/guild_handoff_v1.py` (`ONYX_GUILD_HANDOFF_V1`) is entry-bound to the
accepted Guild Profiles (A9.1) four-file acceptance tuple and consumes an
exact `GuildRegistrySnapshotV1`. It builds `StoryContractV1` records (full
transition history over the fixed lifecycle `draft → approved → in_progress
→ in_review → done` plus the loop edge `in_review → in_progress`),
`QaVerdictV1` records (approve/reject/blocked; reviewer must hold the
constitutional `quality_verdicts` authority; rejects capped at 5; loop edges
reject-covered; `done` requires approve and no blocked; blocked stories stay
in review) and `HandoffArtifactV1` records (distinct existing roles, known
story, ≤5 decisions / ≤10 files / ≤3 blockers, non-empty next action,
4,000-byte budget) into a sealed `GuildStoryLedgerSnapshotV1`. Projections
only; there is no dispatch, execution, session, grant or budget surface. The
module calls no model, opens no network, spawns no process, persists nothing
and takes no action.

The cumulative selection reproduces 717 passing tests and 96 passing
subtests across twenty-nine fresh Python processes — the twenty-eight
files of the accepted A9.1 selection (per-file counts re-observed
2026-08-17) plus this slice's forty-three adversarial tests — with seventeen
platform-specific skips and zero failure/error.

Scope and limits: story/verdict/handoff contracts only. No workflow
execution, no sessions/grants/budgets, no decommission mechanism, no
stage-operation authority (deferred to A9.3 by design), no non-engineering
packs, no model/provider calls. The slice claims no startup/voice/UI/dashboard
wiring and no full Onyx PRD completion.
