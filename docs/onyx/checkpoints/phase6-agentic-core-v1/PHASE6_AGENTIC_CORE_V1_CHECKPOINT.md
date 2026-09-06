# Phase 6 Agentic Core V1 checkpoint

Status: **isolated candidate, strict default-off, not externally accepted, not live**

Date: 2026-07-22  
Platform: Windows 11 `10.0.26200`, Python `3.13.7` x64

## Scope delivered

- Typed, immutable `GoalV1`, `MissionBudgetV1`, `PlanV1` and `StepV1` contracts.
- Bounded DAG validation, deterministic ordering, dependency checks, retry/time/
  compute/token/API/cost budgets and host-owned risk/effect/approval labels.
- Explicit workspace/data-class/root scope before plan persistence or execution.
- Provider-neutral `ModelRouterV1` with hard privacy, workspace, modality,
  structured-output, reliability, latency and cost filters.
- Local deterministic planner plus truthful declaration-only provider adapter.
- Provider-free Research Operator Cell and independently instructed deterministic
  Verifier Cell.
- Six existing MissionStore read-only tools admitted; unknown or consequential
  capabilities denied. `local_catalog_read` is plannable but remains
  `waiting_for_phase5` and cannot dispatch through this candidate.
- One-way idempotent request/plan binding; immutable plan-to-MissionStore binding.
- SQLite metadata/evidence sidecar with immutable plan identity, append-only
  hash-chained events, immutable content-digested receipts, projection/evidence
  reconciliation and a persistent non-resettable kill latch.
- Existing MissionStore remains the only executor. `execute_approved()` never
  opens an approval window and runs only a mission already moved to `running` by
  the existing host authority.
- Per-step timeout, dispatch/argument/idempotency binding, concurrent cancel,
  late-result rejection through MissionStore, kill propagation and restart
  reconciliation without auto-replay.
- Evidence receipts bind MissionStore's plan digest, authority snapshot hash,
  event hash and observed postconditions.
- Bounded critic/repair contract creates a new immutable plan and stops at the
  goal's repair budget.
- Repo-scoped `ExternalAgentAdapterV1` request/status protocol with explicit
  roots, forbidden operations, wall/follow-up/token/cost budgets, kill token and
  evidence requirements. V1's only implementation is `BLOCKED_BY_ACCESS` and
  performs no subprocess or network call.

## Frozen source hashes

- `core/phase6_agentic_core_v1.py` — 93,076 bytes —
  `ab7a6cfec738c31b7beb66ac7a66584f892231ce8a3a2c9e81f30945123cc965`
- `tests/test_phase6_agentic_core_v1.py` — 22,495 bytes —
  `409e9c59b1650f155c3075e176541f438e0cf588f4242dadeb2126b306792b0a`

These two hashes were captured before this checkpoint file was written. The
companion manifest binds their final values and the documentation artifacts.

## Verification performed

Focused candidate:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-tests-20260722-i tests\test_phase6_agentic_core_v1.py
```

Result: **27 passed in 5.33s**.

Static:

```powershell
.\.venv\Scripts\python.exe -m ruff check core\phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v1.py
.\.venv\Scripts\python.exe -m py_compile core\phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v1.py
```

Result: **Ruff passed; compilation passed**.

Stable boundary regression:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-regressions-20260722-j tests\test_missions.py tests\test_mission_tools.py tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py -k "not onyx_live_stops_application_worker_in_finally"
```

Result: **111 passed, 1 deselected, 44 subtests passed in 24.18s**.

The unfiltered command produced **111 passed, 44 subtests passed, 1 failed**.
The failure is `MissionTests.test_onyx_live_stops_application_worker_in_finally`:
the existing fixture constructs `OnyxLive` via `__new__`, while current
`main.py:_stop_phase5_session()` reads `_phase5` without `getattr`. Phase 6 does
not import or modify `main.py`; this candidate was explicitly forbidden from
changing that live surface. It is retained as a visible baseline/integration
finding, not relabeled as a Phase 6 pass.

The machine's global pytest temp directory was inaccessible (`WinError 5`), so
all reported runs used fresh explicit workspace-adjacent `--basetemp` roots.

## Default-off and non-wiring evidence

- The sole feature flag is `ONYX_PHASE6_AGENTIC_CORE_V1`; only exact `true`
  enables the factory.
- The disabled factory test proves no sidecar is created.
- No edits were made to `main.py`, `ui.py`, `core/permission_broker.py`,
  `dashboard/server.py`, accepted Phase 5 candidates, HUD/Orb, owner profile or
  live configuration.
- No process was restarted, no live flag enabled, no network/provider/subprocess
  call performed and no commit/push/deploy created.

## Honest limitations and next integration gates

1. Natural-language/provider planning is not operational; only validated
   host-supplied structured proposals are accepted.
2. Gemini Live and standalone `llm_client` adapter parity, health, cancellation,
   fallback and golden evaluation remain separate Phase 6 slices.
3. `local_catalog_read` requires a separately accepted adapter to Phase 5 V3's
   exact session/workspace/account/profile and permission/dispatch seals.
4. Existing memory has no Phase 6 planner-context adapter yet; it must remain
   workspace-filtered and cannot become authority through similarity.
5. External coding-agent execution remains `BLOCKED_BY_ACCESS` until an installed,
   authenticated, permitted test environment and independent acceptance exist.
6. The baseline `OnyxLive.__new__` lifecycle regression above must be fixed in a
   separately scoped live-integration candidate.
7. No Phase 6 E1-E6 exit, capability-matrix promotion or live activation is
   claimed by this checkpoint.
