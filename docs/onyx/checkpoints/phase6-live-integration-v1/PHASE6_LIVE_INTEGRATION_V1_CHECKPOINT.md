# Phase 6 Live Integration V1 checkpoint

Status: **isolated additive candidate, strict default-off, not live**

Date: 2026-07-23  
Platform: Windows 11 `10.0.26200`, Python `3.13.7` x64

## Scope

This checkpoint adds the first integration facade around accepted Agentic Core
V6. It does not edit or activate any accepted/live component.

Implemented:

- a lazy compatibility adapter over the unchanged standalone
  `core/llm_client.py` text seam;
- loopback-only, workspace-bound and privacy-hard routing;
- exact one-call/600-token-reservation/zero-cost budget enforcement;
- process-bounded timeout, pre-dispatch cancellation and sanitized outcomes;
- an exact binding to accepted
  `Phase5IntegrationV3.permission_hook()` + `catalog_read()`;
- one closed read-only catalog schema with no generic executor;
- immutable, authenticated and idempotent catalog receipt persistence;
- explicit `BLOCKED_BY_ACCESS` external-agent descriptor;
- a facade that composes exact V6 and keeps MissionStore as mission authority.

Not implemented or claimed:

- `main.py`, UI, dashboard, launcher, runtime configuration or packaging wiring;
- Gemini Live audio/streaming compatibility or cross-routing;
- model-generated plans, planner memory or another model/provider;
- generic MCP/tool execution, mutations or new authority;
- installed/authenticated external-agent execution;
- Phase 6 exit, live activation or Onyx completion.

## Authority and fallback

The new factory returns `None` before dependency work unless the exact
`ONYX_PHASE6_LIVE_INTEGRATION_V1=true` value is supplied. No live surface
imports the module. Therefore the current standalone text and Gemini Live paths
remain the only host paths.

When explicitly constructed, the text adapter never cross-routes. Unavailable,
blocked or timed-out results carry stable receipt-safe reasons, allowing the
host to retain its current path as an explicit fallback decision. The catalog
binding has no fallback: unavailable Phase 5 remains truthful
`WAITING_FOR_PHASE5`.

MissionStore remains the only mission executor. The accepted Phase 5 bridge is
the authority for the provider-free catalog read. The integration records its
receipt separately and does not invent a MissionStore execution or force the
frozen V6 projection to complete.

## Verification before manifest freeze

Focused implementation tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-live-v1-dev2 tests\test_phase6_live_integration_v1.py
```

Result before manifest: **27 passed, 1 manifest test deselected, in 2.61s**.

Cumulative accepted-boundary tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp C:\MAAX_Assistant\phase6-live-v1-cumulative tests\test_phase5_integration_v3.py tests\test_phase5_integration_v3_transition.py tests\test_phase5_integration_v3_acceptance.py tests\test_phase6_agentic_core_v1.py tests\test_phase6_agentic_core_v2.py tests\test_phase6_agentic_core_v3.py tests\test_phase6_agentic_core_v4.py tests\test_phase6_agentic_core_v5.py tests\test_phase6_agentic_core_v6.py tests\test_phase6_agentic_core_v6_acceptance.py tests\test_phase6_live_integration_v1.py
```

Result before manifest: **217 passed, 1 manifest test deselected, in 69.30s**.

Static gates:

```powershell
.\.venv\Scripts\python.exe -m ruff check core\phase6_live_integration_v1.py tests\test_phase6_live_integration_v1.py
.\.venv\Scripts\python.exe -m ruff format --check core\phase6_live_integration_v1.py tests\test_phase6_live_integration_v1.py
.\.venv\Scripts\python.exe -m py_compile core\phase6_live_integration_v1.py tests\test_phase6_live_integration_v1.py
```

Result: **passed**.

After manifest freeze, the focused suite passed **28 tests** and the same
cumulative command passed **218 tests**. The standard-library
verifier:

```powershell
.\.venv\Scripts\python.exe -I -S -B scripts\verify_phase6_live_integration_v1.py
```

emitted `P6_LIVE_INTEGRATION_V1_OK`. Ruff lint/format and Python byte
compilation passed again on the frozen implementation/test/verifier bytes.

## Test coverage

- extension-off equivalence and live-surface absence;
- frozen V6, Phase 5, MissionStore, `llm_client`, main/UI/dashboard hashes;
- local/remote/credentialed endpoint classification;
- authorized provider/endpoint/model pinning against later config drift;
- workspace and privacy-class denial before provider invocation;
- text schema, success, redaction, outage, no silent cross-route;
- exact call/token/cost budget rejection, NaN/Infinity/bool rejection;
- cancellation before dispatch and terminable provider timeout;
- exact catalog schema, workspace/privacy/cancel denial;
- accepted Phase 5 authorization-to-dispatch path;
- durable replay, changed-input conflict and receipt redaction;
- receipt-schema tamper rejection without repair;
- V6 plan to Phase 5 receipt flow with no MissionStore mission;
- Phase 5 outage remaining waiting;
- external agent remaining disabled and blocked by access.

No test calls a live provider or the network.

## Resource and data impact

- Default-off resource impact: zero.
- Explicit text call: one bounded child process already defined by the accepted
  V4/V6 executor, one provider call and a 600-output-token reservation.
- Catalog call: one provider-free local read, zero cost and no egress.
- Persistence: one additive SQLite receipt file containing only identifiers,
  digests, counts, zero-cost/egress labels and a stable reason. It stores no
  prompt, system text, output, exception, endpoint, model, cursor or catalog
  item.

## Rollback and limitations

Rollback is omission/disablement of the new flag; no old file or database needs
restoration. The new sidecar is ignored by the current host.

Honest remaining gates:

1. This candidate requires independent functional, integrity and quality
   review before any activation.
2. No live host import/configuration exists.
3. Gemini Live, provider-backed planning and external agents remain separate.
4. The V6 catalog plan remains `WAITING_FOR_PHASE5` after the separately
   receipted read because frozen V6 has no accepted completion transition.
5. This checkpoint does not satisfy Phase 6 E1-E6 or claim Phase 6 exit.
