# ADR-0004: Route models through provider adapters with hard privacy constraints

- Status: Accepted for phased implementation after Capability Nexus foundations
- Date: 2026-07-14
- Decision owners: Cyryx Labs / Onyx owner

## Context

The primary real-time Gemini Live flow is owned by `main.py:OnyxLive` together with `core/live_model.py:resolve_live_model`. Separately, `core/llm_client.py` implements standalone text backends for local Ollama and OpenAI-compatible endpoints; it is not the primary Gemini Live path. The master plan requires model-agnostic operation, cost/reliability routing and Operator Cells while preserving both existing contracts and preventing sensitive workspace data from silently reaching a less trusted provider.

A model is not a principal and cannot select its own credential, policy, workspace, grant or data-class downgrade. A provider abstraction must not introduce a second mission queue, permission broker or tool dispatcher.

## Decision

Introduce a feature-flagged `ModelRegistry` and `ModelRouter` above versioned provider adapters. The current Gemini Live flow and the existing `core/llm_client.py` local/text backends become separate versioned compatibility adapters. Their current call sites, configuration, streaming/text semantics and defaults remain unchanged while routing flags are off. Neither adapter replaces, proxies or silently redirects the other until task-specific parity is proven.

Each provider/model descriptor records capability/modalities, health, context limits, region/residency, permitted data classes, retention/training policy metadata, tool/structured-output support, latency/cost/quota data and evaluated quality/reliability. Credential values remain in the vault and are referenced by workspace-scoped alias.

Routing applies constraints in this order:

1. workspace, owner and data-class privacy/residency policy;
2. required modality, context, tool and structured-output capability;
3. provider/account availability, scope, quota and policy version;
4. task-specific evaluation/reliability threshold;
5. latency and economic cost within hard mission/workspace budgets.

Privacy and authority are hard filters, never weighted preferences. An outage cannot cross a workspace's provider/data-class boundary. If no eligible model exists, the mission waits or reports a truthful blocked/degraded state.

Operator Cells are versioned role profiles over the existing `MissionStore`/`MissionWorker`. They declare allowed capabilities, data classes, model requirements, budgets, evaluation and handoff/verifier rules. They do not own a second queue, database, memory store, permission system or dispatcher. External-impact work uses a deterministic verifier where possible or an independently instructed verifier with separate evidence.

## Provider adapter contract

- normalized request/response and streaming/cancellation behavior;
- workspace disclosure manifest and redaction result;
- model/provider/version/account identity in result provenance;
- token/media/tool usage, latency, cost estimate/actual and quota state;
- structured error taxonomy and retry eligibility;
- no secrets in prompt, response metadata or ordinary logs;
- no tool execution outside the existing dispatcher and broker;
- explicit unsupported/degraded status rather than invented parity.

## Rollout

1. Characterize the Gemini Live path in `main.py`/`core/live_model.py` and the standalone Ollama/OpenAI-compatible text paths in `core/llm_client.py` independently.
2. Wrap each path as its own versioned adapter without changing call sites, configuration, request/response mode or default selection.
3. Add registry/health projection with routing disabled.
4. Run shadow routing and compare the selected compatibility adapter and result metadata against each original path.
5. Add one provider-free research Cell and independently instructed verifier Cell.
6. Add or cross-route another model/provider only after privacy, modality, streaming/text parity, fallback, cost and golden-evaluation gates pass.

## Verification

- Flags-off Gemini Live calls resolve through `OnyxLive`/`resolve_live_model` with the same configuration and public behavior; flags-off local/text calls continue through `core/llm_client.py` with the same Ollama/OpenAI-compatible behavior.
- Adapter parity is evaluated separately for real-time audio/live interaction and standalone text generation; passing one mode never proves the other.
- Privacy/data-class/residency denials cannot be overridden by lower price, higher score, prompt text or model output.
- Workspace/account/credential aliases cannot cross boundaries or appear in model context.
- Outage, quota, cancellation, malformed structured output, context overflow and fallback tests produce truthful states.
- Golden mission evaluations establish minimum groundedness, tool reliability and verifier behavior before a route is enabled.
- Cost/token/quota ceilings are enforced outside prompts and under concurrent missions.
- Operator Cells cannot bypass the single mission engine, permission broker, dispatcher, audit or memory adapter.

## Rollback

Disable router and Operator Cell flags. The primary Gemini Live flow returns directly to `main.py:OnyxLive`/`core/live_model.py`, and standalone local/text callers return directly to `core/llm_client.py`; provider descriptors and evaluation evidence remain read-only for diagnosis. Revoke a provider alias without copying secrets, merging the two compatibility paths or silently selecting another provider.

## Rejected alternatives

- Let the model choose a provider from prompt instructions: policy and privacy would be model-controlled.
- Route solely by price or benchmark score: ignores data boundaries and task reliability.
- Give each Operator Cell its own agent runtime/queue: duplicates execution truth and security controls.
- Claim provider portability from a common text interface alone: omits tools, modalities, policy, cancellation and evidence semantics.
