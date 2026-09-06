# Owner Profile V3 Checkpoint

Date: 2026-07-22

Status: implementation candidate, isolated and default-off. Rejected V1 and
V2 remain byte-for-byte frozen. V3 is not imported by startup, UI, dashboard,
permission broker, QML/Orb, providers, or the live Onyx process.

## V2 rejection closure

- Before any set/forget config mutation, V3 writes and verifies a durable
  recovery marker in the existing preference-memory store. The marker contains
  the verified prior display name and operation, with no credential data.
- Compensation is marked required before invoking the config writer. Every
  config-write exception is treated as possibly post-commit and triggers
  independent restoration attempts for both config and owner preference
  memory.
- After compensation, both stores are read back against the verified prior
  value. A mismatch, read failure, or marker-clear failure makes compensation
  incomplete and preserves `DEGRADED` state.
- An incomplete rollback retains the durable recovery marker. A new authority
  on restart consumes that marker, restores the prior value to both stores,
  verifies them, and only then clears the marker and health latch.
- Raised `set` and `forget` operations are therefore not accepted as the new
  durable owner identity after restart.
- Rollback diagnostics are structured `stage + root error type` entries. The
  defined stages include `rollback-config`, `rollback-memory`,
  `rollback-readback-config`, `rollback-readback-memory`, and
  `rollback-clear-marker`.
- Every original and rollback diagnostic is normalized through chained-cause
  unwrapping. Snapshot diagnostics retain only sanitized operation/stage/type
  metadata; no exception message, name, config value, or memory content.

## Preserved positive behavior

- Unknown placeholders, literal non-translatable English `Sir`, ask-once first
  contact, prompt-safe Unicode NFC names, corrections, forget, restart,
  config/memory reconciliation, and settings preservation remain covered.
- Any exceptional divergence publishes and latches `DEGRADED`; only verified
  `reconcile()` can restore healthy state.

## Verification snapshot

- V3 focused/adversarial: `10 passed`.
- V1 + V2 + V3 + existing memory-store suite: `68 passed`, `15 subtests
  passed`.
- Ruff: passed for V3 core and tests.
- Python bytecode compilation: passed for V3 core and tests.
- Static test found no V3 import in `main.py`, `ui.py`,
  `dashboard/server.py`, or `core/permission_broker.py`.
- Tests use temporary config and SQLite stores; live owner data was untouched.

The Pytest cache emitted one environmental warning from the pre-existing
access-denied workspace cache. It did not affect collection or results.

## Frozen hashes

V3 candidate:

- `core/owner_profile_v3.py`:
  `abf5e990b875a4ed04e9e9fed15eb550f972facf02b060683aa1e3abe88e4d16`
- `tests/test_owner_profile_v3.py`:
  `f327a01f7d82a5df2d5e05d2bde70e3b89f06c6c4f69011e0ee257521033fe38`

Rejected historical candidates:

- V1 core: `b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754`
- V1 tests: `fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035`
- V2 core: `12c459c1d34376a121e7a837d6dbeca365967c69affdc12b7d3e18ea1c76cd73`
- V2 tests: `76f0481f91b82b650ece00d86ad0bfffe21fa4020e46d8e3dcaaaf7e36832714`

## Honest limitations

- Candidate-only; independent acceptance and a separately gated integration
  are still required.
- Cross-store atomicity is a durable recovery protocol over two atomic stores,
  not a native distributed transaction.
- Recovery requires the preference-memory store containing the marker to
  become readable and writable. Until then, the authority remains degraded.
- Raw local exceptions are retained only on the thrown composite exception for
  programmatic diagnosis; snapshots expose sanitized metadata only.

Machine-readable manifest:
`docs/onyx/checkpoints/owner-profile-v3/manifest.json`

