# Guild execution-intent V1 checkpoint

Fourth Onyx Engineering Guild slice (A9.4): a default-off, deterministic,
hermetic execution-intent contract — the inert bridge between the accepted
descriptive substrate and the Phase 11 project autopilot. It adds one
module, one feature flag and no runtime wiring.

`core/guild_execution_intent_v1.py` (`ONYX_GUILD_EXECUTION_INTENT_V1`) is
entry-bound to the accepted Guild Workflow (A9.3) four-file acceptance tuple
and to the exact Phase 11 autopilot bytes
(`core/phase11_project_autopilot_v1.py`, 185,305 bytes, SHA-256
`a5dc26eb034748045a7a69c826a56615f176561006cefd60518d79e4ff8b8430`, still
declaring `MISSION_TYPE = "project_autopilot_v1"`); it consumes exact
A9.1/A9.2/A9.3 snapshots. `ExecutionIntentV1` records bind the exact next
uncompleted stage of a known run (forward-only; one open intent per stage;
story/run coupling enforced), an assignee holding the stage operation under
the registry (exclusive owner sets respected), a non-empty
workspace-relative patch scope under a closed POSIX-form grammar, and a
byte-capped gate-argv shape. `requires_owner_approval` must be exactly True
and `is_dispatchable()` is structurally False — dispatch arrives only with
a later, separately accepted slice under session grants, the approval
inbox, cost budgets and the kill switch. The module calls no model, opens
no network, spawns no process, persists nothing and takes no action.

The cumulative selection reproduces 796 passing tests and 96 passing
subtests across thirty-one fresh Python processes — the thirty files of the
accepted A9.3 selection plus this slice's forty-four adversarial tests —
with seventeen platform-specific skips and zero failure/error.

Scope and limits: intent binding only. No dispatch, no MissionStore
coupling, no sessions/grants/budgets, no decommission mechanism, no
non-engineering packs, no model/provider calls, no startup/voice/UI/dashboard
wiring, and no claim that the full Onyx PRD is complete.
