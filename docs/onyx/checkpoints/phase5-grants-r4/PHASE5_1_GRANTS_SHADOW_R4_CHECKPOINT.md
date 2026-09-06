# Phase 5.1 bounded session grants R4 — shadow checkpoint

Status: candidate, default off, not accepted and not activated.

R4 supersedes the rejected R3 candidate while preserving every V1, V2 and R3
evidence byte. R3 remains historical because it did not bind exact payload and
egress semantics, used incomplete approval-response binding, held the store
lock across host callbacks, treated some budget overruns as terminal, allowed
canonical target aliases and did not bind normative or historical evidence into
its source-to-artifact DAG.

## Exact authorization contract

- `ONYX_GRANT_EVALUATOR` is still strictly default off. Disabled evaluation
  calls no host resolver, state, clock, approval, provider or execution path.
- Callers provide only an opaque invocation reference. Pinned host resolvers
  authoritatively return complete action and grant data. There is no public
  grant factory, preview, registration or caller-supplied proof surface.
- Each finite payload contract binds its SHA-256 digest, human summary, rule ID,
  egress classification and idempotency key. The scope stores a canonical sorted
  finite set; evaluation matches the actual resolved payload exactly and the
  per-action audit digest includes every payload field.
- The approval prompt displays exact targets, account, path, environment,
  effect, payload summaries and digests, what leaves the device, data class,
  risk, reversibility, idempotency, verification and rollback plans, validity,
  use limits, and cost currency, unit and bounds.
- Each request receives an unpredictable internal challenge. The pinned host
  response must echo the exact challenge, scope digest and canonical prompt
  digest. Its approval ID is structurally bound to the strictly increasing host
  attestation sequence and challenge. The sequence high-water survives cleanup
  for the full store lifetime.
- Only schema `4` and policy `onyx-approval-v4` are recognized. Host semantic
  fingerprints include principal, session, workspace, complete mission allowlist,
  complete policy fields and audit head. Drift permanently revokes; rollback
  cannot resurrect a grant.

## Atomic safety and bounded identity

- Clock, state, resolver and approval callbacks execute outside the store lock.
  Snapshot/call/re-lock generation and semantic-fingerprint checks ensure kill,
  audit failure, session end or revoke wins before insertion. Deadlock and all
  four approval-race cases are tested.
- Terminal controls record local fail-closed state without calling the host, so
  they remain effective when clock or state callbacks fail. Invalid host state
  permanently fails closed and revokes existing grants.
- The internal monotonic high-water clock prevents rollback. Per-action or
  aggregate budget overrun denies without revoking an otherwise usable grant;
  an exactly consumed use or aggregate limit revokes as exhausted.
- Windows paths reject unresolved dot aliases, repeated separators, UNC/device,
  reserved-device, trailing-dot/space and ADS ambiguity. URI identity preserves
  percent encoding while rejecting encoded dot/separator ambiguity, raw dot or
  separator aliases, userinfo, query/fragment, bad ports, unbracketed IPv6 and
  host aliases. Invalid inputs are wrapped as `GrantV4ContractError`.
- Targets, target characters, payloads, payload-summary characters, plans,
  prompts, policies, missions, grants, approvals, revocations, lifetime, uses
  and costs are all bounded. A test constructs the contract at every declared
  maximum. Every recoverable string uses `memory.store.contains_secret` and IDs
  retain strict token-like rejection.
- Low and medium risk only. High, critical and always-explicit actions deny.
  Every decision freezes `callback_required=True` and
  `authority_granted=False`.

No startup, UI, dashboard, mission, provider, owner-data, inbox, Capability
Nexus or live permission path imports or activates R4.

## Normative and historical evidence

The R4 evidence freezes `core/workspaces.py`, `docs/onyx/APPROVAL_POLICY.md`,
`docs/onyx/IMPLEMENTATION_ROADMAP.md` and
`docs/onyx/TARGET_ARCHITECTURE.md`. These are the actual policy, roadmap and
architecture sources cited here. No separate
`plans/ONYX_MASTER_IMPLEMENTATION_PLAN.md` exists in this tree, so no path was
invented.

V1 reconstructs all 10 historical files. The R2 and R3 verifiers are actually
executed and their exact top/artifact manifests are leaves in the R4 DAG. Their
historical roots remain, respectively:

- V1: `d1f5d085f0f1254ea26f3bb5221f0cf111cdd584e976bf0381a781261a31a9a4`
- V2: `ff42bcc69d1b4448837d80f42764232a5827172fe6d77c989a8b9fa90d5c0cab`
- V3: `97675a586dea63fa1ed49de68792a563a1000e2a373a8a9aed5d74a56715a7f8`

The R4 verifier resolves absolute and relative local imports, includes package
initializer execution, binds normative dependencies, validates all material
limits against AST literals, parses JUnit testcase elements and reconciles them
with suite attributes, raw log and bundle, and verifies the current base,
environment and timezone-aware timestamp. Tamper tests cover omitted relative
imports, false/empty JUnit, history omission/drift, payload/prompt claims,
limits, manifest order/encoding and cycle fields.

## Verification and acceptance boundary

Base commit: `b2dc0b21f487013cebec34bb148ffb1aeb02611a`. Environment: Python 3.13.7,
pytest 9.0.3, Windows-11-10.0.26200-SP0. The focused, adversarial and
concurrency suite passed 64 tests with zero failures, errors or skips. Ruff
`F,E9`, `py_compile`, whitespace checks and V1/V2/V3 reconstruction passed.

Rollback is to leave or unset the feature flag, or discard the in-memory store.
Restart restores no grant and needs no migration. R4 cannot authorize execution
or suppress the existing callback. The evidence root is not externally
anchored; independent review and anchoring remain required before acceptance.
This is not Phase 5 exit evidence. No commit or push was made.
