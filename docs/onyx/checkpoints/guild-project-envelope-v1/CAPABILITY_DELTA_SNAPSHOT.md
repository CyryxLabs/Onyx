# Capability delta — Guild project envelope V1

| Field | Before | After |
| --- | --- | --- |
| Guild governed project envelope (budgets, KPIs, decommission policy) | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (contract, default-off) |
| Evidence | — | `VE-GUILD-PROJECT-ENVELOPE-V1-E6-001` |
| Authority added | — | None — envelopes are inert records; `is_active` structurally False |
| Guild runtime activation / spending / decommission execution | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` (unchanged; later separately gated runtime slice) |

**What changed.** The guild substrate is complete. Every project can now be
expressed only as a bounded envelope: hard micro-unit cost and loss budgets
with no unlimited option, at least one declared measurable KPI, owner-gated
intents bound at most once, and a mandatory decommission policy whose outcome
vocabulary is closed at `revoke_and_decommission` with a required kill-switch
reference. The owner's termination rule is now machine-checkable rather than
prose.

**What did not change.** No activation, no real spending or measurement, no
decommission execution, no external mutation, no model call, no runtime
wiring, no action authority. A project cannot run until a separately accepted
runtime slice couples grants, the approval inbox, cost observability and the
kill switch.
