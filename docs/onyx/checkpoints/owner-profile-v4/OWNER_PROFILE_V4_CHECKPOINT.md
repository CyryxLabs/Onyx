# Owner Profile V4 Checkpoint

Date: 2026-07-22

Status: isolated, default-off implementation candidate. Rejected V1-V3 are
preserved byte-for-byte. V4 has no startup, UI, dashboard, permission-broker,
QML/Orb, provider, or live-process wiring.

## V3 rejection closure

- V4 replaces marker-deletion semantics with a durable decision journal:
  `PREPARED -> COMMITTED` for success or `PREPARED -> COMPENSATED` for a failed
  operation restored to its verified prior value.
- `PREPARED` contains journal ID, operation, prior name, and target name before
  owner config or owner preference memory is mutated.
- Config and owner-memory target values are written and bilaterally verified
  before the journal may become `COMMITTED`.
- A journal write exception is read back. A post-commit exception with an exact
  `COMMITTED` readback is success; an observed `PREPARED` decision is aborted
  toward the prior value. An unreadable decision remains degraded and is left
  for restart resolution rather than being overwritten.
- Before `COMMITTED`, failure drives both stores to the prior value. Verified
  compensation is durably recorded as `COMPENSATED`; incomplete compensation
  retains `PREPARED` as the recoverable restart instruction.
- Restart resolution drives `PREPARED` and `COMPENSATED` to prior, and
  `COMMITTED` to target, with bilateral readback before healthy publication.
- Journal deletion is garbage collection only. Cleanup errors before deletion,
  after deletion, or with ambiguous deletion never roll back, raise, or change
  an already durable `COMMITTED`/`COMPENSATED` decision.
- Prior reconciliation failures preserve their original operation, stage, and
  unwrapped root error type when a subsequent set/forget is refused.

## Tested crash and fault boundaries

- Restart after `PREPARED` only.
- Restart after target config but before target memory.
- Restart after both targets but before `COMMITTED`.
- Restart after durable `COMMITTED` before cleanup.
- Restart after durable `COMPENSATED` before cleanup.
- Cleanup exception before and after journal deletion.
- `COMMITTED` decision write exception before and after underlying commit.
- Target readback failure leaving recoverable `PREPARED`.
- `COMMITTED` recovery readback failure retaining the committed journal.
- Corrupt journal/prior-reconcile root-stage preservation.

## Preserved behavior

- Unknown placeholders, literal non-translatable English `Sir`, ask-once first
  contact, Unicode NFC names, correction, forget, restart, prompt safety, and
  config/preference-memory reconciliation remain covered.

## Verification snapshot

- V4 focused/adversarial: `16 passed`.
- V1-V4 plus existing memory-store suite: `84 passed`, `15 subtests passed`.
- Ruff and Python bytecode compilation: passed for V4 core and tests.
- Static test found zero V4 imports across live application surfaces.
- Temporary config and SQLite stores were used; live owner data was untouched.

The existing access-denied Pytest cache emitted one environmental warning; it
did not affect collection or results.

## Frozen hashes

V4 candidate:

- Core: `a3ab381ed50c6fd539b10775ce0058b51c5a06b89bd87b1156e6793f6f438fd5`
- Tests: `ee57cc1f0b629f72cbdd8f7d53bc2fd78451a7524995c5eac74d6e60d043d5f0`

Historical rejected candidates:

- V1 core: `b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754`
- V1 tests: `fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035`
- V2 core: `12c459c1d34376a121e7a837d6dbeca365967c69affdc12b7d3e18ea1c76cd73`
- V2 tests: `76f0481f91b82b650ece00d86ad0bfffe21fa4020e46d8e3dcaaaf7e36832714`
- V3 core: `abf5e990b875a4ed04e9e9fed15eb550f972facf02b060683aa1e3abe88e4d16`
- V3 tests: `f327a01f7d82a5df2d5e05d2bde70e3b89f06c6c4f69011e0ee257521033fe38`

## Honest limitations

- Candidate-only; independent acceptance and separately gated integration are
  still required.
- This is a durable recovery protocol over two atomic stores, not a native
  distributed transaction.
- An unreadable journal decision intentionally remains degraded until the
  preference-memory store becomes readable.
- Post-decision cleanup failures are exposed separately through sanitized
  `last_cleanup_failure`, without changing the committed result.

Machine-readable manifest:
`docs/onyx/checkpoints/owner-profile-v4/manifest.json`

