# Capability delta — Guild handoff V1

| Field | Before | After |
| --- | --- | --- |
| Guild story/verdict/handoff contracts | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (contract, default-off) |
| Evidence | — | `VE-GUILD-HANDOFF-V1-E6-001` |
| Authority added | — | None — ledger + projections only; no execution surface |
| Guild workflow engine / sessions / budgets | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` (unchanged; A9.3–A9.5) |

**What changed.** Onyx can hold validated story lifecycles with QA gates
bound to the constitutional `quality_verdicts` authority, the bounded AEXOS
QA loop, and compact bounded handoffs — the work-management substrate the
workflow engine (A9.3) will entry-bind to.

**What did not change.** No execution, no external mutation, no model call,
no runtime wiring, no action authority. Stage-operation semantics remain
deliberately unowned until A9.3.
