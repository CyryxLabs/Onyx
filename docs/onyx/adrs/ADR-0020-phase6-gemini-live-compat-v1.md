# ADR-0020: Exact-call Gemini Live compatibility Candidate 003

## Decision

Use a factory-only, exact-flag, default-off wrapper around the existing Gemini
Live transport. The exact host `LiveConnectConfig` object is passed unchanged
to `client.aio.live.connect(model=..., config=...)`. A separate redacted
attestation records AUDIO/transcription/resumption/voice/tool shape and whether
a system instruction exists, but never stores or hashes its content.

The wrapper exposes a host-compatible keyword-only
`send_realtime_input(*, media=...)` surface and delegates with the unchanged
`media=media` keyword, plus distinct client-content, tool-response and receive
operations. Cancellation, timeout, connect failure and context-entry failure
have explicit statuses and never cross-route to local/text inference. Event
receipts contain only deterministic structural metadata.

## Isolation

`main.py`, `core/live_model.py`, Activation V9 and accepted Phase 6 artifacts
remain byte-exact and do not import the candidate. Characterization tests parse
the current host AST, including exact connect/config, client-content,
realtime-input and `system_instruction` construction surfaces. The golden AST
requires exact `media` keyword parity between host and wrapper and rejects the
incompatible `audio` spelling.
