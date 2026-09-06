# Guild Handoff V1 — E6 acceptance

- Evidence ID: `VE-GUILD-HANDOFF-V1-E6-001`
- Decision date: `2026-08-17`
- Decision: **ACCEPTED — default-off guild story/verdict/handoff contracts**
- Candidate manifest: `docs/onyx/checkpoints/guild-handoff-v1/manifest.json`
- Artifact root: `104efcc6762416ea6ffd2055a5368df49f605a9e507cc746d8cf0bbf37be6b79`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0` after one pre-acceptance
finding in **documentation-authority evidence** was discovered by this
candidate's first collection and remediated by the established procedure: the
Phase 5 current-successor transition chain had to be advanced (V51 → V52,
fixture `phase5_current_successor_transition_v52.json`) because the accepted
A9.1 slice legitimately updated `CAPABILITY_MATRIX.md` and
`VERIFICATION_EVIDENCE.md`, whose hashes the V51 transition binds. No
historical binding, hash or policy was rewritten; V52 is additive over
immutable V51, exactly like the fifty-one predecessors.

This is the second Onyx Engineering Guild slice (A9.2):
`core/guild_handoff_v1.py` (`ONYX_GUILD_HANDOFF_V1`, default-off,
deterministic, hermetic), entry-bound to the accepted A9.1 four-file
acceptance tuple, consuming an exact `GuildRegistrySnapshotV1`. It enforces
the fixed story lifecycle (`draft → approved → in_progress → in_review →
done` plus the single loop edge) over full transition histories; QA verdicts
whose reviewers must hold the constitutional `quality_verdicts` authority;
the bounded AEXOS QA loop (rejects capped at 5, loop edges reject-covered,
`done` requires approve and no blocked, blocked stories stay in review); and
bounded handoff artifacts (≤5 decisions, ≤10 files, ≤3 blockers, non-empty
next action, 4,000-byte budget). Projections only — there is no dispatch,
execution, session, grant or budget surface (machine-asserted). The module
calls no model, opens no network, spawns no process, persists nothing and
takes no action. The gate reproduced **717 passed tests and 96 passed
subtests, 0 failed and 0 errors** across twenty-nine fresh Python processes
(seventeen explained platform-specific skips), on per-file counts
re-observed 2026-08-17.

Verification passes executed (2026-08-17, fresh processes): integrity — the
artifact root `104efcc6` and all eight candidate artifacts recompute
exactly; the A9.1 entry-bind is genuine and byte-exact and reproduces
through the healed current-successor chain; functional — lifecycle, QA-gate,
loop-coverage, blocked-stuck, handoff-bound and sealed-construction rules
enforced and adversarially tested (43 tests); quality — mirrors the accepted
slice idioms; the verifier machine-checks lifecycle invariants (loop edge
present, skip path absent, reject cap exactly 5), forbids
network/process/dispatch authority tokens and reproduces the
twenty-nine-file gate with per-file sum check.

**Honesty boundary.** All verification passes were executed autonomously in
the owner-authorized session (@devops, R15B soak night). No independent
human review occurred. Deliberate narrowing against the draft story:
stage-operation authority requirements are deferred to the workflow engine
(A9.3), which owns stage semantics. The capability-matrix and
evidence-ledger updates for this slice are batched into the next
documentation pass (with the pending release-consolidation updates) to
advance the documentation-authority transition once, not twice; until that
pass lands, this acceptance record and its manifest are the authoritative
statement of the slice. Scope is story/verdict/handoff contracts only — no
workflow execution, no sessions/grants/budgets/decommission, no
non-engineering packs, no live provider or model call, no runtime wiring,
and no claim that the full Onyx PRD is complete.
