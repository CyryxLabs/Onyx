# Guild Project Envelope V1 — E6 acceptance

- Evidence ID: `VE-GUILD-PROJECT-ENVELOPE-V1-E6-001`
- Decision date: `2026-08-19`
- Decision: **ACCEPTED — default-off governed project envelope**
- Candidate manifest: `docs/onyx/checkpoints/guild-project-envelope-v1/manifest.json`
- Artifact root: `438fe075ca88e31e588b4e04dc087ab9e58fce5c3fabdfa658a1dc199ad60874`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0`. This is the fifth and
final Onyx Engineering Guild substrate slice (A9.5), the one that encodes the
owner's termination rule as mechanism rather than prose.
`core/guild_project_envelope_v1.py` (`ONYX_GUILD_PROJECT_ENVELOPE_V1`,
default-off, deterministic, hermetic) is entry-bound to the accepted A9.4
four-file acceptance tuple and consumes exact A9.1 registry and A9.4
execution-intent snapshots.

It enforces, structurally: hard micro-unit budgets with a strictly positive
floor, an absolute ceiling and a loss budget that may never exceed the cost
cap, so an unlimited budget is not representable; at least one declared KPI
with a metric, a non-negative integer target and a measurement reference; a
mandatory and complete `DecommissionPolicyV1` whose
`max_consecutive_gate_failures` is at least 1, whose `kill_switch_ref` is
non-empty and whose `on_budget_breach` and `on_kpi_failure` are drawn from
the closed vocabulary `{"revoke_and_decommission"}` — in V1 no softer
outcome exists in the type; and intent coupling where every bound intent
must exist in the A9.4 snapshot, must still declare
`requires_owner_approval`, and may be claimed by at most one envelope.
`remaining_cost_micro` and `is_budget_breached` are pure arithmetic
projections over a declared cap, and `is_active()` is structurally `False`.
The module calls no model, opens no network, spawns no process, persists
nothing and takes no action. The gate reproduced **910 passed tests and 96
passed subtests, 0 failed and 0 errors** across thirty-four fresh Python
processes (seventeen explained platform-specific skips).

Verification passes executed (2026-08-19, fresh processes): integrity —
artifact root `438fe075` and all eight candidate artifacts recompute exactly
and the A9.4 entry-bind is genuine; functional — budget bounds, the
loss-above-cap rejection, KPI requirements, every decommission-policy field,
the closed outcome vocabulary, intent existence, owner-approval and
single-binding rules, and sealed construction are enforced and adversarially
tested (42 tests), with structurally false activity machine-asserted;
quality — mirrors the accepted slice idioms, and the verifier asserts the
decommission vocabulary and budget floor as constants, forbids
network/process/dispatch/activation/spend authority tokens (the executable
`def decommission(` form specifically, so the read-only
`decommission_outcome` projection stays legitimate) and reproduces the
thirty-four-file gate with a per-file sum check.

**Honesty boundary.** All verification passes were executed autonomously in
the owner-authorized session (@devops). No independent human review
occurred. Matrix and ledger updates are batched into the next
documentation-authority pass. Scope is envelope records and projections only
— no activation, no real spending or measurement, **no decommission
execution**, and no MissionStore, grant, approval-inbox or kill-switch
coupling. A project cannot run until a separately accepted runtime slice
couples those systems; the full Onyx PRD is not claimed complete.
