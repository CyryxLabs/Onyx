# Onyx Live Activation V3 — Candidate Checkpoint

Status: **candidate verified, default-off, not activated**

Date: 2026-07-22

V3 is an isolated replacement for rejected V1/V2. It preserves the accepted
host and component bytes and adds the tenth transactional seam at the real
`ui.MainWindow.__init__`. Each constructed window owns an
`OwnerUiDispatcherV3` on its Qt affinity thread.

## Threading and transaction contract

- Worker owner operations submit frozen `OwnerUiRequestV3` values through a
  queued Qt signal and wait for a frozen `OwnerUiAckV3` using a bounded
  `threading.Event`.
- The direct path is allowed only when `QThread.currentThread() ==
  window.thread()`.
- Worker code never discovers, snapshots, reads, or mutates a QObject/QWidget.
- The GUI slot snapshots all HUD and open setup targets across all registered
  windows before mutation. A failure, expiry, or cancellation reverses every
  changed target in reverse order and verifies the rollback on the GUI thread.
- Timeout, unavailable event loop, and dispatcher teardown fail closed. A
  timed-out queued request is cancelled before it can mutate UI state.
- Owner Profile V8 changes are durably committed before projection. If UI
  acknowledgement fails, V3 compensates durable identity back to its prior
  value and then latches `DEGRADED`, keeping durable/UI truth aligned.

## Evidence

- Focused Activation V3 suite: **13 passed** in 22.18s.
- Combined Owner Profile V8 + Phase 5 Integration V3 + HUD V5 + Activation V3:
  **67 passed** in 44.50s.
- Real host: **10/10** seam rollback failpoints; no authority factory call
  before a complete installation.
- Continuity: **64/64** reconnects, **64/64** catalog reads, **128** unique
  short monotonic session/trace IDs.
- Real offscreen QApplication: set/correct/forget setters executed on affinity
  thread; setup open/closed; two windows; mutate-then-raise global rollback;
  no-event-loop timeout; dispatcher teardown; durable compensation; sticky
  degraded state.
- Ruff, Python compilation, and the 44-file closure verifier: pass.
- The only pytest warning was inability to write the repository `.pytest_cache`
  path (`WinError 5`); isolated basetemp execution and all assertions passed.

## Candidate hashes

- `core/onyx_live_activation_v3.py`: `8860a140c053e07633209d482209635d67f8e1a4c1b5f70f7bd029ff8c0f0be7`
- `scripts/launch_onyx_live_v3.pyw`: `86df14f853654053984623bef3557e205c28898b36b8c6ff02558f834877fc6a`
- `scripts/verify_onyx_live_activation_v3.py`: `0dca532679626b3b4815caf668bf8cbbca2b1a48e76f551a6d2ed586e8e6a4c0`
- `scripts/verify_onyx_live_activation_v3_host.py`: `2c51d4c61b79a009dbbf4d6ba3fccd38cb3299147cf28c70bc452c7938dbde10`
- `scripts/verify_onyx_live_activation_v3_qt.py`: `c6f8f8000b6344f6fd8a469949ac15c06bdffc7e4f655b95dcb76f9b8dcf0ffb`
- `tests/test_onyx_live_activation_v3.py`: `31c67de48a54c6145cda72ea25bf526dcd21b12ef8866c77b7bf149300bda6b8`

No live activation, credential provisioning, provider call, shortcut change,
or restart was performed while producing this checkpoint.
