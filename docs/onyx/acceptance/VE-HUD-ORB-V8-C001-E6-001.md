# Onyx HUD / Orb V8 Candidate 001 External E6 Acceptance

- Evidence ID: `VE-HUD-ORB-V8-C001-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED**
- Findings: **P0=0, P1=0, P2=0, P3=0**

This decision accepts only the default-off HUD/Orb V8 Candidate 001 with
candidate manifest SHA-256
`b3ea35bea9a160803ae01c3ddfc8e4e5811d5547095f7dc21b0ca8f2adbf4152`
and independently recomputed eleven-artifact root
`7d32ac55daeb3bb01dcdb18ea112c4d6d71453ff28cf1aed7fb07d9ae803a967`.

The gate reproduced seven candidate tests, eight independent acceptance tests
and all 19 accepted V7 regression tests in separate Qt processes. It verified
the exact default-off flag, the authenticated V7 installation chain, exact
rollback, one QQuickWidget, live QML loading and no changes to V10.

Three physical 1440x900 Direct3D11 captures prove the bounded behavior on this
machine. The internal particle phase advanced from 0.34 to 1.105 while the
projection was `SPEAKING`; it reset to zero and remained zero in `LISTENING`.
The two speaking captures have different hashes and visibly different internal
particle positions. No arc, orbit, ring or square was added around the Orb.

Measured host CPU was 0.404% speaking, 0.083% idle and 0.000% hidden. The new
voice layer reported 12 FPS speaking and zero FPS idle/hidden.

## Honest boundary

This E6 accepts a default-off Windows/Direct3D11 visual package. It does not
activate V8 in V10 or modify shortcuts. Native macOS/Linux physical rendering,
live voice-provider reproduction and cross-device performance remain outside
this evidence.

