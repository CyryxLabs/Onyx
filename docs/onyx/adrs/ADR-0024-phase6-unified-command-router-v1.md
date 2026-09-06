# ADR-0024: Phase 6 Unified Command Router V1

## Decision

Introduce an isolated, strict-default-off Unified Command Router V1 around the
exact accepted `AgenticCoreV6`, Provider Registry V1, Research/Verifier Cells
V1, Local MCP V1 contracts and Live Integration V2.

The router accepts only an exact `UserCommandV1` with an explicit intent:

- `local_catalog`;
- `research_verify`; or
- `text_plan`.

Intent is never inferred from prompt or content. Each intent has one exact
modality, and tool, research and provider metadata cannot cross intent
boundaries.

## Authority and privacy

Cancellation, identity/workspace, data classification and budget/deadline
checks run before a new command can reach a component route. The host identity
must equal the exact Live Integration V2 identity and the configured Local MCP
identity. The Agentic Core, Research Cells and Live Integration must share the
same exact core and workspace objects.

The router never accepts prompt or instruction text as policy. `input_digest`
binds opaque caller content without exposing it or allowing it to select an
intent, provider or tool. Evidence remains data under the authenticated
Research Cells contract. A command cannot underdeclare an evidence source data
class.

## Intent projections

`text_plan` constructs the exact Agentic Core `RouteRequestV1` and asks the
Provider Registry for an ordered metadata plan. It forces local-private,
structured output and never invokes the selected provider.

`research_verify` passes only an exact authenticated `EvidenceBundleV1` and an
exact derived `ResearchBudgetV1` through the provider-free Research and
Independent Verifier Cells. A ready command plan requires verifier `ACCEPT` and
exact pipeline finalization. `REVISE` or `REJECT` remains explicitly blocked.

`local_catalog` creates only an exact `LocalCatalogMCPRequestV1` for the exact
`local_catalog_read` tool. It does not construct an adapter, start a process or
make a stdio call.

The exact `Phase6LiveIntegrationV2` object is identity-attested but none of its
submit, provider or catalog execution methods is called by this slice.

## Integrity, replay and evidence roots

All five component candidate manifests and available E6 records/metadata
manifests are embedded as exact SHA-256 roots and re-attested from a canonical
project root. Component or type drift fails closed.

Command plans and HMAC-SHA-256 receipts contain identifiers, decision codes and
digests only. Provider calls, process calls, network calls and live calls are
fixed at zero. Identical request replay is idempotent and returns the prior
plan/receipt. A reused request ID with any different command, evidence, cursor
or input digest is a conflict.

## Activation boundary

`ONYX_PHASE6_UNIFIED_COMMAND_ROUTER_V1=true` is the only enabled value.
Construction is factory-only, requires exact component instances and a
distinct 32-byte receipt key, and is absent from all live/main/UI/dashboard,
runtime, packaging, QML and launcher surfaces.

This ADR accepts only an isolated Candidate 001. Router E6 review, activation,
provider invocation, MCP execution and live wiring are separate decisions.
