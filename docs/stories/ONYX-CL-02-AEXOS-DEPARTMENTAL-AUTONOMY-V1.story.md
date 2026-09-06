---
executor: "@architect"
quality_gate: "@pm"
quality_gate_tools: [architecture_review, impact_analysis, authority_matrix_review]
---

# Story ONYX-CL-02-AEXOS-DEPARTMENTAL-AUTONOMY-V1

**Status:** Done  
**Epic:** `ONYX-CONTINUOUS-INTELLIGENCE-AUTONOMY-V1`

## Story

Integrate the Cyryx-owned AEXOS engine through an exact-version process adapter so Onyx can plan and route work across company departments, then execute only the portions admitted by an explicit mission envelope.

## Acceptance criteria

1. The adapter authenticates an allowed AEXOS version and source digest before use and reports unavailable on drift.
2. Department selection is task-first and routed through the AEXOS squad registry; no foreign brand is exposed in Onyx output.
3. Every automated model dispatch declares a shared budget ceiling, story binding and prompt-injection scan result.
4. Away plans include deadline, allowed tools/roots/domains, cost/loss caps, checkpoints, owner-takeover and kill/reconciliation semantics.
5. External writes, publication, outreach, purchases, account actions and deployments remain approval-bound.
6. Verified work and provider costs are receipted; unknown costs fail closed for paid autonomous execution.
7. No visual files change.

## Tasks

- [x] Define the signed/version-pinned AEXOS process contract.
- [x] Materialize authenticated read-only worker discovery.
- [x] Materialize authenticated department and squad planning routes.
- [x] Admit squad execution only through authenticated external-agent receipts.
- [x] Compose model budgets, mission envelopes, approvals and execution receipts.
- [x] Validate failure, drift, kill, takeover and restart recovery.

## Current evidence

- Exact AEXOS 5.3.0 public snapshot commit and three root artifacts are pinned.
- The AEXOS validator passed 1,168/1,168 files in the isolated upstream checkout.
- The Onyx adapter authenticated that checkout and completed a real worker discovery with zero model/provider call and zero mutation.
- The task-first router authenticated the same registry digest and selected Deep Research, Marketing, Products and Sales for a live multi-department planning prompt. A short-term substring false positive was caught and corrected to word/phrase-boundary matching.
- Runtime tool `department_plan` is owner-confirmed, story-bound and budget-bound. It resolves the bundled, hash-pinned AEXOS sidecar by default and fails closed on drift.
- The exact plan is sealed into the existing Phase 11 external-agent task. The resulting encrypted patch receipt therefore binds the story, task digest, AEXOS registry digest, budget ceiling and selected squads.
- Admission remains conditional: providers without an execution-bound authenticated account receipt cannot dispatch. The installed Claude Code adapter remains health-only; deterministic/provider adapters that satisfy the receipt contract are covered by Phase 11 execution, kill, takeover and recovery tests.
- The bundled Windows sidecar contains AEXOS 5.3.0, a hash-pinned Node runtime and a production-only dependency graph with a zero-vulnerability `npm audit --omit=dev` result at qualification time.

## File list

- `core/aexos_engine_adapter_v1.py`
- `core/aexos_department_router_v1.py`
- `core/permission_broker.py`
- `vendor/aexos-engine-5.3.0/engine/`
- `vendor/aexos-engine-5.3.0/runtime/`
- `vendor/aexos-engine-5.3.0/node/`
- `scripts/onyx_agentic_cli.py`
- `tests/test_aexos_engine_adapter_v1.py`
- `tests/test_aexos_department_router_v1.py`
- `main.py`
