# Gemini Live Compatibility Candidate 001 rejection

Candidate 001 was rejected before E6 and was never wired or activated.

It reconstructed a dictionary instead of passing through the exact host
`LiveConnectConfig`, dropping `system_instruction`; used a generic
`session.send(input=..., end_of_turn=True)` surface instead of Gemini Live
realtime/client-content/tool-response methods; lacked strict dataclass
invariants; persisted content-derived event digests; and classified
connect-context entry failures as generic errors.

Candidate 002 supersedes those bytes with identity-preserving config
passthrough, redacted shape-only attestation, exact Live surfaces,
content-free metadata, strict contracts and explicit unavailable status.
