# Phase 6 Live Wiring V2 checkpoint

Status: **isolated additive candidate, strict default-off, not live**

Date: 2026-07-23  
Platform: Windows 11 `10.0.26200`, Python `3.13.7` x64

## Implemented boundary

- exact feature flag `ONYX_PHASE6_LIVE_WIRING_V2=true`; every other value is
  off;
- disabled path returns before predecessor validation, filesystem reads,
  thread creation, child process creation, or patching;
- exact dependency on an installed `Phase6LiveWiringV1`;
- authenticated closure over 15 accepted evidence roots for Wiring V1,
  Provider Registry V1, Research Cells V1, Unified Router V1 C002, and the
  disabled External-Agent Descriptor V1;
- transactional patch of only the V1 controller instance callables
  `_create_session` and `_detach_session`;
- exact rollback that removes temporary instance method shadows and preserves
  every V1 host seam;
- one session-bound provider registry, research/verifier pipeline, local MCP
  identity, unified router, and disabled external-agent catalog;
- separate 256-bit authentication authorities for each evidence or receipt
  domain, with controller and session drift attestation;
- metadata-only provider-health and command preview;
- local catalog projection without opening an MCP process;
- replay-safe authenticated router plans and receipts;
- teardown of the V2 operational session before the V1 base session;
- fail-closed cleanup after operational construction or session-attribute
  drift.

## Provider truth

The current provider record identifies the configured Gemini Live model and
binds the current Onyx prompt digest. Because the accepted Unified Router V1
requires `local_private=True` and `network_required=False`, the remote Gemini
adapter is recorded as `BLOCKED_BY_POLICY`, not falsely as
`AVAILABLE_LOCAL`.

Text preview therefore returns an authenticated blocked plan with
`local_hard_filter`. Confidential input is independently rejected by the
privacy hard filter. Local catalog projection remains ready while recording
zero provider, process, network, and live calls.

## Verification before freeze

- Wiring V2 focused: **14 passed**.
- Wiring V1: **17 passed**.
- Provider Registry V1: **22 passed**.
- Research Cells V1: **22 passed**.
- Unified Command Router V1: **27 passed**.
- Disabled External-Agent Descriptor V1: **40 passed**.
- Local MCP V1: **27 passed**.
- Total focused and predecessor regression evidence: **169 passed**.
- Ruff lint and Python byte compilation: **passed**.

The tests cover strict default-off behavior, factory surface sealing, all
three patch failpoints, exact instance rollback, real Phase 5 session
composition, no socket or subprocess call, no new thread or child process,
provider truth, health observations, replay/conflict behavior, privacy
filtering, local catalog projection, operational construction failure,
attribute drift cleanup, key drift denial, active-session rollback, and exact
accepted-root authentication.

## Not implemented or claimed

- no live activation or shortcut currently enables this candidate;
- no current Gemini provider call is routed through Unified Router V1;
- no MCP server process is opened;
- no external-agent provider is authenticated or installed;
- no host tool, voice, UI, dashboard, permission, or execution seam is changed;
- no Phase 6 exit or complete Onyx claim is made;
- a governed remote-provider successor is still required for public/internal
  Gemini planning and execution.

