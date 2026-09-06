# Onyx Live Activation V2 — Rejected

Status: **REJECTED / FROZEN**

Activation V2 is retained byte-for-byte as historical evidence and must never be
enabled. Its owner projection path traverses and reads Qt `QObject`/`QWidget`
state from the calling worker thread. That violates Qt thread-affinity rules even
though the durable Owner Profile V8 and Phase 5 reconnect behavior passed their
focused gates.

The replacement must be an isolated V3 candidate. V3 must marshal immutable
requests to a GUI-thread dispatcher, snapshot and mutate every HUD/setup target
only on its owning Qt thread, roll back all windows atomically, return a bounded
immutable acknowledgement, compensate durable owner state after any UI failure,
and latch `DEGRADED` on timeout, closed-window, or projection failure.

Frozen V2 SHA-256 evidence:

- `core/onyx_live_activation_v2.py`: `a39c8a43b04b0147dd7efc44bbe355a6873417df8e2432a93c77ef042cd60659`
- `scripts/launch_onyx_live_v2.pyw`: `b614616b3efc188b8179596e16d1a209c60d6cefefbb429146d6c9775d770e3b`
- `scripts/verify_onyx_live_activation_v2.py`: `58f0328a93f72be2d0e806fd9f3b3656a20b92507e020bd2eaae7a91f7cbc5a7`
- `scripts/verify_onyx_live_activation_v2_host.py`: `3bb6e35c84c4b07417ae0b306c1b5a28b5a6842ce2feff63d32e0a135fc8b12b`
- `tests/test_onyx_live_activation_v2.py`: `8b84eccee4cb020e448119cec05f9e47fcf0f1af53d3245fc2df63442ba48e8c`
- `docs/onyx/checkpoints/onyx-live-activation-v2/ONYX_LIVE_ACTIVATION_V2_CHECKPOINT.md`: `a0572baa31a68d81ce1aadb53780b65267331b4b4e96b97c89fe7a83a62c41f7`
- `docs/onyx/checkpoints/onyx-live-activation-v2/manifest.json`: `f829cdc1c4ddb8b2612ab82b4c835d66d7440020f2e18a04ed8d1bcc881af76d`

No live activation, credential provisioning, provider call, shortcut change, or
restart was performed by this rejection record.
