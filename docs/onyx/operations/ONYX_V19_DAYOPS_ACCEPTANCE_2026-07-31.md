# Onyx V19 DayOps acceptance — 2026-07-31

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V19 source
> evidence; it does not prove live Graph access for the current candidate. See
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Status: source accepted for Windows packaging; live Microsoft account evidence pending.

## Delivered contract

- V19 preserves the V18.1/V17/V16 runtime chain and adds a persistent,
  identity-bound DayOps layer.
- The public profile contains only Microsoft public-client identifiers, the
  selected account address, time-zone names and deterministic Governance
  workspace bindings.
- The profile is written atomically and authenticated with a 32-byte HMAC key
  held by the native operating-system vault.
- Refresh tokens remain exclusively in the accepted native credential vault.
  Passwords, client secrets and device codes are neither accepted nor
  persisted.
- Process environment variables are no longer DayOps authority after V19
  onboarding. The profile is reloaded and revalidated for every authorized
  read.
- The existing Governance V16 workspace is required and is never created,
  renamed or reclassified by DayOps.
- The trusted desktop surface exposes status, connect, device-code sign-in,
  cancel, disconnect and a direct read-only Today Brief. Device instructions
  never enter the model transcript or general application log.
- The public Today Brief contains no raw Graph event or message identifier.
  Domain-separated full SHA-256 `source_ref` values preserve private identity
  for stable deduplication, and the canonical public snapshot digest covers
  those references plus every event, message and coverage field.
- Graph importance accepts only the exact `low`, `normal` and `high` enum
  values; invalid records are dropped and disclosed rather than promoted.
- Both the 12,000-character dialog and 4,000-character HUD projection append a
  visible `[TRUNCATED: ...]` marker with available coverage state.
- Model-initiated `day_brief_read` is classified by Governance V16 as an exact,
  confidential, low-risk read. It receives a bounded, audited grant and does
  not open a confirmation window for each query. The direct Today Brief button
  is itself an explicit local owner gesture and likewise needs no additional
  approval. No DayOps mutation receives this authority.

## Source evidence

- Persistent profile, provisioning, Graph factory and live-integration gate:
  30 tests passed.
- Connection controller, V19 activation, UI bridge, V18 regression and
  Document Intake bridge gate: 72 tests passed.
- Package-hygiene gate: 10 tests passed.
- Ruff passed for every new V19 module, launcher and test.
- Source V19 host preflight passed with zero declared network, provider and
  process calls.
- Source disconnected DayOps smoke passed with five trusted UI callbacks,
  `configuration_required`, read-only status, zero network/provider calls and
  zero UI prompts.
- The integrated V19 persistence/UI plus Governance V16 regression gate passed
  77 tests, including repeated natural-language DayOps reads reusing one exact
  bounded grant without invoking the trusted confirmation callback.
- The 2026-08-01 DayOps closure gate passed 47 focused tests and 117
  proportional DayOps/Graph/V19 regression tests. Pycompile and Ruff F/E9/S
  passed on the changed source surfaces; the existing whole-file `ui.py`
  formatting debt remains outside this scoped security closure.

## Security and rollback

- Unknown, extra or secret-named onboarding fields are rejected.
- Profile payload/MAC tampering, duplicate fields, identity drift,
  symlink/reparse paths and invalid vault material fail closed.
- V19 callback rollback restores the exact predecessor only while the V19
  callback is still the current owner; callbacks installed by a later owner
  are preserved.
- V19 rollback removes only V19 state before delegating to the accepted V18.1
  rollback chain.

## Residual evidence required

- Register or supply the Cyryx Labs Microsoft Entra public-client application
  ID, select tenant mode and complete one owner device-code consent for
  `Calendars.Read` and `Mail.Read`.
- Execute one live calendar plus unread-mail read and retain only redacted
  result metadata; no message body, token or device code may enter evidence.
- Build, install and run the packaged V19 preflight and disconnected smoke on
  Windows. Authenticode signing, clean-machine Windows validation and native
  macOS/Linux builds remain separate release gates. The current macOS/Linux
  normal bootstrap and native smoke both terminate at the capability-limited
  portable V8 fallback; they must not be represented as V15-V19 parity until a
  portable current activation is implemented and independently verified.
  The separate default-off portable-current negative-boundary gate reaches only
  `pre_v16` and proves safe unavailability; it records no V15/V19 execution.

This record does not claim a live Microsoft provider result until the owner
completes the one-time account consent and the redacted live gate passes.
