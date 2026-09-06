# Capability delta — Guild profiles V1

| Field | Before | After |
| --- | --- | --- |
| Guild role-profile registry + authority matrix | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (contract, default-off) |
| Evidence | — | `VE-GUILD-PROFILES-V1-E6-001` |
| Authority added | — | None — registry + matrix only; no dispatch/execution surface |
| Operator Cells orchestration (sessions, grants, budgets) | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` (unchanged; later guild slices A9.2–A9.5) |

**What changed.** Onyx can hold a validated, sealed image of the AEXOS
delegation discipline: role profiles with byte-pinned first-party sources, the
Constitution Article II exclusivity floor enforced exactly, one-claim
exclusivity with owner sets, a closed delegation graph and squad (team pack)
membership — the precondition every later guild slice entry-binds to.

**What did not change.** No orchestration, no workflow execution, no external
mutation, no model call, no runtime wiring, no action authority. The guild's
executable slices (handoff/story contracts, SDC engine, autopilot binding,
governed away-mode projects with budgets and decommission) remain unbuilt and
each requires its own acceptance.
