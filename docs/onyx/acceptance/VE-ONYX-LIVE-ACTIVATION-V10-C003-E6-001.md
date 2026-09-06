# Onyx Live Activation V10 Candidate 003 External E6 Acceptance

- Evidence ID: `VE-ONYX-LIVE-ACTIVATION-V10-C003-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED**
- Findings: **P0=0, P1=0, P2=0, P3=0**

This decision accepts only Onyx Live Activation V10 Candidate 003 with
candidate manifest SHA-256
`b22459a5315370f179089cf67d501a687305c2147d2c68ef132575326d47e236`
and independently recomputed 26-artifact root
`5f1b32f01fe7a481f27062b90e5cbbf9816a7b6306547b7a0fe7ddf2a26a56c4`.

C003 preserves the C002 integrity controls and adds one transactional
onboarding seam before `MainWindow` construction. When the secure credential
is configured, the settings file passes the hardened reader, `os_system` is
valid and the owner remains blank or a recognized placeholder, the existing
assistant surface reaches READY without the legacy setup overlay. Identity
authority still reports the literal address `Sir` and retains the exact
first-contact question and `set_owner_name` flow; C003 does not invent or
persist a name.

The original setup denial remains authoritative for missing credentials,
missing or invalid OS settings and unreadable configuration. The 35-seam
transaction captures the original `_check_config` method in immutable private
rollback authority. Public controller drift cannot redirect restoration, and
the onboarding failpoint restores the exact installed V9 method.

The external gate reproduced 33 candidate tests, eight independent E6 tests
and one isolated real-host physical smoke. The smoke constructed real Qt
`main`/`ui` windows for READY and denial paths with an intercepted shortcut
writer. It observed the READY blank-owner path, literal `Sir`, exact contact
question, and setup overlays for missing credential, missing OS and unreadable
configuration. No persistent shortcut, live activation, network or provider
call occurred.

## Honest boundary

This E6 accepts a default-off Windows C003 activation package. It does not
activate V10, write a real desktop shortcut, call Gemini, add a new user-facing
Phase 6 route or declare Phase 6 complete. macOS and Linux continue to delegate
to exact accepted V9. A later physical activation gate must still start the
accepted package against the owner's real local state.
