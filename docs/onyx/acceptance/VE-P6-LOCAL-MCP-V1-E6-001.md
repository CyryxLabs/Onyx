# VE-P6-LOCAL-MCP-V1-E6-001

## Decision

ACCEPTED

## Findings

- P0: 0
- P1: 0
- P2: 0
- P3: 0

## Immutable candidate identity

- Candidate manifest: `docs/onyx/checkpoints/phase6-local-mcp-v1/manifest.json`
- Candidate manifest SHA-256: `9529946b80d4ee8c4434acd2db064afab03bbb049482e82126a57151fc395921`
- Candidate artifact root SHA-256: `c0efe67f8e28fb6444456d535f482c5af783d20508fcb48a618dd3b3ce693f6f`
- Candidate artifacts: 6
- Frozen anchors: 5

## Gate evidence

- Focused Phase 6 Local MCP V1 suite: 27 passed, 0 failed.
- Cumulative Phase 6 acceptance suite: 59 passed, 0 failed.
- Ruff check and format check: passed.
- Python bytecode compilation: passed.
- Candidate verifier: passed with the immutable candidate manifest and artifact root above.

## Protocol and security boundary

The candidate was audited against the stable Model Context Protocol revision
`2025-11-25` for the implemented client subset:

- stdio UTF-8 newline-delimited JSON-RPC framing;
- initialize/version/capability negotiation and `notifications/initialized`;
- bounded `tools/list` pagination and `tools/call`;
- exact request/response correlation, timeout, cancellation, and stdio shutdown;
- pinned executable and immutable artifact identity;
- credential injection by environment only, minimal inherited child environment,
  and denial of credential reflection through server output;
- exact read-only `local_catalog_read` projection;
- server-provided instructions, descriptions, annotations, extra tools, and
  server-initiated requests treated as untrusted or denied;
- strict duplicate-key parsing, exact integer response identifiers, bounded
  structured results, and late cancelled responses ignored;
- deterministic process cleanup using cross-platform Python subprocess
  primitives.

Adversarial coverage includes missing newline, duplicate JSON keys, boolean or
duplicate IDs, unknown notifications, credential leaks, argument aliases,
executable drift, pagination cycles, response duplication, inherited
environment leakage, and process leaks.

## Scope statement

This is an external E6 acceptance of the isolated candidate only. The candidate
remains default-off and factory-only. The gate did not activate or wire the
candidate, edit `main.py`, edit shortcuts, call any live provider, or use the
network. It is not a Phase 6 exit decision and it makes no claim of live
activation.

The cross-platform process behavior is implemented with Python standard-library
semantics suitable for Windows, macOS, and Linux. This gate was physically
reproduced on Windows; macOS and Linux packaging/runtime reproduction remain
separate platform gates.
