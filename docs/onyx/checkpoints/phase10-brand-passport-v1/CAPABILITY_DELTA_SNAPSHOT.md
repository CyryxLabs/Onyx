# Capability delta — Phase 10 brand passport V1

| Field | Before | After |
| --- | --- | --- |
| Brand/account inventory | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (contract, default-off) |
| Evidence | — | `VE-P10-BRAND-PASSPORT-V1-E6-001` |
| Authority added | — | None — inventory only; `can_publish` structurally `False` |
| Publishing | `BLOCKED_BY_ACCESS` | `BLOCKED_BY_ACCESS` (unchanged; later gated slice) |

**What changed.** Onyx can now hold an auditable, tamper-evident inventory of the
authorized brands (Cyryx Labs, MAAX Studio, Lyra, …) and their declared social
accounts, with always-on policy guards enforced on every passport and strict
`(platform, handle)`→one-brand separation. The capability is default-off and
carries no publishing or network authority.

**What did not change.** No live provider connection, no publishing, no audience
research, no community action. The first real publish per account remains
`BLOCKED_BY_ACCESS` until an OAuth/app-review + test-account slice is separately
built and accepted. This delta adds no runtime wiring and no action authority.
