# Phase 6 Provider Registry + Health V1 checkpoint

Status: **isolated default-off Candidate 001; not live and not E6 accepted**.

Activation requires the exact value
`ONYX_PHASE6_PROVIDER_REGISTRY_V1=true`. Every other value is off. Construction
is factory-only and accepts an immutable tuple of exact `ProviderRecordV1`
values plus an exact 32-byte health authentication key.

The provider catalog reuses the accepted Agentic Core V6 routing contracts
without replacement: exact `ModelDescriptorV1`, `RouteRequestV1` and
`ModelRouterV1`. The defining `phase6_agentic_core_v1.py` bytes and the
accepted V6 bytes are separate frozen anchors. Records bind provider, API,
model, version, prompt/evaluation metadata digests and the descriptor's
modality, workspace, data class, local/network, structured-output, cost,
latency and reliability policy.

Health is structural and content-free. HMAC authentication, exact sequence,
strictly increasing observation time, previous digest, record version,
freshness window, immutable key fingerprint and stored snapshot are all
checked. Health and snapshot membership must remain exact. Duplicate routes,
catalog drift, HMAC-authority drift, health drift, replay, gaps, out-of-order
or forged observations are denied.

Route planning performs privacy, workspace, modality, local, structured and
budget hard filters before health freshness/availability, then delegates
ordering to repeated exact `ModelRouterV1` decisions. The result contains only
an explicit primary and ordered fallback metadata. Sensitive data has no
remote fallback. Cancelled, budget-exhausted and unavailable cases are explicit
blocked plans with no target.

The focused gate passes **22/22** tests. The Agentic Core V1-V6 plus Registry
V1 cumulative gate passes **156/156** tests. Golden tests use synthetic records
and authenticated observations only. They
exercise exact flag semantics, factory and immutability boundaries, duplicate
and drift denial, health authentication/monotonicity/freshness, privacy-hard
routing, every hard-filter stage, explicit blocked results, ranking and AST
absence of network/provider invocation.

`main.py`, Agentic Core V6, Live Integration V2, Gemini Compatibility C003,
Live Wiring V1 and Activation V9 remain byte-exact and do not import this
candidate. No provider SDK, external endpoint, credential, live edit,
activation, network call or E6 acceptance was used.
