# Phase 6 Agentic Core V6 External E6 Acceptance

- Evidence ID: `VE-P6-AGENTIC-CORE-V6-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED — Agentic Core V6 only, isolated/default-off implementation handoff**
- Candidate: Phase 6 Agentic Core, V6

## Frozen candidate anchors

This independent record freezes the exact V6 candidate without changing any
candidate byte:

| Anchor | SHA-256 |
|---|---|
| `core/phase6_agentic_core_v6.py` | `38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a` |
| `tests/test_phase6_agentic_core_v6.py` | `83218e07beaa85e570998936278cb3cd53fcaee9f0b37d55cb675b35dedf8dc0` |
| `docs/onyx/adrs/ADR-0015-phase6-agentic-core-v6-ascii-sql-lexing.md` | `b5f53cf7e79cb1dc65eedead54b83b97136903838b665216123c6bd56ecad77a` |
| `docs/onyx/rejections/PHASE6_AGENTIC_CORE_V5_REJECTION.md` | `1b30f6e940a5c3666f252b0e805d57dfd08009067e6bb73600677365b0b7f4d9` |
| `docs/onyx/checkpoints/phase6-agentic-core-v6/PHASE6_AGENTIC_CORE_V6_CHECKPOINT.md` | `96504a9007b919dc8ccb1ef4373d094580a382c785e772e49630726cf4acc124` |
| `docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json` | `cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15` |
| `core/missions.py` (`MissionStore` dependency) | `fe2074eb132c09beecb9f13c5151659e745cf888676c4244c037e0a7ed7f2fe5` |

The exact V6 artifact root is
`ca7d7f3281d9926848696e25befe63373738596dbc7e9b5bdaf95325922b06b0`.
The candidate manifest is the frozen root document for this decision. Any
drift in an anchor, artifact entry, historical manifest, rejection record or
the MissionStore dependency invalidates this acceptance and requires a new
version and independent review.

## Independent gate decision

Functional, integrity and quality gates are **PASS** with
`P0=0, P1=0, P2=0, P3=0`.

The independent review:

- rehashed the final V6 bundle and recomputed its root;
- rehashed and recomputed every rejected V1-V5 candidate manifest/root;
- bound the exact V1-V5 rejection records without retroactive acceptance;
- reproduced 30 V6 tests and 134 cumulative V1-V6 tests;
- reproduced the stable boundary at 246 tests plus 44 subtests;
- reproduced an explicit 36-node closure for recovery, schema/index
  authentication, full-input materialization, process termination,
  two-process convergence, compute enforcement, strict default-off behavior
  and the truthful external-agent boundary;
- exercised representative Kelvin sign, NBSP, vertical-tab, Greek, Cyrillic,
  fullwidth, sharp-S and non-ASCII identifier cases;
- confirmed a representative tokenizer p95 below the independent 20 ms ceiling
  and bounded transient memory below 8 MiB;
- passed Ruff lint, Ruff format and Python byte compilation.

No flag was enabled, no external/provider/network call was made, no live
process was restarted and no candidate, MissionStore or live-wiring byte was
changed by this acceptance.

## Reproduction commands

V6 focused — 30 passed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\.pytest-phase6-v6-acceptance-focused tests\test_phase6_agentic_core_v6.py
```

Cumulative V1-V6 — 134 passed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\.pytest-phase6-v6-acceptance-cumulative tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py tests\test_phase6_agentic_core_v5.py tests\test_phase6_agentic_core_v6.py
```

Stable boundary — 246 passed and 44 subtests passed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\.pytest-phase6-v6-acceptance-stable tests\test_missions.py tests\test_mission_tools.py tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py tests\test_phase6_agentic_core_v5.py tests\test_phase6_agentic_core_v6.py
```

The independent 36-node closure consists of all 30 nodes in
`tests/test_phase6_agentic_core_v6.py` plus these exact six nodes:

```text
tests/test_phase6_agentic_core_v4.py::test_recovery_and_compaction_query_plans_use_exact_indexes_without_temp_sort
tests/test_phase6_agentic_core_v4.py::test_exact_materializer_rejects_lossy_or_unknown_input_before_write
tests/test_phase6_agentic_core_v4.py::test_process_timeout_terminates_and_joins_worker
tests/test_phase6_agentic_core_v4.py::test_lineage_deadline_terminates_process_charges_and_exhausts
tests/test_phase6_agentic_core_v4.py::test_v4_forced_expiry_two_processes_converge_on_one_executable_mission[claimed]
tests/test_phase6_agentic_core_v1.py::test_external_agent_contract_is_repo_scoped_and_truthfully_blocked
```

The external acceptance verifier is independently runnable with only the
standard library:

```powershell
.\.venv\Scripts\python.exe -I -S -B scripts\verify_phase6_agentic_core_v6_acceptance.py
```

It must emit `P6_AGENTIC_CORE_V6_ACCEPTANCE_OK`.

## Historical disposition

V1-V5 remain **REJECTED**, preserved and never activated. Their exact manifest
digests and artifact roots are:

| Version | Manifest SHA-256 | Artifact root SHA-256 |
|---|---|---|
| V1 | `82eea75a58beec613eba2823d928a76b6d520d9f76b4e4f6b8c811058c77cbd1` | `192556429c262c63161bfcf1fe07d27e3e3470336fd6d97e6f8bacbf7816f0e1` |
| V2 | `c1608dbb7042b1f940422f9ca7c8791eb6935ec15505fe2859c0f756e129dcbc` | `5d8dd8b9d65f8aae17224b2cbeed74546c3c563eba76a87a9f53ac3ba7104ec4` |
| V3 | `3d77e96c6561445adb8b2cdb61e400d4ba896d6556ed0c357bb270c501d98288` | `9f0f710373441a86d6d77bf908cfc7cf81b7f06faab9b293dcba5d23dd33bf27` |
| V4 | `f831f52ff257b877f6dbb7b2eac279cee7c2ffd6c84b5761998ac37689e14315` | `bdcdee76e4209c071705d4ad76a69515efd4dd6fe395005d3fa653da9c51b0cd` |
| V5 | `b879f2d3266601ec76fec2fa08c4dcb6364217d6b23d7d63811d700c769b8958` | `9913b6731fd4ccdb103ce511ddb0b4133be456b4acd878dd45091f522d9d1fe4` |

Their additive rejection-record digests are independently bound by the
verifier. This decision does not rewrite history or accept a prior version.

## Exact acceptance boundary

Accepted:

- the exact isolated V6 ASCII SQL lexical correction and inherited V4/V5
  closures;
- exact schema authentication, fail-before-write behavior and bounded
  process/coordination contracts;
- the exact frozen `MissionStore` dependency used by this candidate;
- an implementation handoff for a later, separately reviewed integration.

Not accepted or activated:

- imports, flags or dispatch wiring in `main.py`, `ui.py`, `dashboard/`,
  runtime, packaging or launchers;
- live provider adapters, `local_catalog` binding, Gemini Live planning or any
  provider/network call;
- installed `ExternalAgent` execution or external-agent orchestration;
- planner memory, Phase 5 live binding, Phase 6 exit or Onyx completion;
- restart, deployment, commit or push.

V6 remains isolated, default-off and unwired. The next integration may only
proceed after provider adapters, `local_catalog` and `ExternalAgent` live
contracts exist and receive separate extension-off equivalence, authority,
rollback, resource and live-runtime evidence.
