# Onyx HUD Orb V6 Candidate 003 External E6 Acceptance

- Evidence ID: `VE-HUD-ORB-V6-C003-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED**
- Findings: **P0=0, P1=0, P2=0, P3=0**

This decision accepts only Candidate 003 with manifest SHA-256
`ba034588791b1003a6743bf037ae32a11285adcac7c4084cba1bc5bb3923ae1c`.
The independently recomputed 15-record candidate-and-anchor root is
`0e100c6d7ace7c058d57ec53b72338b566345c4e36874c120bc8bc1c219f76ee`.

The gate reproduced 25 V6 tests, 15 V5 tests and 28 representative runtime
tests, Ruff check and format, compilation, exact flag adversarials, idempotent
installation and exact rollback. The physical capture enumerates exactly one
`QQuickWidget` and fails closed when a second widget exists.

## Honest boundary

This is a default-off Windows/Direct3D11 acceptance. Candidate 003 explicitly
reuses Candidate 002 PNG and metrics byte-for-byte because only Python
formatting and candidate identity changed. No new physical capture is claimed.
No live activation occurred. Native macOS/Linux physical rendering remains
outside this evidence.
