# Phase 6 Gemini Live Compatibility Candidate 002 rejection

Candidate 002 was rejected before E6 and was never live.

Although it corrected exact config identity, redacted attestation, strict
invariants, unavailable connect/enter failures and content-free event metadata,
its realtime wrapper exposed and delegated `audio=`. The unchanged real host
call site in `main.py` uses `send_realtime_input(media=msg)`. Candidate 002
therefore failed unchanged-call-site compatibility.

Candidate 003 replaces that surface with keyword-only `media` and delegates
`media=media`. A golden AST comparison requires exact keyword parity with the
host and explicitly rejects `audio=`.
