# Phase 6 Agentic Core V4 checkpoint

Status: **isolated candidate, strict default-off, not externally accepted, not live**

Date: 2026-07-22  
Platform: Windows 11 `10.0.26200`, Python `3.13.7` x64

## Prior disposition and preservation

V1, V2 and V3 remain rejected and frozen. The additive V3 rejection record is
`docs/onyx/rejections/PHASE6_AGENTIC_CORE_V3_REJECTION.md`. V4 does not edit any
artifact listed by the V3 manifest, including `core/missions.py`.

## V4 corrections delivered

- Existing V4 coordination databases are authenticated by normalized exact DDL
  and complete table/index/FK/trigger PRAGMA signatures before any repair.
  Same-name table, index and trigger mutations fail closed.
- Compute recovery selects only expired deadlines and clears them with exact
  account/token/deadline/generation CAS. A forced renewal between selection and
  CAS remains live. Five expired accounts with `limit=3` clear exactly three.
- Recovery and compaction use declared indexes without a temporary sort. The
  terminal index is exactly `(terminal, updated_at, plan_id)`.
- The strict V4 mission materializer rejects titles over 240 and unknown/missing
  step fields before write, and binds the full canonical caller input digest.
- Spawned non-daemon computation is synchronously terminated and joined at its
  deadline. Explicit close/sentinel/join lifecycle leaves no worker; twelve
  create/invoke/close cycles leave zero thread and child delta.
- Full plan, fenced materialization, approval, process-isolated execution,
  process-isolated verification and close pass end-to-end.
- Real stale-before-create and stale-after-create process races each converge on
  exactly one bound and executable mission.
- Planner, critic, repair planner, runner, verifier and recovery all route
  through the same lineage budget and process executor.

## Verification before manifest freeze

Focused V4, excluding only the not-yet-created manifest test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v4-focused-d tests\test_phase6_agentic_core_v4.py -k "not checkpoint_manifest"
```

Result: **16 passed, 1 deselected in 15.25s**.

Cumulative frozen V1-V3 plus V4, with only manifest tests deferred:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v4-cumulative-b tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py -k "not checkpoint_manifest"
```

Result: **75 passed, 3 deselected in 30.34s**.

Stable boundary before manifest freeze:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v4-regression-a tests\test_missions.py tests\test_mission_tools.py tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py -k "not checkpoint_manifest"
```

Result: **187 passed, 44 subtests passed, 3 deselected in 55.49s**.

After manifest creation, cumulative V1-V4 passed **78 tests in 31.60s** with
no filter or deselection. The complete stable boundary then passed **190 tests
and 44 subtests in 56.57s**, also with no filter or deselection.

One earlier cumulative attempt observed the frozen, rejected V3
`after_create` 100 ms lease-race test fail under process contention. V4 tests did
not fail, and the immediate cumulative rerun plus the stable run passed. V3
remains rejected and unchanged; this checkpoint does not conceal or promote it.

Static gates: Ruff lint and format pass for V4 code/tests and Python byte
compilation passes.

Performance on the stated host:

- 500 compute snapshots: median `1.239 ms`, p95 `1.870 ms`, max `2.230 ms`.
- 500 indexed recovery reads: median `0.978 ms`, p95 `1.321 ms`, max `2.123 ms`.
- 100 warm process IPC calls: median `0.073 ms`, p95 `0.130 ms`, max
  `0.827 ms`.

## Default-off and scope evidence

- Exact `ONYX_PHASE6_AGENTIC_CORE_V4=true` is required.
- No V4 import exists in `main.py`, `ui.py` or `dashboard/server.py`.
- No live configuration, accepted Phase 5, permission broker, Orb/HUD, owner
  profile or provider route was changed.
- No process restart, feature activation, commit, push or deployment occurred.

## Honest remaining gates

1. V4 remains unaccepted until independent functional, integrity and quality
   review validates the final checkpoint and manifest.
2. V4 callbacks must be spawn-pickleable and return-only. A provider that
   directly mutates external state needs its own cancellation contract.
3. Natural-language provider planning, Gemini Live parity, accepted Phase 5
   catalog binding, planner memory and installed external agents remain separate
   slices.
4. No Phase 6 exit or live activation is claimed.
