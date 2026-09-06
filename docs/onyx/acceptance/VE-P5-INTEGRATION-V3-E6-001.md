# Phase 5 Integration V3 External E6 Acceptance

- Evidence ID: `VE-P5-INTEGRATION-V3-E6-001`
- Decision date: 2026-07-22
- Decision: **ACCEPTED — Integration V3 only, frozen default-off transition handoff**
- Candidate: Phase 5 Integration, V3

## Frozen candidate anchor

This independent record freezes the exact V3 transition without changing any
candidate byte:

| Anchor | SHA-256 |
|---|---|
| `core/phase5_integration_v3.py` | `52d48c121da485c024811e6cd3fafbabaed971175d7cb41ad23358c5c2879b0d` |
| `tests/test_phase5_integration_v3.py` | `c2b92406ce5f7b6d1a8f88afe167dbf62aed8059cccea47bc2c523dd4956ad02` |
| `scripts/verify_phase5_integration_v3_transition.py` | `c23724bc5d5ac2a184bdca5766e53ec4324ac4ea5fe8601998421477e1ded025` |
| `tests/test_phase5_integration_v3_transition.py` | `11c448200591b5038ca77afedb633f8712294eeff86fa2357924a16bba789b47` |
| `main.py` | `6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712` |
| `docs/onyx/checkpoints/phase5-integration-v3/manifest.json` | `9ee4b34fc87a6be5e123c83c7dd244804498891eb175b5201cf074475ff0d167` |
| `docs/onyx/checkpoints/phase5-integration-v3/PHASE5_INTEGRATION_V3_CHECKPOINT.md` | `1615bc10c349a7c88ac3c23e89d55e74c05c81c07c3c252409172100a6e17b17` |
| `docs/onyx/checkpoints/phase5-integration-v3/phase5-integration-v3.sha256` | `e5ed8bc4196fd98b25e675159031754d21e1fd31eac048a4796eb9212d40037c` |

The exact candidate-manifest digest
`9ee4b34fc87a6be5e123c83c7dd244804498891eb175b5201cf074475ff0d167`
is the frozen root for this decision. Any drift in a candidate, historical,
accepted-component, hook, or execution-closure anchor invalidates this
acceptance and requires a new version and new independent gates.

## Independent gate decision

The independent acceptance gate is **PASS** with `P0=0, P1=0, P2=0`.
It independently rehashed the candidate closure and its anchors, executed the
frozen transition verifier, reproduced 35 focused tests and 230 cumulative
tests, and confirmed lint and bytecode compilation. No feature flag was enabled,
no live process was restarted, and no candidate or UI/HUD byte was changed.

Two P3 advisories remain:

1. The checkpoint reported the focused count but omitted the exact focused
   reproduction command; this record supplies it without modifying the
   checkpoint.
2. Pytest cannot write the ordinary `.pytest_cache` on this host. The tests
   still pass with explicit `--basetemp`; this is host residue, not runtime
   state or an execution dependency.

## Reproduction commands

Exact focused command — 35 passed, 0 failed, 0 deselected:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py --basetemp .pytest-p5-v3-acceptance-focused
```

Exact cumulative command — 230 passed, 0 failed, 0 deselected:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_session_grants_v11.py tests\test_approval_inbox_v15_acceptance.py tests\test_capability_nexus_v32_acceptance.py tests\test_phase5_component_adapters_v3.py tests\test_phase5_runtime_v10.py tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py --basetemp .pytest-p5-v3-cumulative
```

Exact frozen transition-verifier command and required marker:

```powershell
.\.venv\Scripts\python.exe -I -S -B scripts\verify_phase5_integration_v3_transition.py
```

The command must emit `P5_INTEGRATION_V3_TRANSITION_OK` and the exact V3
transition payload. The independent acceptance verifier is:

```powershell
.\.venv\Scripts\python.exe -I -S -B scripts\verify_phase5_integration_v3_acceptance.py
```

## Historical and accepted closure binding

Rejected Integration V1 and V2 remain exact, preserved historical candidates,
unreachable from V3. Their core/test/verifier/checkpoint/manifest roots are
independently rehashed by the acceptance verifier; neither is retroactively
accepted.

The three historical execution closures are independently bound as follows:

| Closure | Projection-manifest SHA-256 | Closure-root SHA-256 |
|---|---|---|
| Runtime V10 E6 | `a897faf253ad18899c9abd724c74dddbcf14593a9f0dd9b7af89ac4ca270abba` | `b37df684730d1e18d8291a68af12af814f34aada22ebb1428fe29e5858dc7ed8` |
| Approval Inbox V15 E6 | `895ad5b300f9ce7c0d467a80cb321d00af92f268b40fa573ea387afc5cd6c9f4` | `8a125205928d9b55e662f5da1086a9f2605e98eab34533281379cae2875d007d` |
| Capability Nexus V32 E6 | `5f43294603f3f61c6a59128849ee6dd1ceedc7d63185364a9240df8b3c524474` | `17946d71960d5f08ae2b6979e3ab23ee255ccca2e6bf6e22153d07acffe65bb1` |

The accepted Session Grants R11, Approval Inbox V15, Capability Nexus V32,
Component Adapters V3 and Runtime V10 implementation anchors are also rehashed.
The governed broker hook remains
`e37fb092410ba0843036dbdc779342c4d24a811bbfcf0de8812f2f6144e7d250`,
and the unchanged dashboard hook remains
`4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1`.

## Exact acceptance boundary

Accepted:

- the exact V3 authorization-to-dispatch bridge and transition evidence;
- collision burning, argument sealing, bounded anti-replay state and the
  provider-free `local.catalog/catalog_read` execution contract;
- the exact V10/V15/V32 historical execution closures;
- a handoff to a separately controlled low-risk activation decision.

Not activated or accepted by this decision:

- any Phase 5 flag, live restart or live catalog-read invocation;
- remote approve, grant, dispatch, connector, provider, MCP or mutation
  authority;
- changes to `ui.py`, QML, Orb/HUD or `dashboard/static`;
- the Phase 5 exit, later phases, packaging or completion of Onyx.

All eight integration flags remain default `False`; activation requires an
explicit later host configuration and separate live evidence. This record is a
freeze/acceptance of exact default-off bytes, not an activation instruction.

