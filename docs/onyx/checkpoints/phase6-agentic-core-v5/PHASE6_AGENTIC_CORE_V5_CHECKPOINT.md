# Phase 6 Agentic Core V5 checkpoint

Status: **isolated candidate, strict default-off, not externally accepted, not live**

Date: 2026-07-22  
Platform: Windows 11 `10.0.26200`, Python `3.13.7` x64

## Prior disposition and preservation

V1-V4 remain rejected and frozen. The additive V4 rejection record is
`docs/onyx/rejections/PHASE6_AGENTIC_CORE_V4_REJECTION.md`. V5 does not edit an
artifact listed by the V4 manifest.

## Minimal V5 correction

- A lexical state machine replaces V4's whole-string SQL lowercasing/collapse.
- Single/double/backtick/bracket quotes, blob payloads and line/block comments
  preserve exact bytes and escape spelling.
- Only outside-token whitespace and unquoted SQL word case are normalized.
- Unterminated lexical states fail closed.
- Full `sqlite_master` token streams plus V4's complete PRAGMA schema inventory
  authenticate both V5 coordination and the exact-input ledger before writes.
- Same-name CHECK literal case/whitespace/escape, quoted identifier, stored
  comment and index-order mutations fail without changing database bytes.
- A specifically tested SQLite outside-whitespace rewrite reopens successfully
  as benign and equivalent.
- All V4 recovery, fencing, full-input binding, process termination/lifecycle,
  compute budgeting and compaction behavior is inherited unchanged.
- The V5 facade passes plan, materialize, approve, isolated execute, isolated
  verify and close end-to-end.

## Verification before manifest freeze

Focused V5 excluding only the not-yet-created manifest test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v5-focused-a tests\test_phase6_agentic_core_v5.py -k "not checkpoint_manifest"
```

Result: **25 passed, 1 deselected in 2.18s**.

Cumulative V1-V5, retaining the already-frozen V2-V4 manifest tests and
deferring only V5's manifest:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v5-cumulative-a tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py tests\test_phase6_agentic_core_v5.py -k "not checkpoint_manifest or test_phase6_agentic_core_v2 or test_phase6_agentic_core_v3 or test_phase6_agentic_core_v4"
```

Result: **103 passed, 1 deselected in 35.73s**. This preserves the complete
frozen V4 cumulative closure of 78 tests and adds 25 V5 tests.

Complete stable boundary before manifest:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v5-regression-a tests\test_missions.py tests\test_mission_tools.py tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py tests\test_phase6_agentic_core_v5.py -k "not checkpoint_manifest or test_phase6_agentic_core_v2 or test_phase6_agentic_core_v3 or test_phase6_agentic_core_v4"
```

Result: **215 passed, 44 subtests passed, 1 deselected in 62.43s**. This
preserves the complete frozen V4 stable closure of 190 tests and 44 subtests.

After manifest creation, cumulative V1-V5 passed **104 tests in 34.09s** with
no filter or deselection. The complete stable boundary then passed **216 tests
and 44 subtests in 57.84s**, also with no filter or deselection.

Static gates: Ruff lint and format pass for V5 code/tests; Python byte
compilation passes.

Performance on the stated host:

- 2,000 quote/comment-aware tokenizations: median `0.013 ms`, p95 `0.020 ms`,
  maximum `0.037 ms`.
- 500 complete in-memory V5 schema signatures: median `0.424 ms`, p95
  `0.702 ms`, maximum `0.845 ms`.

## Default-off and scope evidence

- Exact `ONYX_PHASE6_AGENTIC_CORE_V5=true` is required.
- No V5 import exists in `main.py`, `ui.py` or `dashboard/server.py`.
- No live configuration, MissionStore, accepted Phase 5, permission broker,
  Orb/HUD, owner profile or provider route was changed.
- No process restart, feature activation, commit, push or deployment occurred.

## Honest remaining gates

1. V5 remains unaccepted until independent functional, integrity and quality
   review validates its final bytes and manifest.
2. V4's spawn-pickleable, return-only callback constraint remains.
3. Provider planning, Gemini Live parity, accepted Phase 5 catalog binding,
   planner memory and installed external agents remain separate slices.
4. No Phase 6 exit or live activation is claimed.
