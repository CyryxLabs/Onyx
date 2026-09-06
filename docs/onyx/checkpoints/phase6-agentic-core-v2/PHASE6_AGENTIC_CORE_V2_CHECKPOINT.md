# Phase 6 Agentic Core V2 checkpoint

Status: **isolated candidate, strict default-off, not externally accepted, not live**

Date: 2026-07-22  
Platform: Windows 11 `10.0.26200`, Python `3.13.7` x64

## V1 disposition and preservation

The V1 candidate was rejected for four gate findings. Its core, tests, ADR,
checkpoint and manifest remain byte-for-byte unchanged. The additive rejection
record is `docs/onyx/rejections/PHASE6_AGENTIC_CORE_V1_REJECTION.md`.

## V2 corrections delivered

- `max_compute_seconds` is a persisted lineage-wide wall-compute account shared
  by the root plan and repairs. Planning, every runner attempt, verification and
  explicit restart recovery are charged.
- Effective runner timeout is `min(step.timeout_seconds, lineage remainder)`.
  Timeout detaches the daemon result, cancels MissionStore authority and rejects
  the late result. Exhaustion is terminal plan `BLOCKED` with reason
  `BUDGET_EXHAUSTED`; verification cannot project completion after overrun.
- Materialization commits a unique SQLite reservation before MissionStore
  creation. Two core instances at a barrier create exactly one mission.
- A create-before-bind failure cancels the mission, writes an immutable orphan
  tombstone and blocks the plan. Expired-reservation recovery discovers crash
  orphans through a deterministic plan marker and never creates a replacement.
- Planner V2 captures the exact invoked adapter descriptor, checks host routing,
  invokes once, and requires the exact proposal adapter ID to match before any
  plan persistence.
- Artifact-root construction is specified in ADR-0011, implemented by
  `artifact_root_v2()` and recomputed from all listed bytes by the final focused
  manifest test.
- Frozen V1 domain serialization/evidence and the existing MissionStore remain
  the authorities they already were. V2 does not add another executor.

## Verification

Final focused candidate and frozen V1 compatibility:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v2-final-focused tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py
```

Result: **44 passed in 11.83s**.

Stable unfiltered boundary, including the pre-existing OnyxLive lifecycle seam:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-v2-final-regression tests\test_missions.py tests\test_mission_tools.py tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py
```

Result: **156 passed, 44 subtests passed in 68.29s, with no deselection and no
failure**.

The accepted `main.py` was not edited. The old `OnyxLive.__new__` lifecycle test
fixture now initializes `_phase5=None` and `_dashboard=None`, matching the
constructor-owned shutdown seam. Its focused regression passes.

Static gates:

```powershell
.\.venv\Scripts\python.exe -m ruff check core\phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v2.py
.\.venv\Scripts\python.exe -m ruff format --check core\phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v2.py
.\.venv\Scripts\python.exe -m py_compile core\phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v2.py
```

Result: **Ruff lint passed, Ruff format passed and compilation passed**.

Performance probe: 500 persisted `budget_snapshot()` calls measured median
`3.214 ms`, p95 `6.842 ms`, maximum `15.873 ms` on the stated host.

## Artifact-root algorithm

The manifest is excluded. For every listed artifact, form the UTF-8 bytes of
`canonical_relative_posix_path + NUL + lowercase_sha256`; sort the complete
records ascending; join with LF and no trailing LF; SHA-256 the result. The
manifest-focused test independently verifies size, file digest and this root.

## Default-off and scope evidence

- Only exact `ONYX_PHASE6_AGENTIC_CORE_V2=true` enables the explicit factory.
- No V2 import exists in `main.py`, `ui.py` or `dashboard/server.py`.
- No edits were made to `main.py`, UI, permission broker, dashboard, Phase 5
  accepted candidates, live configuration, Orb/HUD or owner profile.
- No provider, network or subprocess call was added or performed.
- No process was restarted, no flag enabled, and no commit/push/deploy created.

## Honest remaining gates

1. V2 remains unaccepted until independent functional, integrity and quality
   gates validate this checkpoint and manifest.
2. A detached Python thread cannot be forcibly killed safely; MissionStore is
   cancelled and its late result is discarded. Admitted V2 tools remain local
   provider-free read-only.
3. Natural-language/provider planning, Gemini Live and `llm_client` parity,
   memory planner context, accepted Phase 5 `local_catalog_read` binding and a
   real installed/authenticated external-agent adapter remain separate slices.
4. No Phase 6 E1-E6 exit, capability-matrix promotion or live activation is
   claimed.
