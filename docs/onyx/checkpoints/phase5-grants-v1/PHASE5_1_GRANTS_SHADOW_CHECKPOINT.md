# Phase 5.1 bounded session grants — shadow checkpoint

Status: implementation candidate; default off; not accepted or activated.

## Scope

This checkpoint implements only the first Phase 5 slice: a typed, process-local
session-grant store and exact shadow evaluator. It does not import from startup,
UI, dashboard, missions or provider code. It cannot suppress the current trusted
permission callback and every decision has `callback_required=true` and
`authority_granted=false`. Approval inbox, Capability Nexus, connectors and live
permission-broker wiring are explicitly outside this checkpoint.

The sole feature flag is `ONYX_GRANT_EVALUATOR`. Only `1` and `true`
(case-insensitive, surrounding whitespace ignored) opt in. All other and missing
values are off.

## Enforced limits

- Schema version: `1`; policy version: `onyx-approval-v1`.
- Lifetime: at most 24 hours; restart restores zero grants.
- Target set: 1–32 exact lowercase SHA-256 digests; no duplicates.
- Risk: low or medium only; high, critical and `always_explicit` always deny.
- Uses: 1–10,000.
- Cost: integer micro-units, 0–10^15, checked per action and in aggregate.
- Exact principal, authenticated session, workspace, optional mission,
  capability, tool, operation, payload digest, action digest and audit head.
- Digest/identity/target comparisons use `hmac.compare_digest`.
- Expired, not-yet-valid, future/stale request, policy drift, audit-head drift,
  revoke, kill, audit-unhealthy, ambiguity and exhaustion deny.

The action digest reproduces the canonical algorithm of
`core.permission_broker.build_request`; a parity test freezes that boundary.
Only content digests and bounded identifiers enter the grant store—no payload,
target content, credential, provider call or owner data is read or persisted.

## Fresh verification

Environment: Python 3.13.7, pytest 9.1.1,
Windows-11-10.0.26200-SP0. Base commit:
`b2dc0b21f487013cebec34bb148ffb1aeb02611a` with an intentionally dirty shared
worktree; no commit or push was made.

Focused command:

```powershell
$base = Join-Path $env:TEMP ('onyx-p51-grants-final-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_session_grants_v1.py --basetemp $base --junitxml docs\onyx\checkpoints\phase5-grants-v1\phase5-grants-v1.junit.xml
```

Result: 41 passed, 0 failed, 0 errors, 0 skipped; exit 0; wall report 0.28 s.
JUnit SHA-256:
`a198efd2bc2a06e1c07a38fbb1bc9949b5db7af583b4b69aa9e28508f73d788a`.

Static commands, all exit 0:

```powershell
.\.venv\Scripts\python.exe -m ruff check --select F,E9 core\session_grants_v1.py tests\test_session_grants_v1.py
.\.venv\Scripts\python.exe -m py_compile core\session_grants_v1.py tests\test_session_grants_v1.py
$files = @('core/session_grants_v1.py','tests/test_session_grants_v1.py','docs/onyx/VE-SCOPE-P51-GRANTS-V1-001.sha256','docs/onyx/checkpoints/phase5-grants-v1/PHASE5_1_GRANTS_SHADOW_CHECKPOINT.md')
foreach ($file in $files) { $out = git diff --no-index --check -- NUL $file 2>&1; if ($out) { $out; exit 1 } }
```

Source/evidence manifest: `VE-SCOPE-P51-GRANTS-V1-001.sha256` (10 entries).

## Rollback and limitations

Rollback is the default: leave/unset `ONYX_GRANT_EVALUATOR`. No database or
owner-state restoration is needed because this store has no persistence API.
Dropping the process or constructing a new store removes every session grant.

This is shadow infrastructure, not a Phase 5 exit, approval bypass, persisted
grant ledger, autonomy envelope, approval inbox or live capability. Phase 5
activation still requires shadow replay proving zero over-grant, independent
review, the remaining Phase 5 slices and E1–E6 acceptance.
