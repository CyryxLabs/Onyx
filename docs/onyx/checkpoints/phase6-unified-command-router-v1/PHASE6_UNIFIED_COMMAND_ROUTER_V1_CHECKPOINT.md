# Phase 6 Unified Command Router V1 checkpoint

Status: **candidate 002 ready for external gate; isolated/default-off, not
live and router E6 not performed**.

## Exact composition

The candidate requires direct exact instances of:

- `AgenticCoreV6`;
- `ProviderRegistryV1`;
- `ResearchVerifierPipelineV1`;
- `LocalMCPIdentityV1` and `LocalCatalogMCPRequestV1`; and
- `Phase6LiveIntegrationV2`.

All five component candidate manifests, their available historical E6
record/metadata roots and the Local MCP dependency reacceptance are embedded
as 14 exact SHA-256 bindings. They are
re-attested from an explicit canonical project root at construction and before
every plan/receipt operation. Component, type, workspace, identity, registry,
key or receipt drift fails closed.

## Canonical command contract

`UserCommandV1` binds an exact host identity, workspace, `DataClassV1`,
modality, budget, deadline, cancellation state, opaque input digest and one
explicit `CommandIntentV1`:

- `local_catalog` + `catalog`;
- `research_verify` + `research`; or
- `text_plan` + `text`.

The router never classifies intent from prompt or content. Evidence and cursor
metadata cannot cross intents. Cancellation, identity/workspace, privacy and
budget/deadline filters precede new component routing. Cross-workspace evidence
and evidence whose class exceeds the declared command class are denied.

## Metadata-only projections

`text_plan` creates the exact Agentic Core `RouteRequestV1` and receives only an
ordered `ProviderRoutePlanV1`. Local-private and structured-output requirements
are forced. No provider is invoked and a blocked registry plan remains blocked
without fallback.

`research_verify` requires an exact authenticated `EvidenceBundleV1`, derives
the exact `ResearchBudgetV1`, and runs the provider-free Research and
Independent Verifier Cells. A ready plan requires verifier `ACCEPT` and exact
pipeline finalization. `REVISE`/`REJECT` remains blocked.

`local_catalog` creates only the exact identity-bound
`LocalCatalogMCPRequestV1` for `local_catalog_read`. No MCP adapter is
constructed, no process is opened and no stdio call is made.

The Live Integration V2 object is required for exact host identity/object
lineage, but none of its operational methods is invoked.

## Replay and receipts

Plans and HMAC-SHA-256 receipts contain only identifiers, decision/rationale
codes and digests. Provider, process, network and live call counters are fixed
at zero. Same request/same command replay returns the prior exact plan and
receipt. Reusing a request ID with a different input digest, evidence bundle,
cursor or any other command field is a conflict. Forged receipts and plan
substitution are denied.

## Verification

- Focused adversarial tests: **27/27 passed**.
- Cumulative exact-component plus router tests: **154/154 passed**.
- Python compilation: passed.
- Ruff lint/format checks: passed.
- AST confirms no provider/MCP/live operational calls and no network/process
  imports.
- Independent verifier marker:
  `P6_UNIFIED_COMMAND_ROUTER_V1_OK`.
- Direct E6 reproduction: Agentic Core V6, Provider Registry V1, Research Cells
  V1 and Live Integration V2 passed.
- Local MCP V1 candidate 001 and historical E6 bytes remain immutable. The
  additive C002 dependency reacceptance binds them to accepted Activation V10
  C003 and reproduces all 27 focused MCP tests without rewriting either
  historical envelope.
- Network calls: zero.
- Process calls: zero.
- Provider calls: zero.
- Live facade calls: zero.

Coverage includes strict flag/factory behavior, exact type/object lineage,
accepted component roots, all three intents, no silent modality/provider/tool
crossing, local catalog projection only, provider metadata ordering and block
preservation, research `ACCEPT`/`REVISE`, cancellation, identity, privacy,
deadline and latency filters, cross-workspace and underclassified evidence,
idempotent replay, conflict, forged receipt/plan, component/type drift,
content-free projections and absence from live surfaces.

## Honest limitations

The candidate does not execute a provider, open an MCP process, acquire
research sources, infer intent, submit a mission, call the live facade, modify
UI/HUD/activation/shortcuts or prove end-to-end assistant behavior.

It is absent from `main.py`, UI, dashboard, runtime, packaging, QML and
launchers. Activation V10 C003 and the Local MCP C002 dependency reacceptance
are now exactly bound. Router E6 review and later live composition remain
separate decisions. This checkpoint does not claim Phase 6 completion or Onyx
completion.
