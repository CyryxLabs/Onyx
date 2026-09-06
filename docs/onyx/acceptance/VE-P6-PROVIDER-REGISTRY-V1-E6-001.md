# Phase 6 Provider Registry + Health Route Plan V1 External E6 Acceptance

- Evidence ID: `VE-P6-PROVIDER-REGISTRY-V1-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED — isolated metadata-only default-off candidate**
- Candidate: `phase6-provider-registry-candidate-001`

## Frozen candidate

This decision accepts candidate manifest
`7a3191607037f6210ae145b5477bbaeff5bfdaa7c756257d4775c1f30c0a10c6`
and its exact 5/5 artifact root
`98d381711cda0b9f72eadb9a1ae9f81f8bebff70a922b1f7aa42c139baa82baf`.

| Artifact | SHA-256 |
|---|---|
| `core/phase6_provider_registry_v1.py` | `7b3e6c682ff6ec8a7e3ceade8f245afdf4edbc562dd1872acf54fa241109b6ad` |
| `tests/test_phase6_provider_registry_v1.py` | `034443d484db5b524d42a99721066eff8847c4c4edda6c3c5ecf09edf0c0a9c6` |
| `scripts/verify_phase6_provider_registry_v1.py` | `393970577e86216825b9fe0d611ab0c10cffdf149acc7dce1f6d74e48e8c6557` |
| `docs/onyx/adrs/ADR-0021-phase6-provider-registry-v1.md` | `2e334685ce522b582729ed4cee105350e3b574fb238b77d3f4e1a3c525037aca` |
| `docs/onyx/checkpoints/phase6-provider-registry-v1/PHASE6_PROVIDER_REGISTRY_V1_CHECKPOINT.md` | `a5dc60911634d211482d2eb4828c01fcbd33ec4dc9757fefd9781230df5b6a18` |

Seven frozen anchors bind the defining Agentic Core V1 types, accepted Agentic
Core V6, `main.py`, Live Integration V2, Gemini compatibility, Live Wiring V1
and Activation V9.

## Independent gate and resolved findings

Final decision: **P0=0, P1=0, P2=0, P3=0** for the frozen candidate.

The initial external audit found and resolved before freeze:

1. **P1:** the private HMAC authority key lacked an immutable fingerprint,
   allowing authority substitution before the first observation;
2. **P1:** health and health-snapshot keysets were not required to match,
   allowing a unilateral health deletion to reset sequence state;
3. **P2:** the candidate imported routing types directly from Agentic Core V1
   but did not separately byte-bind that defining file.

The frozen candidate now re-attests the 32-byte key fingerprint, requires exact
health/snapshot membership and binds
`core/phase6_agentic_core_v1.py` at
`ab7a6cfec738c31b7beb66ac7a66584f892231ce8a3a2c9e81f30945123cc965`.
Regression tests reproduce the former authority/snapshot attacks and require
fail-closed denial.

## Accepted behavior

The independent review confirmed:

- exact reuse of `ModelDescriptorV1`, `RouteRequestV1` and `ModelRouterV1`;
- privacy/data-class, workspace, modality, local-only, structured-output and
  budget hard filters before health and ranking;
- sensitive requests never receive a network-backed fallback;
- HMAC-SHA-256 authentication, exact 32-byte authority, monotonic sequence,
  previous-digest chain, strictly increasing observation time and maximum
  300000 ms freshness;
- available and degraded health eligibility; stale, rate-limited and
  unavailable health denial;
- replay, gap, duplicate route, out-of-order, forgery, record drift,
  authority drift and snapshot drift denial;
- explicit no-target blocks for cancellation, budget exhaustion and health
  unavailability;
- ordered metadata-only primary/fallback plans with no prompt, payload,
  provider invocation, credential, network call or live route;
- exact default-off flag and factory-only construction.

Evidence reproduced `P6_PROVIDER_REGISTRY_V1_OK`, **22/22 focused tests** and
**156/156 cumulative Agentic Core V1-V6 plus Registry tests**. Ruff lint,
formatting and Python compilation passed.

## Exact boundary

The candidate remains **isolated, default-off, metadata-only, unwired and not
live**. This acceptance does not set
`ONYX_PHASE6_PROVIDER_REGISTRY_V1=true`, invoke a provider, contact a network,
prove external provider availability, change a live route, unlock Phase 6 or
claim Onyx completion.

```powershell
.\.venv\Scripts\python.exe -I -S -B scripts\verify_phase6_provider_registry_v1_acceptance.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_phase6_provider_registry_v1_acceptance.py
```

The verifier must emit `P6_PROVIDER_REGISTRY_V1_ACCEPTANCE_OK`.
