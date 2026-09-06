# Onyx Phase 6 Local/Text Compatibility V1 External E6 Acceptance

- Evidence ID: `VE-P6-LOCAL-TEXT-COMPAT-V1-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED**
- Final findings: **P0: 0, P1: 0, P2: 0, P3: 0**

This decision accepts only the isolated Phase 6 Local/Text Compatibility V1
candidate. The frozen candidate manifest SHA-256 is
`a4c972e5ef74745884faf0c03e5bce3cad5424c524a7d03eee36a59f59ae49fc`
and the independently recomputed five-artifact root is
`9c14301f67b1f01604909265a50b9591645fa7d11451f981811e90e30da80611`.

The candidate is **default-off**, **factory-only**, requires explicit
installation, and is absent from live startup, dashboard, runtime, packaging,
QML and launcher surfaces. This acceptance did not activate it, restart Onyx,
call a provider, contact a network endpoint, or change the Unified Router,
HUD, Activation, startup or shortcuts.

## Independent result

The gate reproduced **31 passed** focused tests and **133 passed, 221 subtests
passed** in the combined candidate and regression run. Ruff check, Ruff format
check, candidate verification, external verification and Python compilation
passed. `core/llm_client.py` remained byte-exact at
`e5c0f805e0d10a07e38054316fb9c6423409190cfa0f48bc39694e65c6a4e417`.

The accepted protocol contracts cover:

- separate Ollama and OpenAI-compatible mappings with no silent retry or
  cross-route fallback;
- streaming and non-streaming response normalization, including tool-call
  parity and lazy-stream failure mapping;
- typed timeout and unavailable failures, cooperative cancellation, request
  budgets and privacy denial;
- loopback-only HTTP endpoint validation, including malformed ports and
  whitespace rejection;
- exact install ownership, owner-drift detection and restoration of the
  original host state on rollback.

Blocking deadline enforcement belongs to the injected transport. Cancellation
while that transport is blocked is cooperative; the adapter checks cancellation
before dispatch and while consuming stream items. No stronger preemptive
transport-cancellation claim is made.

## Findings resolved before freeze

The pre-freeze review found and closed five issues: lazy streaming transport
failures now map to typed compatibility errors; controlled/factory inputs now
reject falsey invalid control objects; rollback detects owner-marker drift and
restores the exact original marker state; privacy validation rejects malformed
ports and unsafe whitespace; and the injected-transport timeout/cancellation
boundary is now explicit in code evidence and documentation.

No P0-P3 finding remains open in the accepted bytes.

## Integrity and replay boundary

The external verifier enforces canonical regular paths, exact candidate
manifest identity, exact five-member closure, byte lengths, SHA-256 leaf
digests, the sorted artifact root, the frozen `llm_client.py` anchor, exact
acceptance-manifest membership and a maximum of 64 manifest rows. It fails
closed on membership substitution, traversal, links/reparse points, digest
drift and contract drift.

HMAC and replay counters are not applicable here: this evidence is an
immutable, local acceptance envelope and contains no mutable signed runtime
state, authorization token, nonce or replayable command. SHA-256 binding and
closed membership are the applicable integrity controls. Runtime authorization
and authenticated mutable state remain outside this candidate.

## Exact acceptance boundary

Accepted:

- the exact five-artifact candidate closure and frozen `llm_client.py` anchor;
- the isolated Local/Text provider compatibility contract;
- default-off factory construction, explicit install and drift-safe rollback;
- the reproducible synthetic-fake test and external verification evidence.

Not accepted or activated:

- live wiring, provider credentials, a real Ollama/OpenAI-compatible server, or
  network availability, quality, latency and resource-consumption claims;
- Unified Router integration, Phase 6 exit, live activation, startup changes,
  installer changes, shortcut changes, or completion of Onyx as a whole.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_phase6_local_text_compat_v1.py
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_phase6_local_text_compat_v1.py tests/test_regressions.py
.\.venv\Scripts\python.exe -B scripts/verify_phase6_local_text_compat_v1.py
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_phase6_local_text_compat_v1_acceptance.py --basetemp .pytest-phase6-local-text-e6-001
.\.venv\Scripts\python.exe -B scripts/verify_phase6_local_text_compat_v1_acceptance.py
```

The external verifier must emit
`P6_LOCAL_TEXT_COMPAT_V1_ACCEPTANCE_OK`.
