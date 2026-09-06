# Phase 4 E1-E5 checkpoint candidate R2

Evidence candidate: `VE-P4-EXIT-CANDIDATE-R2-001`  
Input scope: `VE-SCOPE-P4-E1E5-R2-001` plus accepted R10  
Decision: **E6 not performed; activation false; Phase 5 remains blocked**

R1 is preserved as historical/rejected evidence.  Its source scanner could be
bypassed through package imports, aliases and dynamic execution; its manifest
did not mechanically bind itself; its rollback proof exercised only the V1
disabled case; and its pytest command contained a placeholder.  R2 replaces
those claims without changing or activating product code.

## E1 — exact scope and retained blockers

Included: read-only/default-off verification over the accepted R10 product
universe, an adversarial startup-policy scanner, an exact R2 input manifest,
isolated rollback tests and this review package.  No enabled runtime slice is
proposed.

Retained outside any enabled slice:

- M1a canonical Windows policy remains `BLOCKED_BY_PLATFORM` until it passes
  under the intended installed-user token without weakening DACL/capability
  rules.
- Owner M1b review/backfill, startup/owner wiring, credential aliases, browser
  profiles and cross-workspace production operation remain unproved/excluded.
- Connectors/providers/MCP remain access- or implementation-blocked.
- Physical browser/device/LAN and exact installers remain unproved.
- Proprietary/public release remains `BLOCKED_BY_LICENSE`.

## E2 — capability delta

`CAPABILITY_MATRIX.md` records the R2 delta.  M1a stays
`BLOCKED_BY_PLATFORM`; workspace registry, mission context and typed evidence
stay `PARTIAL`.  No capability inherits fixture evidence as production proof.

## E3 — evidence mechanics

`VE-SCOPE-P4-E1E5-R2-001.sha256` contains the exact six input files required by
the R2 verifier.  It requires canonical UTF-8/LF, final LF, lowercase SHA-256,
literal ` *` separator, ordinal paths, a safe relative path, exact set and exact
current bytes.  Negative tests remove/add/mismatch records and corrupt
encoding/order/format.

The manifest deliberately **does not hash itself**.  Generated JSON/JUnit/raw
logs are outputs, not inputs, and are hashed by
`phase4-e1-e5-r2.bundle.json`.  The manifest SHA in the candidate bundle is an
unaccepted observation, not a trusted anchor.  Only a later E6 reviewer may
record that SHA externally in `VERIFICATION_EVIDENCE.md` while accepting or
rejecting the checkpoint.

The exact pytest nodes are newline-delimited in
`tests/phase4_e1e5_r2_selection.txt`.  The reproducible PowerShell command is:

```powershell
$nodes = Get-Content tests/phase4_e1e5_r2_selection.txt | Where-Object { $_ -and -not $_.StartsWith('#') }
& '.\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider --basetemp .phase4-e1e5-r2-test --junitxml docs/onyx/checkpoints/phase4-e1-e5/phase4-r2-safety.junit.xml $nodes
```

The raw pytest output, JUnit, source-gate JSON and static-gate raw output are
hashed with their durations/counts in the bundle.  R10's accepted 382/7 result
is referenced rather than rerun or widened.

## E4 — tested safety and rollback boundary

Startup policy is fail-closed:

- static enhanced imports, including `from core import control_plane_v5`, deny;
- `__import__`, `importlib.import_module`, `runpy.run_module/run_path`,
  `exec`, `eval` and `compile` calls are forbidden in startup regardless of
  target, including aliases and literal `getattr` resolution;
- literal reads/opens of an enhanced module source deny, including aliased
  `pathlib.Path` expressions;
- external/missing scanner paths produce typed verification failures with a
  safe absolute label, never an uncaught `relative_to` error.

The tests exercise every one of the eight flag readers through accepted
enable -> explicit disable -> exact environment restoration.  This proves
reader semantics only; it does **not** claim eight service lifecycle tests.

For V1 alone, an isolated non-owner root is initialized while enabled, closed,
disabled, then re-enabled/reopened.  Disable preserves the exact file set and
SHA-256 bytes, deletes nothing and creates no production owner path.  Reopen
validates the preserved schema.  Existing R10 tests provide proportional
failure, cancellation, restart, unknown-outcome and isolation evidence.

Rollback remains: keep flags false, detach any later integration before
disable, preserve sidecars for diagnosis/export, reconcile unknown outcomes
before retry and delete only after verified export plus explicit owner action.

## E5 — checkpoint inventory

R2 adds zero product schema statements, API methods, event types, migration
rows, provider calls, dependencies or production imports.  It references the
accepted inventory: v1->v2 M1a/M1b with two named migrations; isolated v3;
isolated MissionContext v4; and isolated P4.4 v5/record-v3 typed contracts.

- ADR/API/event delta: none; ADR-0001/0002 remain controlling.
- Threat/data delta: scanner and verifier only; no new authority/identity/data
  store, no secret/owner/provider payload and no owner write.
- License/cost delta: no dependency/distributable/API/token/financial cost.
- Resource impact: bounded local verifier/tests; measured duration and output
  bytes are in the bundle.
- Reconcile/revoke: retain unknown records, never blind retry; no active grant
  or connector exists to revoke in this candidate.

Recommended review state: keep every Phase 4 flag off until retained blockers
close.  This candidate cannot accept itself, activate Phase 4 or unlock Phase 5.
