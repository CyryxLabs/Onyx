# Onyx Live Activation V3 — Rejected

Status: **REJECTED / FROZEN**

Activation V3 is retained byte-for-byte as historical evidence and must never
be enabled. V3 correctly confined QObject discovery, reads, and writes to the Qt
affinity thread, but treated a setter returning normally as success. It did not
immediately read back the exact target property after every apply and rollback
setter. A silent no-op or wrong-value setter could therefore acknowledge a UI
state that was not actually committed or restored.

The isolated V4 replacement must validate normalized exact readback after each
setter, report compound apply/rollback failures, handle targets destroyed during
dispatch with an explicit Qt validity check, compensate Owner Profile V8 on any
UI mismatch, and latch `DEGRADED`.

Frozen V3 SHA-256 evidence:

- `core/onyx_live_activation_v3.py`: `8860a140c053e07633209d482209635d67f8e1a4c1b5f70f7bd029ff8c0f0be7`
- `scripts/launch_onyx_live_v3.pyw`: `86df14f853654053984623bef3557e205c28898b36b8c6ff02558f834877fc6a`
- `scripts/verify_onyx_live_activation_v3.py`: `0dca532679626b3b4815caf668bf8cbbca2b1a48e76f551a6d2ed586e8e6a4c0`
- `scripts/verify_onyx_live_activation_v3_host.py`: `2c51d4c61b79a009dbbf4d6ba3fccd38cb3299147cf28c70bc452c7938dbde10`
- `scripts/verify_onyx_live_activation_v3_qt.py`: `c6f8f8000b6344f6fd8a469949ac15c06bdffc7e4f655b95dcb76f9b8dcf0ffb`
- `tests/test_onyx_live_activation_v3.py`: `31c67de48a54c6145cda72ea25bf526dcd21b12ef8866c77b7bf149300bda6b8`
- `docs/onyx/checkpoints/onyx-live-activation-v3/ONYX_LIVE_ACTIVATION_V3_CHECKPOINT.md`: `4419193517c172b9324a49233a0920c4c39b8456deb0a5c942294d4921a3f1d0`
- `docs/onyx/checkpoints/onyx-live-activation-v3/manifest.json`: `e886340788a9c305b4cc2142da98e1964546382050880b7123b1203d0b8c9006`

No live activation, credential provisioning, provider call, shortcut change, or
restart was performed by this rejection record.
