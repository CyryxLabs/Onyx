# Capability delta — Guild workflow V1

| Field | Before | After |
| --- | --- | --- |
| Guild workflow templates + run projections | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (contract, default-off) |
| Evidence | — | `VE-GUILD-WORKFLOW-V1-E6-001` |
| Authority added | — | None — templates + projections only; no execution surface |
| Guild execution binding / sessions / budgets | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` (unchanged; A9.4–A9.5) |

**What changed.** The guild's descriptive substrate is complete: authority
(A9.1), work records and gates (A9.2), and now stage flow (A9.3) — AEXOS
workflows as byte-pinned data with stage/authority and run/story coupling
enforced structurally.

**What did not change.** No execution, no external mutation, no model call,
no runtime wiring, no action authority. A9.4 (autopilot execution binding)
and A9.5 (governed away-mode with budgets and decommission) remain unbuilt,
each requiring its own acceptance.
