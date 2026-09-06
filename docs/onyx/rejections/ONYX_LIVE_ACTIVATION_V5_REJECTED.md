# Onyx Live Activation V5 — Rejection Record

Status: **REJECTED — BYTES PRESERVED — NEVER LIVE**

V5 corrected the production audio MIME contract, contained Gemini Live provider
failures, retained the local HUD/dashboard lifecycle, and enforced a single
setup surface. It was rejected before live activation because two adversarial
contracts remained incomplete:

- Tool replay identity was keyed by `(call_id, name)` instead of solely by the
  exact provider `call_id`; argument identity was not bound, concurrent
  conflicts were not fail-closed, and completed IDs were retained without the
  required bounded replay window.
- Circuit numeric configuration admitted booleans/non-finite values and had no
  hard upper bounds. Manual recovery could mutate circuit state from a UI
  thread rather than submitting an acknowledged command to the owning event
  loop.

All V1-V5 candidate, test, checkpoint, and manifest bytes remain unchanged.
Activation V6 is a separate wrapper candidate and requires an independent gate
before any live activation.
