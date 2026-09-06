# Owner Profile V2 Checkpoint

Date: 2026-07-22

Status: implementation candidate, isolated and default-off. V1 is preserved
byte-for-byte as a rejected historical candidate. V2 has no startup, UI,
dashboard, permission-broker, QML/Orb, provider, or live-process wiring.

## Rejection closure

- `_publish(..., reconciled=False)` now always publishes `DEGRADED`, whether a
  name is known or unknown.
- Any read, write, verification, or compensation exception latches degraded
  health before it can escape. A finally-safe path publishes the degraded
  snapshot even when one or both rollback operations fail.
- Config and memory rollback attempts are independent; failure of the first
  cannot prevent the second.
- The sanitized `last_failure` records operation, exact stage, root-cause type,
  all rollback root-cause types, and possible divergence without retaining
  error messages or store contents.
- When compensation also fails, `OwnerProfileTransactionError` preserves the
  original root exception, the safe operation wrapper, and every rollback root
  exception as programmatic attributes while presenting a content-free public
  message.
- A later successful set, correction, or forget cannot silently heal latched
  health. Only `reconcile()` can clear the latch, after repairing and reading
  back both the config and preference-memory values.
- Reconciliation read or repair failures return a degraded snapshot and retain
  the last known safe address where possible. First-contact prompting is
  suppressed while storage health is degraded.

## Preserved V1 behavior

- Blank values, placeholders, `Sir`, and translated honorifics are not owner
  identities.
- The fallback remains literal English `Sir` with the
  `literal-non-translatable` policy.
- First contact asks once through an explicit state machine.
- Unicode NFC names, correction, forget, restart recovery, config-primary
  reconciliation, preference-memory recovery, prompt safety, and settings
  preservation remain covered.

## Verification snapshot

- V2 focused/adversarial: `11 passed`.
- V1 + V2 + existing memory-store suite: `58 passed`, `15 subtests passed`.
- Ruff: passed for the V2 core and test.
- Python bytecode compilation: passed for the V2 core and test.
- Static test found no V2 import in `main.py`, `ui.py`,
  `dashboard/server.py`, or `core/permission_broker.py`.
- Live config and memory were not used by the tests.

The Pytest cache emitted one environmental warning because the pre-existing
workspace cache path is access-denied. It did not affect collection or results.

## Frozen hashes

V2 candidate:

- `core/owner_profile_v2.py`:
  `12c459c1d34376a121e7a837d6dbeca365967c69affdc12b7d3e18ea1c76cd73`
- `tests/test_owner_profile_v2.py`:
  `76f0481f91b82b650ece00d86ad0bfffe21fa4020e46d8e3dcaaaf7e36832714`

Rejected V1 preserved exactly:

- `core/owner_profile_v1.py`:
  `b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754`
- `tests/test_owner_profile_v1.py`:
  `fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035`

## Honest limitations

- Candidate-only; an independently accepted integration is still required.
- File-plus-SQLite durability remains two atomic stores with compensating
  rollback, not a native distributed transaction.
- Raw exception objects retained by the composite exception are intended for
  local programmatic inspection only. The snapshot and sanitized diagnostic
  deliberately expose no error messages.
- An unrecoverable store outage intentionally keeps the authority degraded and
  suppresses first-contact prompting until reconciliation succeeds.
- Independent functional, integrity, and quality review remains required.

Machine-readable manifest:
`docs/onyx/checkpoints/owner-profile-v2/manifest.json`

