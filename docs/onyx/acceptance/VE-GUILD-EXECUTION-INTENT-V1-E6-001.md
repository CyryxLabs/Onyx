# Guild Execution-Intent V1 — E6 acceptance

- Evidence ID: `VE-GUILD-EXECUTION-INTENT-V1-E6-001`
- Decision date: `2026-08-19`
- Decision: **ACCEPTED — default-off guild execution-intent binding**
- Candidate manifest: `docs/onyx/checkpoints/guild-execution-intent-v1/manifest.json`
- Artifact root: `68a4fc775dbdccb0741c0bf69aa5ff786966f4f828f2220ac35ec21efde64e83`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0`. Fourth Onyx
Engineering Guild slice (A9.4): the inert bridge between the accepted
descriptive substrate and the Phase 11 project autopilot.
`core/guild_execution_intent_v1.py` (`ONYX_GUILD_EXECUTION_INTENT_V1`,
default-off, deterministic, hermetic) is entry-bound to the accepted A9.3
four-file acceptance tuple **and** to the exact autopilot bytes
(`core/phase11_project_autopilot_v1.py`, 185,305 bytes, SHA-256
`a5dc26eb034748045a7a69c826a56615f176561006cefd60518d79e4ff8b8430`, still
declaring `MISSION_TYPE = "project_autopilot_v1"`), consuming exact
A9.1/A9.2/A9.3 snapshots. Intents bind the run's exact next uncompleted
stage (forward-only; one open intent per stage; story/run coupling), an
assignee holding the stage operation under the registry (exclusive owner
sets respected), a non-empty workspace-relative patch scope under a closed
POSIX-form grammar, and a byte-capped gate-argv shape.
`requires_owner_approval` must be exactly `True` and `is_dispatchable()` is
structurally `False`. The module calls no model, opens no network, spawns
no process, persists nothing and takes no action. The gate reproduced
**796 passed tests and 96 passed subtests, 0 failed and 0 errors** across
thirty-one fresh Python processes (seventeen explained platform-specific
skips).

Verification passes executed (2026-08-18/19, fresh processes): integrity —
artifact root `68a4fc77` and all eight candidate artifacts recompute
exactly; the A9.3 entry-bind and the autopilot byte-pin are genuine;
functional — version-pin denial, forward-only binding, authority coupling,
patch-scope grammar, owner-approval and non-dispatchability gates enforced
and adversarially tested (44 tests); quality — mirrors the accepted slice
idioms; the verifier machine-checks the autopilot pin and the structurally
false dispatchability, forbids network/process/dispatch authority tokens
and reproduces the thirty-one-file gate with a per-file sum check.

**Honesty boundary.** All verification passes were executed autonomously in
the owner-authorized session (@devops). No independent human review
occurred. Matrix/ledger documentation updates are batched into the next
documentation-authority pass. Scope is intent binding only — dispatch,
MissionStore coupling, sessions, grants, budgets and decommission remain
unbuilt and separately gated (A9.5+); no runtime wiring or action
authority is added, and the full Onyx PRD is not claimed complete.
