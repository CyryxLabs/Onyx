# Phase 6 Agentic Core V3 checkpoint

Status: **isolated candidate, strict default-off, not externally accepted, not live**

Date: 2026-07-22  
Platform: Windows 11 `10.0.26200`, Python `3.13.7` x64

## Prior disposition and preservation

V1 and V2 remain rejected and byte-for-byte preserved. Their additive rejection
records describe the independent gate findings. V3 retains V2's adapter
identity and artifact-root positives while replacing its unsafe execution,
materialization and recovery coordination.

## V3 corrections delivered

- Planner, critic, repair planning, step runner, verifier and recovery all use
  the remaining persisted lineage-wide `max_compute_seconds` account. Every
  wall interval is charged on success or exception.
- One bounded worker is permanently poisoned after timeout. Late results are
  discarded and no replacement thread is created, preventing repeated timeout
  leaks. Hung mission work is cancelled and terminally blocked as
  `BUDGET_EXHAUSTED`.
- `MissionStore.create_idempotent()` is an additive transactional API with a
  deterministic mission identity and exact-content replay check.
- Materialization uses durable generation/owner fencing with checks immediately
  before and after create. A stale owner cannot cancel, tombstone, overwrite or
  bind the winner.
- Two real spawned-process tests force lease expiry before and after creation.
  Both interleavings produce exactly one bound, approvable and executable
  mission; both callers return cleanly or observe that winner.
- Runtime and in-flight compute recovery are bounded and indexed. Tests inspect
  SQLite query plans, prohibit the legacy full projection scan and validate the
  complete schema/index/trigger inventory.
- Terminal coordination compaction is retention-based and bounded; immutable
  V1 evidence and MissionStore history are preserved.

## Verification before manifest freeze

Focused V3 excluding only the not-yet-created manifest test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v3-focused-b tests\test_phase6_agentic_core_v3.py -k "not checkpoint_manifest"
```

Result: **16 passed, 1 deselected in 7.05s**.

The two forced-expiry process interleavings were also repeated three times
before the cumulative run; every repetition passed.

Stable unfiltered boundary, with only the V2/V3 manifest tests deferred until
the V3 manifest exists:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v3-regression-a tests\test_missions.py tests\test_mission_tools.py tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py -k "not checkpoint_manifest"
```

Result: **171 passed, 44 subtests passed, 2 deselected in 40.67s**.

After creating the manifest, the cumulative V1/V2/V3 suite was repeated with
no filter or deselection. Result: **61 passed in 18.77s**.

The complete stable boundary was then repeated with both manifest tests and no
filter or deselection. Result: **173 passed, 44 subtests passed in 40.65s**.

Static gates cover Ruff lint/format for V3, undefined-name/import checks for the
additive legacy MissionStore edit, and Python byte compilation. The existing
legacy `core/missions.py` has a broad pre-existing Ruff E701/E702 formatting
baseline and is not mechanically reformatted in this candidate.

Performance probe on the stated host:

- 500 `compute_snapshot()` reads: median `3.812 ms`, p95 `4.794 ms`, maximum
  `6.083 ms`.
- 500 empty indexed recovery reads: median `4.778 ms`, p95 `5.797 ms`, maximum
  `7.938 ms`.

## Default-off and scope evidence

- Only exact `ONYX_PHASE6_AGENTIC_CORE_V3=true` enables the explicit factory.
- No V3 import exists in `main.py`, `ui.py` or `dashboard/server.py`.
- `main.py`, UI, dashboard, permission broker, Phase 5, live configuration,
  Orb/HUD and owner profile were not changed by V3.
- No provider, network or subprocess call was added or performed.
- No process was restarted, no feature flag enabled, and no commit, push or
  deployment was created.

## Artifact root

The manifest is excluded. Every listed canonical POSIX path plus NUL plus its
lowercase SHA-256 is UTF-8 encoded; complete records are sorted ascending,
joined with LF and no trailing LF, then SHA-256 hashed. The final focused test
checks byte size, each digest and the computed root.

## Honest remaining gates

1. V3 remains unaccepted until independent functional, integrity and quality
   review validates the final checkpoint and manifest.
2. A timed-out callback can occupy the one daemon worker until it returns; the
   core stays poisoned and rejects further callbacks until reconstructed.
3. Natural-language/provider planning, Gemini Live and `llm_client` parity,
   accepted Phase 5 catalog binding, memory planner context and a real installed
   external-agent adapter are separate slices.
4. No Phase 6 exit, capability-matrix promotion or live activation is claimed.
