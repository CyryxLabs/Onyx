# Guild project envelope V1 checkpoint

Fifth and final Onyx Engineering Guild substrate slice (A9.5): a default-off,
deterministic, hermetic governed-envelope contract that wraps every guild
project in hard budgets, declared KPIs and the owner's termination rule as an
executable decommission policy. It adds one module, one feature flag and no
runtime wiring.

`core/guild_project_envelope_v1.py` (`ONYX_GUILD_PROJECT_ENVELOPE_V1`) is
entry-bound to the accepted Guild Execution-Intent (A9.4) four-file
acceptance tuple and consumes exact `GuildRegistrySnapshotV1` and
`GuildExecutionIntentSnapshotV1` instances. `ProjectBudgetV1` carries
micro-unit cost and loss caps with a strictly positive floor and an absolute
ceiling, the loss budget never above the cost cap, and a bounded
`max_missions`; an unlimited budget is not representable. `ProjectKpiV1`
requires a metric, a non-negative integer target and a measurement
reference, and every envelope declares at least one. `DecommissionPolicyV1`
is mandatory and complete: `max_consecutive_gate_failures >= 1`, a non-empty
`kill_switch_ref`, and both `on_budget_breach` and `on_kpi_failure` drawn
from the closed vocabulary `{"revoke_and_decommission"}` — in V1 no softer
outcome exists in the type. Bound intents must exist in the A9.4 snapshot,
must still declare `requires_owner_approval`, and no intent may be claimed by
two envelopes. `remaining_cost_micro` and `is_budget_breached` are pure
arithmetic projections over a declared cap, and `is_active()` is structurally
False. The module calls no model, opens no network, spawns no process,
persists nothing and takes no action.

The cumulative selection reproduces 910 passing tests and 96 passing subtests
across thirty-four fresh Python processes — the thirty-three files of the
accepted Argos selection plus this slice's forty-two adversarial tests — with
seventeen platform-specific skips and zero failure/error.

Scope and limits: envelope records and projections only. No activation, no
real spending or measurement, no decommission execution, no MissionStore,
grant, approval-inbox or kill-switch coupling, no non-engineering packs, no
model/provider calls, no startup/voice/UI/dashboard wiring, and no claim that
the full Onyx PRD is complete. The runtime slice that will own activation,
spending, measurement and decommission execution remains unbuilt and
separately gated.
