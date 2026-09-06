# Phase 6 Live Integration V2 External E6 Acceptance

- Evidence ID: `VE-P6-LIVE-INTEGRATION-V2-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED — Live Integration V2 only, isolated/default-off implementation handoff**
- Candidate: Phase 6 Live Integration V2

## Frozen candidate anchors

This external record accepts the exact V2 candidate without changing any
candidate byte:

| Anchor | SHA-256 |
|---|---|
| `core/phase6_live_integration_v2.py` | `e3194a0d8e206d33218bc8291cbd518788e8dfb3931adfd2f067908655d409b5` |
| `tests/test_phase6_live_integration_v2.py` | `0a69c7296c53361349472462e40d8fb9ca77eff1f0e2b462dd69293f0039dbe7` |
| `docs/onyx/adrs/ADR-0017-phase6-live-integration-v2.md` | `d94e414eadf092ddad0a28b9b0d6e96b772f7a549fc1b0f363f842401ee2b7c3` |
| `docs/onyx/rejections/PHASE6_LIVE_INTEGRATION_V1_REJECTION.md` | `eb917cec9cb7e3c96aef33e87b40c0a6cc90146824212972f2f00eb9ff2a66b7` |
| `docs/onyx/checkpoints/phase6-live-integration-v2/PHASE6_LIVE_INTEGRATION_V2_CHECKPOINT.md` | `2a0f998d4c97688f0f0144186326252b4129fe21a0b295d59eba3f058611831e` |
| `scripts/verify_phase6_live_integration_v2.py` | `3765979778f58b9f8a238256bf11cc3f4e1fbee13afd4bc0ccd3a223cf3d289a` |
| `docs/onyx/checkpoints/phase6-live-integration-v2/manifest.json` | `d02b265e5d67c98fb9dd2e868440ead39360187bdd95592fcf89a44f4448833a` |

The manifest closes **6/6 artifacts** at the exact artifact root
`0b58365a0c43ea9b7133de1c0a51e77aa6bd855852849dab2bd9c433f733a334`.
Any candidate-anchor, manifest or root drift invalidates this decision and
requires a new candidate version and external review.

## V1 rejection and P1 reproduction

V1 remains **REJECTED — preserved, default-off, never live**. Its manifest
SHA-256 is
`56b8d2ae00078bd755dab583da922d0530b8d2e5482080704f62bc58f05ed6a7`,
its artifact root is
`4f974bdef7fbf58a6fb3780d5d3158884240ce9e4984401c67025b5eb26089bd`
and the additive rejection-record SHA-256 is
`eb917cec9cb7e3c96aef33e87b40c0a6cc90146824212972f2f00eb9ff2a66b7`.

The external gate reproduced both V1 P1 findings:

1. V1 contains no complete immutable
   `workspace_id + account_id + profile_id + principal_id` binding across its
   operational requests and receipts.
2. V1's public text adapter accepts caller-supplied `invoke` and `executor`
   dependencies, while its facade factory accepts prebuilt `catalog` and
   `text` adapters.

The gate then reproduced the V2 closure:

- exact frozen four-part host identity, compared with Agentic Core V6 and
  Phase 5 V3 before process or receipt-store construction;
- complete identity payload/digest in V2 text/catalog request and receipt
  digests, with cross-account/profile/principal/workspace adversarial denial;
- a V2 text constructor accepting only identity and a facade factory exposing
  no invoker, executor or prebuilt adapter;
- internal exact `_current_llm_text_call` and exact
  `TerminableProcessExecutorV4` construction;
- repeated operational and identity attestation, including
  post-construction drift denial.

V2 corrects those two findings without retroactively accepting or editing V1.

## Independent gate result

Functional, integrity and quality gates are **PASS** with
`P0=0, P1=0, P2=0, P3=0` within this exact acceptance boundary.

The external review:

- rehashed the V2 manifest and all 6/6 artifacts and recomputed the artifact
  root;
- rehashed the exact V1 manifest, artifact root and rejection evidence;
- reproduced **23/23 focused V2 tests**;
- reproduced **241/241 cumulative Phase 5 V3 + Agentic Core V1-V6 + Live
  Integration V1-V2 tests**;
- passed **17/17 external acceptance tests**;
- reproduced the two V1 P1 defects and the corresponding V2 closures;
- passed Ruff lint, Ruff format and Python byte compilation;
- independently reran and obtained:
  `P6_LIVE_INTEGRATION_V2_OK`,
  `P6_LIVE_INTEGRATION_V1_OK`,
  `P6_AGENTIC_CORE_V6_ACCEPTANCE_OK` and
  `P5_INTEGRATION_V3_ACCEPTANCE_OK`;
- confirmed strict default-off behavior and no import, flag or dispatch wiring
  in the checked live host surfaces.

No flag was enabled, no provider/network call was made, no live process was
restarted and no candidate, V1, accepted dependency or live-wiring byte was
changed by this acceptance.

## Reproduction commands

Focused V2 — 23 passed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-live-v2-e6-focused tests\test_phase6_live_integration_v2.py
```

Cumulative boundary — 241 passed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-live-v2-e6-cumulative tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py tests\test_phase6_agentic_core_v5.py tests\test_phase6_agentic_core_v6.py tests\test_phase6_agentic_core_v6_acceptance.py tests\test_phase6_live_integration_v1.py tests\test_phase6_live_integration_v2.py
```

Static gates:

```powershell
.\.venv\Scripts\python.exe -m ruff check core\phase6_live_integration_v2.py tests\test_phase6_live_integration_v2.py scripts\verify_phase6_live_integration_v2.py
.\.venv\Scripts\python.exe -m ruff format --check core\phase6_live_integration_v2.py tests\test_phase6_live_integration_v2.py scripts\verify_phase6_live_integration_v2.py
.\.venv\Scripts\python.exe -m py_compile core\phase6_live_integration_v2.py tests\test_phase6_live_integration_v2.py scripts\verify_phase6_live_integration_v2.py
```

The external acceptance verifier is independently runnable with the standard
library and reruns all four bound verifiers:

```powershell
.\.venv\Scripts\python.exe -I -S -B scripts\verify_phase6_live_integration_v2_acceptance.py
```

It must emit `P6_LIVE_INTEGRATION_V2_ACCEPTANCE_OK`.

## Exact acceptance boundary

Accepted:

- the exact six-artifact V2 identity and sealed operational-factory closure;
- exact preservation and explicit rejection of V1;
- the exact inherited V1 timeout/cancellation/endpoint/model/privacy behavior
  only where V2 seals the accepted V1 delegate;
- the exact Phase 5 V3 provider-free catalog binding and V2 identity receipt
  envelope;
- an isolated implementation handoff for later, separately authorized
  activation work.

Not accepted or activated:

- imports, flags or dispatch wiring in `main.py`, `ui.py`, dashboard, runtime,
  packaging, QML or launchers;
- changes to the current standalone text caller or Gemini Live audio/streaming
  path;
- generic tool execution, provider-backed planning or planner memory;
- installed/authenticated external-agent execution;
- a supported V6 catalog completion transition, Phase 6 exit, Onyx completion,
  restart, deployment, commit or push.

Live Integration V2 remains isolated, strict default-off and unwired. This E6
decision closes the V2 candidate review only; it is not live activation or
proof that the full Onyx product is operationally complete.
