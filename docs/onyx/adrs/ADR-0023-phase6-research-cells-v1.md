# ADR-0023: Provider-free Research and Independent Verifier Cells V1

## Decision

Introduce an isolated, exact-flag, default-off two-cell pipeline around exact
Agentic Core V6 authority. The pipeline retains the exact
`AgenticCoreV6`, `AgenticStateStoreV6`, `WorkspaceScopeV1`,
`RESEARCH_OPERATOR_V1` and `VERIFIER_OPERATOR_V1` objects. It does not modify
or replace Agentic Core V1-V6.

The Research Cell and Independent Verifier Cell have distinct immutable
operator-profile and instruction-profile digests. Neither accepts a runtime
instruction. Evidence text is always data and never changes either profile.

## Evidence and research candidate

Research accepts only an authenticated `EvidenceBundleV1`. Each source binds:

- source ID and metadata-only HTTPS or URN URI;
- capture timestamp, exact `DataClassV1` and workspace;
- sorted source spans containing explicit claim key/value and opaque span text;
- span, content, source and bundle digests; and
- source and bundle HMAC-SHA-256 authorization tags from a separate 32-byte
  evidence authority.

The Research Cell deterministically projects all evidence pairs into
content-addressed claims and exact citations. It emits explicit contradiction
groups and per-source fresh/stale status. Its output is always
`candidate_not_certified` with `certified=false`.

## Independent verification

The Verifier Cell receives only an exact research candidate, exact evidence
bundle and bounded control metadata. It validates every citation against the
source ID, URI, source digest, span ID, span digest, claim key and claim value.
It also reconstructs the exact expected claim/citation projection and rejects
selective citation omission, unsupported or incomplete coverage and projection
drift. It requests revision for contradiction or stale evidence, and accepts
only a completely supported, fresh and consistent candidate.

Verifier reports contain decision codes, digests, finding codes, contradiction
keys and source IDs. They contain no generated claim values or new facts.
Pipeline finalization requires an authenticated verifier `ACCEPT` receipt bound
to the exact research candidate and evidence bundle.

## Authority, replay and bounds

Research and verification receipts are HMAC-SHA-256 authenticated by a distinct
32-byte receipt authority and bind operation, request ID, workspace, cell
identity, input and output digests. Identical replay is idempotent. Conflicting
replay, forged receipt, output drift, authority drift, cross-workspace evidence
and evidence forgery fail closed. Receipt/output maps are key-bound and public
research, verify and finalize operations are serialized by an exact reentrant
lock so concurrent request conflicts cannot commit twice.

Source, span, byte, freshness and deadline budgets are exact and bounded.
Candidate claim/citation item counts and serialized candidate bytes are checked
against the same request budget before verification. Cancellation is explicit.
The candidate has no provider SDK, model call, network import, live route, UI
or activation path.

## Activation boundary

`ONYX_PHASE6_RESEARCH_CELLS_V1=true` is the only enabled value. Construction is
factory-only and requires an already-open exact Agentic Core V6. The flag is
unset by default, and no live host imports this candidate.

This ADR accepts only a candidate design. External E6 review, live wiring,
provider-backed research, current source acquisition and Phase 6 exit are
separate decisions.
