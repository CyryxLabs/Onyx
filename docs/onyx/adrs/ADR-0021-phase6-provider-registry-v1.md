# ADR-0021: Provider Registry + Health route-plan V1

## Decision

Introduce an isolated, exact-flag, default-off provider catalog and pure route
planner around the accepted Agentic Core contracts. The candidate imports and
uses the exact `ModelDescriptorV1`, `RouteRequestV1` and `ModelRouterV1`; it
does not define replacement routing, planning or mission types.

Provider records are frozen, versioned and identified by unique adapter and
provider/API/model routes. Prompt and evaluation metadata enter only as
precomputed SHA-256 digests. The exact descriptor owns modality, workspace,
data classification, local/network, structured-output, cost, latency and
reliability policy.

Health observations are HMAC-SHA-256 authenticated against an in-memory
32-byte authority key whose immutable fingerprint is re-attested. Sequence,
timestamp and previous authenticated digest must advance exactly, and health
entries must have an exact stored-snapshot membership match. Replay, gaps,
out-of-order timestamps, stale/future ingestion, unknown lineage, authority
substitution, forgery and post-ingestion drift fail closed. Observations
contain structural health metadata only: availability, degraded, rate-limited
or unavailable status and freshness bounds.

Routing accepts only an exact `RouteRequestV1` and classification metadata. It
applies privacy/data-class, workspace, modality, local-only, structured-output
and budget hard filters in that order; then health freshness/availability; then
repeated exact `ModelRouterV1` selection to create a deterministic ordered
primary/fallback plan. Confidential and restricted requests cannot include a
network-backed fallback.

## Non-goals and isolation

The plan has no provider invocation method and accepts no prompt, tool payload,
audio, transcript, API key or user content. It never sends data, changes
modality or silently crosses providers. The candidate is not imported by the
live host or frozen Phase 6 anchors. No network, credential, live activation or
E6 acceptance occurs in this slice.
