# Phase 5 current successor transition V17

Status: **FROZEN SOURCE — REBUILD AND INSTALLED ACCEPTANCE REQUIRED**  
Transition: `tests/fixtures/phase5_current_successor_transition_v17.json`  
Transition SHA-256: `03edb5ae160ae20ff42e0f7c434b9353637aa44b59fac0d01ea168e89c3e9319`  
Domain root: `2d33d97f437df7c6fe22bb1d1625fc4394d7b73cea1de583811c3352e6194823`

V17 preserves the exact V16 transition as its immutable predecessor. Its only
Phase 5-bound runtime delta is the shutdown-reason normalization in `main.py`.
Gemini Live continuity reasons (`provider-reconnect`,
`provider-session-rotation`, and `provider-resumption-reset`) are translated to
the canonical Phase 5 `reconnect` terminal reason before the governed bridge is
closed. Unknown noncanonical shutdown reasons fail into canonical `shutdown`.

This correction does not replace the Gemini Native Audio provider, Charon
voice, mission engine, permission broker, memory authority or HUD. It prevents
a valid provider rotation or cancellation from stranding Phase 5 cleanup and
causing `RuntimeCleanupError` during a normal application close.

Focused lifecycle, rotation and Phase 6 integration tests pass at source. A
traceable rebuild, exact installed inventory, real provider connection, normal
window close and absence of cleanup errors are required before V17 replaces
V16 operationally.
