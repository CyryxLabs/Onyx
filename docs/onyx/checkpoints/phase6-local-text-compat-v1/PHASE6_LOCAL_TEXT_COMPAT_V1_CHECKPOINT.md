# Phase 6 Local/Text Compatibility V1 — Checkpoint

## Candidate

- ID: `phase6-local-text-compat-candidate-001`
- Feature flag: `ONYX_PHASE6_LOCAL_TEXT_COMPAT_V1`
- Only enabled value: `true`
- Default: off
- Factory-only: yes
- Live wiring: no
- E6: not performed

## Frozen host characterization

The candidate was built around, not inside, `core/llm_client.py`. The host file
is frozen at:

`e5c0f805e0d10a07e38054316fb9c6423409190cfa0f48bc39694e65c6a4e417`

Its real public surface is:

- `call_llm(messages, tools=None, timeout=120) -> dict`
- `call_llm_text(prompt, system=None, model=None, timeout=120) -> str`
- `call_llm_stream(messages, tools=None, timeout=120) -> Generator`

Ollama uses `/api/chat`; OpenAI-compatible providers use
`/v1/chat/completions`. Chat and streaming use the host's 150-token settings,
while text generation uses 600 tokens.

## Implemented evidence

- Exact disabled/no-op behavior.
- Factory-only construction.
- Strict loopback privacy policy.
- Provider-pinned requests with no cross-routing.
- Ollama request/response normalization.
- OpenAI-compatible request/response normalization.
- Non-stream and text-only parity.
- Native Ollama streaming parity.
- OpenAI-compatible SSE and fragmented tool-call parity.
- Explicit unavailable, timeout, cancellation, privacy, contract, and budget
  errors.
- Eager and lazy-stream timeout/unavailable exception normalization with zero
  retry or provider substitution.
- Pre-request and mid-stream cancellation.
- Exact controlled-operation control objects and strict URL whitespace/port
  rejection.
- Request, response, and stream-event budgets.
- Explicit process-local install.
- Exact function-identity rollback.
- Drift detection after restoration.
- Owner-marker drift detection with restoration of the original owner state.
- Provider/network-free AST verification.
- No live startup, UI, HUD, activation, router, runtime, packaging, QML, or
  launcher references.

## Verification

Focused candidate suite:

`python -B -m pytest -q -p no:cacheprovider tests/test_phase6_local_text_compat_v1.py`

Independent artifact verifier:

`python -B scripts/verify_phase6_local_text_compat_v1.py`

The manifest records exact artifact digests and frozen anchors. The verifier
recomputes them, validates the host AST characterization, scans live surfaces,
and reruns the focused suite with deterministic fakes.

## Boundary

This is an isolated compatibility candidate, not a live activation. It does not
assert that any real local model server is installed, reachable, performant, or
correct. It does not authorize Unified Router work reserved for ADR-0024.
Timeout enforcement while an injected handler is blocked belongs to that
transport; cancellation during a blocking handler/iterator call is cooperative.
Independent E6 has not been performed.
