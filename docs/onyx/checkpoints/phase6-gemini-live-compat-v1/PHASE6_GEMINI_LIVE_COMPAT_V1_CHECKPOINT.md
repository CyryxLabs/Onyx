# Phase 6 Gemini Live Compatibility Candidate 003 checkpoint

Status: **isolated default-off candidate; not live and not E6 accepted**.

Candidate 003 supersedes rejected Candidates 001 and 002. The exact opt-in is
`ONYX_PHASE6_GEMINI_LIVE_COMPAT_V1=1`. It passes the host config by identity,
resolves the model through the frozen `resolve_live_model`, retains no prompt,
API key, raw event, transcript, audio or tool payload, and never falls back to
the standalone local/text route.

Golden tests cover flag adversarials, config identity and redaction, connect
and `__aenter__` unavailability, keyword-only realtime `media`, client content,
tool response, receive/cancel/budgets, strict dataclass invariants and AST
characterization of the current `main.py` Live surfaces. The AST gate requires
the wrapper and host to use exactly `media` and rejects `audio`.

No SDK network call, credential use, live import, activation or E6 acceptance
occurred. The fake-client candidate does not prove current Gemini availability,
real audio interoperability, provider session resumption or production
latency. Current `main.py` and Candidate 003 both send realtime input with the
keyword `media`; no host call site was changed.
