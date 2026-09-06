# Phase 6 local read-only MCP V1 checkpoint

Status: **isolated additive candidate, strict default-off, not live**

Date: 2026-07-23  
Protocol: MCP `2025-11-25` over local stdio  
Platform: Windows 11, Python 3.13

## Implemented

- exact factory flag `ONYX_PHASE6_LOCAL_MCP_V1=true`;
- pinned executable and server-artifact SHA-256 attestation before launch;
- local subprocess stdio with `shell=False`;
- newline-delimited UTF-8 JSON-RPC 2.0;
- `initialize` with exact protocol negotiation and server identity;
- `notifications/initialized`;
- `tools/list` discovery and exact single `local_catalog_read` selection;
- locally authored and sanitized read-only tool declaration;
- `tools/call` with only bounded `page_size` and opaque `cursor`;
- response correlation, malformed/oversized/EOF/error denial;
- denial of server-initiated requests and unexpected notifications;
- request timeout, MCP cancellation notification and bounded process shutdown;
- identity-bound, input-bound, idempotent in-memory replay;
- content-free SHA-256 receipt with `stdio`, `egress=none` and
  `mutation=none`;
- credentials available only in the child environment;
- deterministic offline adversarial fixture.

## Verification

Focused:

```text
27 passed in 9.01s
```

Cumulative with Agentic Core V6 acceptance, Live Integration V2 acceptance and
Gemini Live Compatibility C003 acceptance:

```text
59 passed in 22.20s
```

Ruff check, Ruff format and Python compilation pass for the candidate files.
No test calls a network endpoint or provider.

Adversarial coverage includes artifact drift, workspace divergence, request-ID
conflict, cross-identity calls, protocol downgrade, duplicate tools, malicious
server instructions, extra dangerous tools, malformed JSON, oversized output,
server-initiated sampling, tool errors, timeout/cancellation, credential
redaction and factory bypass.

The independent gate additionally found and corrected five protocol/security
gaps before freeze:

- duplicate JSON object keys and non-integer response IDs are rejected;
- `initialize` is never cancelled, as required by MCP 2025-11-25;
- late responses to cancelled requests are ignored without poisoning the next
  request correlation;
- bounded `tools/list` pagination detects cross-page duplicates and cursor
  cycles;
- the child receives a minimal cross-platform environment and any attempt to
  reflect its credential over stdout is rejected.

Additional attacks cover CRLF/LF framing, a message without a newline,
duplicate completed responses, unknown notifications, argument aliases,
executable drift before launch, untrusted structured fields, parent-environment
leakage and process cleanup after failed initialization.

## Authority boundary

The MCP server may advertise arbitrary text, annotations or additional tools.
The adapter exposes only its own frozen declaration and will invoke only
`local_catalog_read`. Tool output is data; it is not Onyx policy or an
instruction source.

This candidate does not import or edit `main.py`, Activation V9/V10, the HUD,
the dashboard or packaging. It does not grant generic process execution: the
only constructible process is the explicitly pinned command supplied to the
default-off factory.

## Not yet claimed

- a production MCP server connected to Phase 5 catalog authority;
- durable receipts across process restarts;
- live/runtime wiring or user-facing MCP routing;
- Streamable HTTP;
- external provider or agent support;
- E6 external acceptance;
- Phase 6 exit.

Rollback is omission of the feature flag. With the flag off, the factory
returns before inspecting dependencies or creating a process.
