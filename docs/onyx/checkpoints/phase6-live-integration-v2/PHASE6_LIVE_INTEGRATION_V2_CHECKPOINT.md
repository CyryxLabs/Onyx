# Phase 6 Live Integration V2 checkpoint

Status: **isolated additive candidate, strict default-off, not live**

Date: 2026-07-23  
Platform: Windows 11 `10.0.26200`, Python `3.13.7` x64

## Scope

V2 is the additive correction for the two P1 findings recorded in
`PHASE6_LIVE_INTEGRATION_V1_REJECTION.md`. It preserves the complete frozen V1
candidate and does not edit or activate any accepted/live component.

Implemented:

- frozen four-part host identity:
  `workspace_id + account_id + profile_id + principal_id`;
- exact comparison of that identity with Agentic Core V6 and Phase 5 V3 before
  executor construction or receipt writes;
- complete identity payload and digest in every V2 text/catalog request and
  receipt digest;
- adversarial rejection of cross-workspace, account, profile and principal
  composition and replay;
- a public operational factory with no invoker, executor or prebuilt-adapter
  parameter;
- internal construction and repeated attestation of exact
  `_current_llm_text_call` plus exact `TerminableProcessExecutorV4`;
- post-construction invoker/executor/identity drift rejection;
- an additive authenticated append-only V2 identity receipt store;
- composition of the exact V1 closed catalog binding and Phase 5 V3 authority;
- an unchanged disabled external-agent boundary.

Not implemented or claimed:

- edits or wiring in `main.py`, UI, dashboard, launcher, runtime configuration
  or packaging;
- generic tool execution, external-agent execution or new authority;
- Gemini Live audio/streaming routing or provider-backed planning;
- Phase 6 exit, activation or operational-completion claim.

## V1 disposition

The V1 manifest SHA-256 remains
`56b8d2ae00078bd755dab583da922d0530b8d2e5482080704f62bc58f05ed6a7`
and its artifact root remains
`4f974bdef7fbf58a6fb3780d5d3158884240ce9e4984401c67025b5eb26089bd`.
All five V1 manifest artifacts remain byte-exact. V2 does not reinterpret V1
as accepted.

## Authority and construction order

The feature gate recognizes only exact lowercase `true`. With the gate off,
the factory returns `None` before checking dependencies.

With explicit opt-in, construction is ordered as follows:

1. validate exact dependency types and absolute receipt path;
2. attest the complete identity against exact Core V6 and Phase 5 V3;
3. internally construct the exact current text seam and exact accepted
   terminable executor;
4. create the additive V1-base and V2 identity receipt stores;
5. construct exact catalog and facade bindings.

Any failure after text construction closes the bounded executor. Every facade
operation re-attests identity and operational dependencies.

## Verification before manifest freeze

Focused V2:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-live-v2-dev3 tests\test_phase6_live_integration_v2.py -k "not manifest_recomputes"
```

Result: **22 passed, 1 manifest test deselected, in 2.48s**.

Cumulative Phase 5 V3 + Agentic Core V1-V6 + live integration V1-V2:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-live-v2-cumulative tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py tests\test_phase6_agentic_core_v5.py tests\test_phase6_agentic_core_v6.py tests\test_phase6_agentic_core_v6_acceptance.py tests\test_phase6_live_integration_v1.py tests\test_phase6_live_integration_v2.py --deselect tests/test_phase6_live_integration_v2.py::test_v2_manifest_recomputes_artifact_root
```

Result: **240 passed, 1 manifest test deselected, in 53.57s**.

Static V2 lint and format gates passed before freeze.

After manifest freeze the full focused and cumulative counts, standard-library
verifier marker and static gates are recorded in the manifest.

## Adversarial coverage

- strict default-off behavior and no live-surface import;
- byte-exact V1 preservation and explicit rejection evidence;
- each Core/Phase 5 workspace, account, profile and principal divergence;
- cross-account/profile/principal text request and catalog request denial;
- full identity presence in request/receipt payloads and digests;
- exact operational factory signature and exact adapter constructor signature;
- exact captured invoker and exact terminable executor attestation;
- post-construction invoker, executor and identity mutation denial;
- loopback/remote endpoint and model characterization through frozen V1;
- cancellation, privacy denial, redaction and no network in tests;
- durable identity-bound replay and changed-identity/input conflict;
- receipt schema/trigger tamper rejection without repair;
- catalog-only Phase 5 flow, no MissionStore mission and truthful waiting state;
- external agent disabled and blocked by access.

No test calls a live provider or the network.

## Resource, rollback and remaining gates

Default-off resource impact is zero. Explicit construction creates one bounded
process executor and additive receipt stores only after complete identity
attestation. Catalog reads remain provider-free, zero-cost and no-egress.

Rollback is omission/disablement of the V2 flag. The current host ignores the
module and its sidecars.

V2 corrects the two V1 P1 findings. It remains an isolated candidate requiring
separate activation authority; it does not claim Gemini Live parity, installed
external agents, provider-backed planning or Phase 6 exit.

