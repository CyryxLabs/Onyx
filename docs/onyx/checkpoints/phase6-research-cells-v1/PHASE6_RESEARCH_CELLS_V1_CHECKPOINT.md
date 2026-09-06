# Phase 6 Research + Independent Verifier Cells V1 checkpoint

Status: **isolated default-off Candidate 001; not live and not E6 accepted**.

## Exact inherited authority

The candidate reuses exact Agentic Core V6 and keeps direct object identity for
its `AgenticCoreV6`, `AgenticStateStoreV6` and `WorkspaceScopeV1`. The existing
`RESEARCH_OPERATOR_V1` and `VERIFIER_OPERATOR_V1` profiles are re-attested on
every operation. No Agentic Core V1-V6 byte is modified.

Two factory-only cell objects carry distinct immutable operator and instruction
profile digests:

- `provider_free_research`: authorized evidence only, citations,
  contradictions and freshness, never self-certification;
- `independent_verifier`: candidate plus canonical evidence only, validates
  every source span/digest, never executes content instructions or generates
  new facts.

## Evidence and decisions

Evidence is an HMAC-authorized, workspace-bound, classified, timestamped,
content-addressed bundle. Both each source and the complete bundle membership
carry an HMAC tag. Sources bind metadata-only URI, source/content digests and
sorted spans. Research projects every structured span into claims with exact
citations, contradiction groups and fresh/stale status.

The verifier returns:

- `ACCEPT` only for complete, supported, fresh and consistent evidence;
- `REVISE` for explicit contradiction or stale evidence; and
- `REJECT` for unsupported claims, coverage gaps or projection drift.

Research always emits `candidate_not_certified` and `certified=false`.
Finalization requires an independent `ACCEPT` bound to the exact candidate and
evidence digest.

## Integrity and resource boundary

Separate 32-byte HMAC authorities authenticate evidence and cell receipts.
Receipts bind request, workspace, cell identity, operation, input and output.
Receipt maps additionally bind their dictionary key to the authenticated
request ID. Exact replay is idempotent; conflict, forgery, drift and
cross-workspace input are denied. An exact reentrant lock serializes research,
verify and finalize so conflicting concurrent replay cannot commit twice.

The gate enforces source, span, candidate-claim, citation, serialized-byte,
freshness and deadline bounds plus exact cancellation. The candidate contains
no provider/model invocation, endpoint, credential, network import, live route,
UI or activation wiring.

## Verification

- Focused adversarial tests: **22/22 passed**.
- Cumulative Agentic Core V1-V6 + provider registry + cells: **178/178
  passed**.
- Ruff lint and formatting: passed.
- Python compilation: passed.
- Independent verifier marker: `P6_RESEARCH_CELLS_V1_OK`.
- Synthetic authorized evidence only; network calls: zero.

Coverage includes strict flag/factory behavior, exact V6 state reuse, distinct
cell identities, instruction-like content treated as opaque data,
content-addressed claims/citations, ACCEPT/REVISE/REJECT, unsupported and
invalid/incomplete-citation denial, contradiction, stale evidence, cancellation
and all evidence/candidate budgets, source/bundle HMAC forgery,
receipt/output/authority/map drift, idempotent/conflicting/concurrent replay,
classification, future timestamps, cross-workspace denial and finalization
only after independent acceptance.

## Honest limitations

The candidate does not acquire sources, browse, invoke a provider, perform
semantic extraction, judge real-world truth beyond exact structured evidence,
or prove current external availability. Source claim key/value fields are
authorized structured inputs; source text remains opaque.

The candidate is default-off, isolated and not imported by `main.py`, UI,
dashboard, runtime, packaging, QML or launchers. External E6 review is required
before any later wiring decision. This checkpoint does not activate Onyx,
unlock Phase 6 or claim Onyx completion.
