# Onyx Live Activation V8 External E6 Acceptance

- Evidence ID: `VE-ONYX-LIVE-ACTIVATION-V8-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED**
- Findings: **P0=0, P1=0, P2=0, P3=0**

This decision accepts only the corrected, frozen, default-off V8 candidate
whose manifest SHA-256 is
`ab28f369248df1ed807aeeee15658193a533881bf68fb2268d49692b52c20392`.
Its independently recomputed 21-binding root is
`8198e4265e45f6895ac07e95943a8868127ee7bb3037fd7512ccf31515d998dd`.

The independent gate reproduced 7 focused tests, 4 legacy desktop tests, the
V7 external acceptance, host/COM quoting and two-recreation idempotency,
24 transactional seams, exact post-V7 rollback, bootstrap activation from an
empty environment, explicit `pythonw.exe` existence, Ruff check and format,
and Python compilation. A socket-deny harness observed zero network attempts.

## Honest boundary

V8 remains default-off. No physical shortcut was written, no UI, microphone,
Gemini or provider was started, and no live process was restarted. Windows
source checkout uses the V8 bootstrap; packaged Windows and macOS/Linux
behavior remain delegated unchanged. Controlled activation is a separate
operational action.
