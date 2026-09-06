# Capability delta — Voice session authority V1

| Field | Before | After |
| --- | --- | --- |
| Exact low-risk enablement (bounded session authority) | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (contract, default-off) |
| Evidence | — | `VE-VOICE-SESSION-AUTHORITY-V1-E6-001` |
| Authority added | — | **Yes, deliberately**: an in-scope, in-root operation under a live envelope can be authorized without prompting the owner. This is the first Onyx contract that grants rather than shadows |
| Always-explicit gates | prompt every time | unchanged — still prompt every time, envelope or not |
| Runtime wiring | — | none; the hook is not installed by this slice |

**What changed.** Ordinary reading, writing and local development inside the
owner's authorized roots can stop interrupting, which is the friction the
owner reported. The decision surface is bounded by an exact trigger phrase,
authorized roots compared by whole path components, a clamped lifetime, an
operation cap and a kill switch that denies first.

**What did not change.** Deleting (even inside a root), desktop and browser
control, pushing, publishing, messaging, spending and credentials still stop
and ask. No runtime wiring, no UI, no persistence. And Onyx still has no
speaker verification: the owner accepted that exposure explicitly, and the
mitigations bound the blast radius rather than prevent a spoofed opening.
