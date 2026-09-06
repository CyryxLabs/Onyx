# Capability delta — Phase 10 content draft V1

| Field | Before | After |
| --- | --- | --- |
| Content draft + provenance/policy gate | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (contract, default-off) |
| Evidence | — | `VE-P10-CONTENT-DRAFT-V1-E6-001` |
| Authority added | — | None — draft + gate only; no publish method, `published` unrepresentable |
| Publishing / scheduling | `BLOCKED_BY_ACCESS` | `BLOCKED_BY_ACCESS` (unchanged; later gated slice) |

**What changed.** Onyx can hold provenance-checked, claim-validated, accessible,
policy-reviewed content drafts (assets with declared rights, validated claims
citing evidence, alt text on visuals, approval only after a positive policy
review) ready to hand to the separately accepted editorial calendar.

**What did not change.** No publishing, no live provider action, no analytics. The
publish/schedule step and the live provider run remain `BLOCKED_BY_ACCESS` until
separately built and accepted. This delta adds no runtime wiring and no action
authority.
