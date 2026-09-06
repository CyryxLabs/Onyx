# Guild Profiles V1 — E6 acceptance

- Evidence ID: `VE-GUILD-PROFILES-V1-E6-001`
- Decision date: `2026-08-17`
- Decision: **ACCEPTED — default-off guild role-profile registry + authority matrix**
- Candidate manifest:
  `818196ac6bd2048bbfe5218d0e576b392b07aa1005816b6f4b867f3ee9bbc09d` is the
  artifact root; the checkpoint manifest binding it is
  `docs/onyx/checkpoints/guild-profiles-v1/manifest.json`
- Artifact root: `818196ac6bd2048bbfe5218d0e576b392b07aa1005816b6f4b867f3ee9bbc09d`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0` after two pre-acceptance
findings in **predecessor evidence** were discovered by this candidate's chain
and remediated forward-only: (1) the Phase 10 provider-connector module had
drifted post-acceptance — documented and healed via
`CORRECTION-P10-PROVIDER-CONNECTOR-POST-ACCEPTANCE-DRIFT.md` and the
`VE-P10-PROVIDER-CONNECTOR-CURRENT-V1-E6-001` source-integrity successor;
(2) three inherited gate files had grown since the July selection — the
cumulative selection was re-observed per file on 2026-08-17 and records
current counts. No accepted byte was rewritten for either finding.

This is the first Onyx Engineering Guild slice (Operator Cells, A9.1): a
default-off, deterministic, hermetic role-profile registry entry-bound to the
accepted Phase 10 content-draft four-file acceptance tuple, ingesting the
first-party AEXOS definitions as byte-pinned data. It enforces the AEXOS
Constitution v1.1.0 Article II floor exactly (`git_push`/`pr_creation`/
`release_tag` → `devops`; `story_creation` → `po`/`sm`;
`architecture_decisions` → `architect`; `quality_verdicts` → `qa`), one-claim
exclusivity with owner sets and leak rejection, a closed delegation graph,
byte-exact source pinning with a deterministic pack root, and squad (team
pack) membership. `is_operation_permitted` and `delegation_target` are pure
projections; there is no dispatch, execution, session, grant or budget
surface. The module calls no model, opens no network, spawns no process,
persists nothing and takes no action. The gate reproduced **674 passed tests
and 96 passed subtests, 0 failed and 0 errors** across twenty-eight fresh
Python processes; seventeen skips are explained platform-specific inherits
(sixteen artifact-service, one control-plane POSIX).

Verification passes executed (2026-08-17, fresh processes): integrity — the
artifact root `818196ac` and all eight candidate artifacts recompute exactly,
the accepted content-draft entry-bind is genuine and byte-exact, and the
predecessor chain reproduces through the documented current-successor path;
functional — the constitutional floor, exclusivity/leak, delegation-graph,
byte-pinning and sealed-construction gates are enforced and adversarially
tested (48 tests), and the registry exposes no orchestration surface
(machine-asserted); quality — the module mirrors the accepted Phase 9/10
slice idioms (sealed factory, entry-bind, frozen dataclasses, byte-bounded
text contract), and the verifier machine-checks source invariants, forbids
network/process/dispatch authority tokens and reproduces the twenty-eight-file
cumulative gate with a per-file sum check.

**Honesty boundary.** All verification passes were executed autonomously in
the owner-authorized session (@devops, R15B soak night, "seguir com tudo
possível essa noite... Não precisa da minha autorização"). No independent
human review occurred; prior slices' three-independent-review structure is
not claimed. Scope is deliberately **registry and matrix only** — no
orchestration, no workflow execution, no sessions/grants/budgets/decommission,
no non-engineering squad packs, no live provider or model call. Those are
later guild slices (A9.2–A9.5), each requiring its own acceptance. This
acceptance live-wires no component, adds no action authority, and does not
claim the full Onyx PRD complete.
