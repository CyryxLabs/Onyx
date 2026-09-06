# Guild Workflow V1 — E6 acceptance

- Evidence ID: `VE-GUILD-WORKFLOW-V1-E6-001`
- Decision date: `2026-08-17`
- Decision: **ACCEPTED — default-off guild workflow templates + run projections**
- Candidate manifest: `docs/onyx/checkpoints/guild-workflow-v1/manifest.json`
- Artifact root: `48043deead60aecc926925a191926f785896229026097e1e2048e46916dabfdc`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0`. Third Onyx Engineering
Guild slice (A9.3), completing the guild's **descriptive** substrate:
`core/guild_workflow_v1.py` (`ONYX_GUILD_WORKFLOW_V1`, default-off,
deterministic, hermetic), entry-bound to the accepted A9.2 four-file
acceptance tuple, consuming exact `GuildRegistrySnapshotV1` and
`GuildStoryLedgerSnapshotV1` instances. Byte-pinned `WorkflowTemplateV1`
records (AEXOS workflow sources; ordered unique stages binding a required
operation and a strictly progressing lifecycle completion status ending at
`done`) and `WorkflowRunV1` records (exact template-prefix stages; each
assignee must hold the stage operation under the registry with exclusive
owner sets respected; story status must equal the last completed stage's
declared status) build into a sealed snapshot with projections only — no
dispatch, execution, session, grant or budget surface (machine-asserted).
The module calls no model, opens no network, spawns no process, persists
nothing and takes no action. The gate reproduced **752 passed tests and 96
passed subtests, 0 failed and 0 errors** across thirty fresh Python
processes (seventeen explained platform-specific skips), on per-file counts
re-observed 2026-08-17.

Verification passes executed (2026-08-17, fresh processes): integrity — the
artifact root `48043dee` and all eight candidate artifacts recompute
exactly; the A9.2 entry-bind is genuine and reproduces through the healed
current-successor chain; functional — template gates (dup/unknown/
regressing/must-end-done/tamper), run gates (prefix/status/authority/
exclusive-owner coupling) and sealed construction enforced and adversarially
tested (35 tests); quality — mirrors the accepted slice idioms; the
verifier machine-checks source invariants, forbids network/process/dispatch
authority tokens and reproduces the thirty-file gate with per-file sum
check.

**Honesty boundary.** All verification passes were executed autonomously in
the owner-authorized session (@devops, R15B soak night). No independent
human review occurred. Matrix/ledger documentation updates for this slice
are batched into the next documentation-authority pass (V53, with A9.2's
and the release-consolidation updates). Scope is templates and run
projections only — execution (A9.4), sessions/grants/budgets/decommission
(A9.5), non-engineering packs, live calls and runtime wiring remain
unbuilt, and the full Onyx PRD is not claimed complete.
