# ADR-0025 — Phase 6 Local/Text Compatibility V1

- Status: Candidate accepted for isolated verification
- Date: 2026-07-23
- Scope: local Ollama and OpenAI-compatible text surfaces only

## Context

`core/llm_client.py` already owns the live text path and has three public
surfaces: non-streaming chat, text-only generation, and streaming chat. The
Phase 6 work needs a reproducible compatibility candidate without changing
those call sites, defaults, provider selection, startup behavior, or existing
live integrations.

ADR-0024 is reserved for the Unified Router. This decision therefore uses
ADR-0025 and does not define or activate routing.

## Decision

Add `core/phase6_local_text_compat_v1.py` as a provider-free, factory-only,
default-off adapter.

The exact activation token is:

`ONYX_PHASE6_LOCAL_TEXT_COMPAT_V1=true`

Importing the module and constructing a disabled factory are no-ops. Even when
enabled, the factory only returns an isolated adapter; it does not install it.
An additional explicit installation call is required to replace the three
process-local function objects, and rollback restores their original object
identities.

The adapter characterizes two independent protocols:

1. Ollama: `/api/chat`, `keep_alive=-1`, the current `num_predict` and
   `num_gpu` options, and native NDJSON-style chunks.
2. OpenAI-compatible: `/v1/chat/completions`, current `max_tokens`,
   `tool_choice=auto` when tools exist, and SSE-style chunks.

There is no implicit fallback or provider substitution. A request is pinned to
the provider in its exact configuration. Only HTTP loopback endpoints
(`localhost`, `127.0.0.1`, or `::1`) are accepted. Credentials, URL paths,
queries, fragments, HTTPS endpoints, LAN hosts, and public hosts are denied.

The candidate contains no HTTP client or socket access. A host-owned transport
must be injected. Tests use deterministic local fakes and make zero real
network requests.

## Contracts

- `core/llm_client.py` remains byte-identical at SHA-256
  `e5c0f805e0d10a07e38054316fb9c6423409190cfa0f48bc39694e65c6a4e417`.
- The installed wrappers retain the existing call signatures and defaults.
- Chat results normalize to `content` plus `tool_calls`.
- Tool-call arguments converge to the same shape across both protocols.
- Streaming emits the existing `sentence` and final `done` event shapes.
- Unavailable, timeout, cancellation, privacy denial, budget exhaustion, and
  malformed contracts are distinct failures.
- Request bytes, response bytes, stream events, timeout, and cancellation are
  bounded.
- Blocking deadlines are enforced by the injected transport using the exact
  `timeout_seconds` request field. The adapter maps both eager and lazy-stream
  timeout/unavailable failures, but does not preempt an uncooperative transport
  thread. Cancellation is checked before and after invocation and between
  stream chunks; it is cooperative while the injected handler or iterator is
  blocked.
- Rollback restores all original function identities even when wrapper drift is
  detected; owner-marker drift is also detected, the original owner state is
  restored, and drift is then reported.
- No live file imports or references the candidate or its feature flag.

## Consequences

This candidate proves local text compatibility against protocol fakes. It does
not prove that a particular installed Ollama, LM Studio, LocalAI, Jan, or
llama.cpp server is operational. It does not install dependencies, invoke a
model, modify provider settings, route requests, or enter live startup.

Independent E6 acceptance remains a separate future gate.
