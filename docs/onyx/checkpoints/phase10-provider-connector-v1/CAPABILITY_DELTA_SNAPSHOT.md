# Capability delta — Phase 10 provider connector V1

| Field | Before | After |
| --- | --- | --- |
| Provider account-status read (contract) | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (contract, default-off) |
| Evidence | — | `VE-P10-PROVIDER-CONNECTOR-V1-E6-001` |
| Authority added | — | None — read-only; no publish method; live fetch owner-gated |
| Live provider fetch / publishing | `BLOCKED_BY_ACCESS` | `BLOCKED_BY_ACCESS` (unchanged; owner-gated) |

**What changed.** Onyx has a governed, route-pinned, read-only way to read one
approved provider's account status (verification, follower count, recent post
ids) for a registry-declared test account, with identity attributed from the
trusted registry and a spoofed-handle response denied.

**What did not change.** No publishing, no audience research, no community
action, and no real network in evidence. The live provider fetch and any publish
remain `BLOCKED_BY_ACCESS` until an owner-approved OAuth/app-review + test-account
run and separate publish slice are built and accepted. This delta adds no runtime
wiring and no action authority.
