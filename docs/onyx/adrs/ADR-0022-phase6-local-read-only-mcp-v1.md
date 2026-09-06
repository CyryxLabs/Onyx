# ADR-0022: Phase 6 local read-only MCP V1

Status: Accepted for isolated candidate implementation  
Date: 2026-07-23

## Context

The Phase 6 roadmap requires one real local read-only MCP adapter while
preserving the current Onyx engine and Phase 5 catalog authority. A protocol
shaped in-process mock would not prove MCP interoperability. A generic
unrestricted MCP client would also create new authority that the current host
does not grant.

The latest stable Model Context Protocol revision at implementation time is
`2025-11-25`. Its stdio transport uses newline-delimited UTF-8 JSON-RPC, and
its lifecycle requires `initialize`, version/capability negotiation and
`notifications/initialized` before normal operations.

## Decision

Implement an additive, provider-free client adapter with these boundaries:

- exact `ONYX_PHASE6_LOCAL_MCP_V1=true` factory gate, default off;
- protocol revision `2025-11-25`;
- pinned local executable and server artifact, both SHA-256 attested before
  process creation;
- subprocess stdio with `shell=False`, bounded messages, one in-flight request,
  strict response correlation, timeouts, cancellation and bounded shutdown;
- strict duplicate-key JSON parsing, LF/CRLF framing, bounded paginated tool
  discovery and late-cancelled-response suppression;
- credentials passed only through the server environment, never in JSON-RPC,
  declarations or receipts; arbitrary parent environment values are not
  inherited and credential reflection on stdout is denied;
- exactly one locally authored public tool contract:
  `local_catalog_read`;
- server descriptions, annotations, extra tools and instructions are
  untrusted content and cannot expand Onyx authority;
- structured result validation and identity/input-bound deterministic receipt;
- no network transport, provider call, write capability, live host import or
  activation.

The adapter is a client boundary. V1 deliberately does not replace the
accepted Phase 5 catalog adapter or wire a production MCP server into
`main.py`.

## Consequences

Phase 6 now has a protocol-real stdio MCP seam that can be independently tested
against adversarial servers. Operational use still requires a separately
accepted local server composition that delegates to the Phase 5 read authority,
plus live wiring and rollback evidence. The current V9 host remains unchanged.
