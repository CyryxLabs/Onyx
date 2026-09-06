# Phase 5 Runtime Core V10 Checkpoint

Date: 2026-07-22

Status: implementation candidate, isolated and default-off. This checkpoint is
not an external acceptance record and does not wire V10 into `main.py`, `ui.py`,
`dashboard/`, startup, or the live Onyx process.

## Scope

- Preserves the V1-V9 candidate files as independent historical artifacts.
- Makes each termination acknowledgement an authoritative transaction: token
  consumption, pending/failure truth, final outcome, completion, and waiter
  notification commit under one condition lock before telemetry.
- Treats acknowledgement, completion, and timeout events as bounded
  best-effort telemetry. Event faults cannot roll back cleanup truth or escape
  to the host; they are recorded separately in a 128-entry diagnostic ring.
- Resolves a zero-pending termination deterministically and waits with a closed
  monotonic `Condition.wait_for` predicate. A timeout never emits an empty
  reason.
- Requires exact immutable 32-byte decision and termination keys before an
  authority epoch exists. Byte arrays, subclasses, short/long/empty values,
  provider exceptions, malformed token material, duplicate tokens, and
  incomplete/mismatched plan graphs fail construction.
- Precomputes and validates every four-action terminal plan and keyed opaque
  token. Termination and acknowledgement never call entropy, HMAC, or hashing.
- Latches hashing, HMAC, digest, and constant-time comparison faults as a
  sticky `crypto` component failure, advances the authority epoch, clears all
  decision seals, and returns `EXPLICIT`/`False` without leaving the runtime
  `READY`. The instance cannot heal cryptographic authority; recovery requires
  a newly validated runtime instance.
- Preserves the V9 DLP, identifier grammars, exact local-catalog envelope,
  component leases/sequences, projection bounds, and host-owned cleanup plan.

## Verification snapshot

- V10 focused: `103 passed`.
- Cumulative runtime V1-V10 + Session Grants R11 + component adapters V1-V3 +
  regressions: `1111 passed`, `221 subtests passed`.
- Ruff: passed for the V10 core and test.
- Python bytecode compilation: passed for the V10 core and test.
- Microbenchmark (2000 evaluate/consume operations): p50 `3.810200 ms`, p95
  `6.635800 ms`, maximum `18.153800 ms`.
- Termination microbenchmark: 256 transitions in `328.551400 ms` total,
  `1.283404 ms` mean, zero worker-thread delta.
- Static live-surface search over `main.py`, `ui.py`, `dashboard`, `scripts`,
  `packaging`, and sibling `core` files found no V10 import or flag reference.

The Pytest cache emitted one environmental warning from the existing local
cache configuration. It did not affect collection or test results.

## Frozen implementation hashes

- `core/phase5_runtime_v10.py`:
  `f80fd636e145e669cc1ea76cfc024fcc5d385451cc1ef8624f7c9d8e0ac3f439`
- `tests/test_phase5_runtime_v10.py`:
  `b2a6d9524d2d5d1b85af3325462f7bd28793180cee0ea4295d6600750615cfff`

## Honest limitations

- V10 is deliberately not live-wired and grants no production authority.
- Cleanup remains host-owned: the core issues and tracks the bounded plan but
  does not execute cleanup callbacks.
- The crypto latch is intentionally irreversible within one instance; a host
  must replace the runtime after fixing the cryptographic provider.
- The diagnostic ring is bounded and discards its oldest record after 128
  telemetry faults.
- Initial termination retirement remains a distinct fail-closed transition; an
  internal retirement fault produces `TERMINATION_ERROR` with the complete
  host-readable plan. Ack/completion/timeout telemetry faults do not.
- The DLP scanner is defensive pattern recognition, not proof that arbitrary
  prose can never encode a secret.
- External functional, integrity, and quality review is still required before
  acceptance or integration.

Bundle root:
`docs/onyx/checkpoints/phase5-runtime-v10/`

Machine-readable manifest:
`docs/onyx/checkpoints/phase5-runtime-v10/manifest.json`
