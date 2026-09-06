# Phase 6 Agentic Core V6 checkpoint

Status: **isolated candidate, strict default-off, not externally accepted, not live**

Date: 2026-07-23  
Platform: Windows 11 `10.0.26200`, Python `3.13.7` x64

## Prior disposition and preservation

V1-V5 remain rejected and frozen. The additive V5 rejection record is
`docs/onyx/rejections/PHASE6_AGENTIC_CORE_V5_REJECTION.md`. V6 does not edit an
artifact listed by the V5 manifest.

## Minimal V6 correction

- Outside literals/comments, only SP, TAB, CR, LF and FF are whitespace.
- Identifier/number classes are explicit ASCII sets.
- Only ASCII A-Z bytes are lowered; every non-ASCII code point is exact.
- Kelvin sign, NBSP, vertical tab, Greek/Cyrillic/fullwidth/sharp-S confusables
  and non-ASCII identifier case are covered by regressions.
- Valid same-name SQLite schemas using declared types `K` and `K` have distinct
  complete signatures. A real `KEAL` type tamper fails before writes with the
  file hash unchanged.
- V5 literal, blob, quoted identifier, escape, comment and unterminated-state
  behavior remains covered.
- Coordination and exact-input ledger retain full PRAGMA authentication.
- V4/V5 compute, process, recovery, fencing, idempotency and compaction closures
  remain inherited and pass end-to-end through V6.

## Verification before manifest freeze

Focused V6 excluding only its not-yet-created manifest:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v6-focused-a tests\test_phase6_agentic_core_v6.py -k "not checkpoint_manifest"
```

Result: **29 passed, 1 deselected in 1.80s**.

Cumulative V1-V6, retaining frozen manifests and deferring only V6's:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v6-cumulative-a tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py tests\test_phase6_agentic_core_v5.py tests\test_phase6_agentic_core_v6.py -k "not checkpoint_manifest or not test_phase6_agentic_core_v6"
```

Result: **133 passed, 1 deselected in 34.94s**. This preserves the complete V5
cumulative closure of 104 tests and adds 29 V6 tests.

Stable boundary before V6 manifest:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v6-regression-a tests\test_missions.py tests\test_mission_tools.py tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py tests\test_phase6_agentic_core_v5.py tests\test_phase6_agentic_core_v6.py -k "not checkpoint_manifest or not test_phase6_agentic_core_v6"
```

Result: **245 passed, 44 subtests passed, 1 deselected in 72.64s**. This
preserves V5's complete 216-test/44-subtest stable closure.

After manifest creation, cumulative V1-V6 passed **134 tests in 64.29s** with
no filter or deselection. The complete stable boundary then passed **246 tests
and 44 subtests in 70.58s**, also with no filter or deselection.

Static gates: Ruff lint/format and Python byte compilation pass.

Performance on the stated host:

- 2,000 Unicode-bearing V6 tokenizations: median `0.038 ms`, p95 `0.091 ms`,
  maximum `0.921 ms`.
- 500 complete V6 schema signatures: median `1.284 ms`, p95 `2.789 ms`,
  maximum `7.584 ms`.

## Default-off and scope evidence

- Exact `ONYX_PHASE6_AGENTIC_CORE_V6=true` is required.
- No V6 import exists in `main.py`, `ui.py` or `dashboard/server.py`.
- No live configuration, MissionStore, Phase 5, permission broker, Orb/HUD,
  owner profile or provider route changed.
- No restart, activation, commit, push or deployment occurred.

## Honest remaining gates

1. V6 remains unaccepted until independent functional, integrity and quality
   review validates final bytes and manifest.
2. V4's spawn-pickleable, return-only callback constraint remains.
3. Provider planning, Gemini Live, Phase 5 catalog binding, planner memory and
   installed external agents remain separate slices.
4. No Phase 6 exit or live activation is claimed.
