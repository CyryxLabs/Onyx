# Onyx Live Activation V4 — Candidate Checkpoint

Status: **candidate verified, default-off, not activated**

Date: 2026-07-22

V4 is an isolated replacement for rejected V1/V2/V3. It preserves the accepted
host and component bytes while adding an eleventh transactional seam at the
real `ui.MainWindow.closeEvent` for deterministic dispatcher teardown.

## Verified GUI transaction contract

- Worker operations exchange only frozen requests/acknowledgements with the
  affinity-thread dispatcher through a queued Qt signal and bounded event.
- GUI target handles use weak references plus `sip.isdeleted`, the PyQt6
  validity mechanism available in this runtime, before every access.
- Every HUD/setup setter is followed immediately by its exact getter/property.
  The normalized readback must equal the normalized expected address.
- Silent no-op setters, wrong-value setters, getter exceptions, and targets
  destroyed during the setter are rejected.
- On apply failure, every already-attempted target is rolled back in reverse
  order. Every rollback setter is also read back exactly. Apply and rollback
  failures are returned separately in one immutable compound acknowledgement.
- Owner Profile V8 is compensated to the prior durable name on any UI failure;
  the controller then latches `DEGRADED`.
- A controller remains `READY` only after the durable snapshot and every live
  target readback agree at transaction boundaries. A newly attached window is
  synchronised and verified before it is accepted as ready.
- Timeout cancellation still removes the request before late queued delivery
  can mutate any target.

## Evidence

- Focused Activation V4 suite: **13 passed** in 20.95s.
- Combined Owner Profile V8 + Phase 5 Integration V3 + HUD V5 + Activation V4:
  **67 passed** in 49.24s.
- Real host: **11/11** seam rollback failpoints; authority factory was never
  called before a complete installation.
- Continuity: **64/64** reconnects, **64/64** catalog reads, **128** unique
  short monotonic session/trace IDs.
- Real offscreen QApplication: exact normalized set/correct/forget readback;
  two windows; setup open/closed; affinity; silent no-op; wrong-value setter;
  getter exception; rollback no-op compound failure; target destroyed during
  dispatch; durable compensation; sticky degraded state.
- Direct affinity-path performance: **64 transactions in 2.812 ms**.
- Ruff, Python compilation, and bundle closure verification: pass.
- The sole pytest warning was repository `.pytest_cache` `WinError 5`; isolated
  basetemp execution and all assertions passed.

## Candidate hashes

- `core/onyx_live_activation_v4.py`: `2521b5dcf53172e73e23219e9266037f7312a233ef135281a1a2ac3660aec05b`
- `scripts/launch_onyx_live_v4.pyw`: `a7bfc190cb95d49e871fcd312f32badbd1a5a6d18393ca725d214f1f66769af8`
- `scripts/verify_onyx_live_activation_v4.py`: `20426a7fd2e592dfa54b2a352928a941e01bd7798314bb3d21363a9c0e6bd597`
- `scripts/verify_onyx_live_activation_v4_host.py`: `e1e53cee11d1fbaf460d8690f9131da56c9773e75ffbd286345395c969fe2105`
- `scripts/verify_onyx_live_activation_v4_qt.py`: `19015ebf96a32e449709831d86d90465e612ba63f770bea917f01dd21ab3b95b`
- `tests/test_onyx_live_activation_v4.py`: `4c776af560a7f3bfd470bef91d205fddbe509c6c767cbaad2b754f3023068783`

No live activation, credential provisioning, provider call, shortcut change,
or restart was performed while producing this checkpoint.
