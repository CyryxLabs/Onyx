# Phase 5 Runtime Core V9 Checkpoint

Date: 2026-07-22

Status: implementation candidate, isolated and default-off. This checkpoint is
not an external acceptance record and does not wire V9 into `main.py`, `ui.py`,
`dashboard/`, startup, or the live Onyx process.

## Scope

- Preserves the V1-V8 candidate files as independent historical artifacts.
- Revokes runtime authority before any termination-plan transition work.
- Precomputes every bounded host cleanup plan and opaque token during
  initialization, before the authority epoch exists. Initialization fails if
  token material cannot be produced.
- Uses only prevalidated immutable plan objects during termination; no builder,
  fallback, entropy, HMAC, cleanup callback, or schema validation participates
  in the transition.
- Keeps a complete host-readable four-action plan and a non-READY fail-closed
  state if an ordinary internal exception occurs after revocation.
- Removes the cross-field DLP `len(value) <= 16` exemption. All label/value
  pairs are scanned within a cumulative 8192-byte budget and a 1024-byte
  per-field ceiling.
- Rejects credential-shaped identifiers (`sk-proj`, GitHub tokens, AWS access
  keys, Google API keys, bearer/basic shapes, JWTs, and natural secret labels)
  while preserving ordinary IDs and explicit UUID/ULID/digest grammars.
- Makes `termination_actions` immutable after construction because its plans
  are init-time authority prerequisites.

## Verification snapshot

- V9 focused: `80 passed`.
- Cumulative runtime V1-V9 + Session Grants R11 + component adapters V1-V3 +
  regressions: `1008 passed`, `221 subtests passed`.
- Ruff: passed for the V9 core and test.
- Python bytecode compilation: passed for the V9 core and test.
- Microbenchmark (2000 evaluate/consume operations): p50 `3.731250 ms`, p95
  `6.447300 ms`, maximum `25.818100 ms`.
- Termination microbenchmark: 256 transitions in `282.554 ms` total,
  `1.103727 ms` mean, zero worker-thread delta.
- Static wiring search over `main.py`, `ui.py`, `core`, `dashboard`, `scripts`,
  `packaging`, and `docs`: no V9 import or flag reference outside this bundle.

The Pytest cache emitted one environmental warning because the existing
`.pytest_cache` directory is not writable. It did not affect collection or test
results.

## Frozen implementation hashes

- `core/phase5_runtime_v9.py`:
  `55130494afe02bbbd52acad4d9b4e12cf09e69aeba51592b0bd97c93ccdf0da1`
- `tests/test_phase5_runtime_v9.py`:
  `99de4fc6cf1bcefa32de48be6d76f0753980582cb461ebd203f44a6c6cd1406c`

## Honest limitations

- V9 is deliberately not live-wired and grants no production authority.
- Cleanup remains host-owned: the core issues and tracks the bounded plan but
  does not execute cleanup callbacks.
- The DLP scanner is defensive pattern recognition, not proof that arbitrary
  prose can never encode a secret.
- External functional, integrity, and quality review is still required before
  acceptance or integration.

Bundle root:
`docs/onyx/checkpoints/phase5-runtime-v9/`

Machine-readable manifest:
`docs/onyx/checkpoints/phase5-runtime-v9/manifest.json`
