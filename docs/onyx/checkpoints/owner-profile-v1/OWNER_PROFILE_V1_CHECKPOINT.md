# Owner Profile V1 Checkpoint

Date: 2026-07-22

Status: implementation candidate, isolated and default-off. This checkpoint
does not wire the candidate into `main.py`, `ui.py`, `dashboard/`, the
permission broker, QML/Orb surfaces, startup, or the live Onyx process.

## Scope

- Introduces one owner-profile authority for addressing and first-contact
  state instead of treating the fallback honorific as owner identity.
- Treats blank, placeholder, `Sir`, and translated-honorific settings as an
  unknown name. The fallback is the literal English `Sir`, explicitly marked
  `literal-non-translatable`.
- Emits the first-contact name question once per unnamed contact through the
  explicit `UNKNOWN -> AWAITING_NAME -> KNOWN` state machine.
- Persists a validated display name atomically in the existing non-secret
  `owner_name` setting and mirrors it to semantic preference memory under
  `preferences/owner_display_name`.
- Reconciles restart drift deterministically: a valid config value is primary;
  valid preference memory recovers a blank/placeholder config; invalid copies
  are removed. A repair failure is exposed as `DEGRADED` rather than hidden.
- Uses compensating rollback if either durable store or read-back verification
  fails during set, correction, or forget.
- Preserves Unicode names with NFC normalization, bounded whitespace, and a
  prompt-safe personal-name character grammar. Controls, markup, multiline
  content, emoji, and instruction-shaped punctuation are rejected.
- Does not log profile data. Memory audit metadata contains only the existing
  content-free memory action/source fields; the chosen display name is stored
  only in the two intended durable locations.

## Verification snapshot

- Focused test suite: `27 passed`.
- Candidate plus existing memory-store suite: `47 passed`, `15 subtests
  passed`.
- Ruff: passed for the candidate core and test.
- Python bytecode compilation: passed for the candidate core and test.
- Static live-surface test verifies no import from `main.py`, `ui.py`,
  `dashboard/server.py`, or `core/permission_broker.py`.
- Tests use isolated temporary configuration and SQLite databases; the live
  owner setting and live memory were not changed.

The Pytest cache emitted one environmental warning because the pre-existing
workspace cache path is access-denied. It did not affect test collection or
results.

## Frozen implementation hashes

- `core/owner_profile_v1.py`:
  `b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754`
- `tests/test_owner_profile_v1.py`:
  `fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035`

## Later integration points

1. `main.py::_load_owner_name`: replace direct JSON interpretation with the
   authority snapshot so placeholders never become identities.
2. `main.py::OnyxLiveSession._build_config`: insert `prompt_directive()` and
   send `begin_contact()` only once after a session becomes interactive.
3. `main.py::OnyxLiveSession.speak_error`: use `address()` so the fallback is
   always literal English.
4. `ui.py::SetupOverlay` and `OnyxWindow._on_setup_done`: display placeholders
   as blank and persist first answers/corrections through `set_name()` rather
   than a second config writer.
5. Add owner-only local intents for `correct_name()` and `forget_name()`; no
   dashboard or remote mutation endpoint is needed.

## Honest limitations

- Candidate-only: no production behavior changes until a separately reviewed
  integration imports and constructs this authority.
- Cross-file/SQLite atomicity is implemented by two atomic stores plus verified
  compensating rollback; it is not a native distributed transaction.
- If rollback itself fails, the operation raises a reconciliation-required
  error. A new authority can then run deterministic `reconcile()`.
- The strict display-name grammar favors prompt safety; exotic aliases using
  symbols outside letters, marks, numbers, name punctuation, and spaces need an
  explicit future policy decision.
- Independent functional, integrity, and quality review is still required
  before live integration.

Machine-readable manifest:
`docs/onyx/checkpoints/owner-profile-v1/manifest.json`
