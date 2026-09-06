# Onyx Live Activation V10 Candidate 002 External E6 Acceptance

- Evidence ID: `VE-ONYX-LIVE-ACTIVATION-V10-C002-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED**
- Findings: **P0=0, P1=0, P2=0, P3=0**

This decision accepts only Onyx Live Activation V10 Candidate 002 with
candidate manifest SHA-256
`208897c07a24d6fe9e22636cfa42ce5772b17e95fac18e86d9fdbc993b34720e`
and independently recomputed 25-artifact root
`f42994deaea77f64f4a8870fb397f09790effbb24195ee8dcd7b074ac8e7dcc1`.

The accepted composition is the exact V9 E6 installation plus the exact
HUD/Orb V7 Candidate 003 E6 package and exact Phase 6 Live Wiring V1 E6
package, within the accepted Phase 5 Exit Candidate V2 historical envelope.
The gate authenticated all four accepted closures before importing the
application host, then exercised the real
`install_candidate(ui_module) is True` and exact uninstall rollback contract.
The complete V10 transaction owns 34 seams and restores the exact installed V9
state.

The external gate reproduced 29 candidate tests and eight independent E6 tests.
It checked all 25 frozen source bindings, the recomputed artifact root, every
HUD V7 manifest leaf and QML artifact, predecessor membership, acceptance
envelopes, drift and tamper rejection, fresh-namespace HUD loading, private
rollback authority, arbitrary-working-directory Windows controls, the
already-configured owner shortcut refresh path and exact non-Windows V9
delegation. No network call, provider call, physical activation or shortcut
write occurred.

## Resolved during the external gate

Before freeze, the gate corrected the candidate artifact root and restored the
HUD V7 accepted-root verification path. It added strict leaf-level closure
verification for the HUD manifest and loads the hash-bound HUD implementation
in a fresh private namespace so poisoned imports, helpers or module globals
cannot substitute the accepted API.

Rollback authority now captures immutable private references to the accepted
HUD uninstaller, wiring controller and original V9 seams; mutation of public
controller attributes cannot redirect rollback. Both Windows command controls
now normalize the project root from `%~dp0`, and an already-configured Windows
owner receives the V10 shortcut refresh without replaying first-run setup.
Candidate and external verifiers now allocate isolated per-run pytest roots;
two simultaneous executions cannot collide on a shared Windows directory.

## Honest boundary

This E6 accepts a default-off Windows activation package. It does not activate
V10, modify a real desktop shortcut, call Gemini or any provider, add a new
user-facing Phase 6 route, or declare Phase 6 complete. macOS and Linux retain
the exact accepted V9 delegation; native V10 activation on those platforms is
outside this evidence.
