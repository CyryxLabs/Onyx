# Capability delta — Guild execution-intent V1

| Field | Before | After |
| --- | --- | --- |
| Guild execution-intent binding | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (contract, default-off) |
| Evidence | — | `VE-GUILD-EXECUTION-INTENT-V1-E6-001` |
| Authority added | — | None — intents are inert records; `is_dispatchable` structurally False |
| Guild dispatch / sessions / budgets / decommission | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` (unchanged; A9.5+) |

**What changed.** Workflow stages can now bind to exact, validated,
version-pinned execution intents against the Phase 11 autopilot — with the
owner-approval requirement and non-dispatchability as type-level facts. The
future dispatcher can only ever execute what this substrate has already
authorized.

**What did not change.** No execution, no external mutation, no model call,
no runtime wiring, no action authority. A9.5 (governed away-mode with
grants, budgets and the owner's decommission rule) remains unbuilt and
separately gated.
