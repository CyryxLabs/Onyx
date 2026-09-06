# Phase 5.1 bounded session grants R5 — shadow checkpoint

Status: candidate, default off, not accepted and not activated.

R5 supersedes the rejected R4 candidate while preserving every V1 through R4
byte and evidence root. R4 remains historical because it represented target and
payload sets independently, consumed use/cost during evaluation, discarded its
first host snapshot before resolver execution, did not bind credential/vault
rotation, accepted target canonicalization ambiguities, and did not freeze the
complete directly cited normative ancestry.

## Exact action identity

- `ONYX_GRANT_EVALUATOR` remains strictly default off. Disabled evaluation
  calls no host clock, state, resolver, approval, provider or execution path.
- Every grant contains a finite canonical set of indivisible `ActionBinding`
  records. Each binds a host-resolved SHA-256 target identity and safe/redacted
  display to the exact payload digest, payload summary, rule ID, egress class
  and idempotency key. There is no target/payload Cartesian product.
- The trusted prompt enumerates each exact target-identity plus payload pair and
  also shows account, path, environment, effect, data/risk, reversibility,
  verification, rollback, currency/unit, validity, cost and use limits.
- Raw target URLs/paths are not accepted or retained. A legitimate opaque
  lowercase-hex resource display remains valid when secret scanning permits it;
  secret-shaped displays fail before storage. Stores, prompts, logs and bundles
  contain only the canonical display and host-resolved target identity.
- Every resolver value and nested policy/binding/state/outcome/approval object
  requires an exact concrete type and is reconstructed into a fresh validated
  record. Subclasses or post-return mutation cannot bypass invariants.

## Snapshot, clock and authorization binding

- The first host clock/state snapshot is called outside the store lock, then
  processed under lock before any resolver call. It updates the monotonic high
  water, invalidates drift/expiry, clears affected reservations and captures the
  generation/fingerprint. A second processed snapshot must match; ABA or clock
  rollback cannot discard an observation.
- Clock addition is checked before issue. `now_ms` and every expiry stay within
  `0..MAX_MONOTONIC_MS`; the exact upper edge succeeds and overflow denies
  before approval.
- Host state fingerprints include complete policies and missions, audit head,
  principal/session/workspace, `credential_epoch` and `vault_generation`.
  Credential or vault rotation permanently revokes, and rollback cannot revive.
- Unpredictable challenge, exact scope digest, canonical prompt digest,
  sequence-bound approval ID and strictly increasing attestation sequence remain
  mandatory. Consumed approvals are an explicit set actually checked on issue;
  sequence high water survives deterministic cleanup.

## Two-phase shadow lifecycle

- `evaluate` is advisory and consumes nothing. `reserve` creates a bounded,
  expiring record but does not increment use or cost and cannot exceed remaining
  outstanding use/cost capacity.
- `record_outcome` accepts only an opaque reference resolved by the pinned host.
  It records callback approval, dispatch, receipt verification, receipt digest
  and status. Only the exact `verified` tuple `(true,true,true)` atomically
  commits use/cost and a bounded receipt. Cancelled, denied and unverified
  outcomes release without consumption.
- Kill, audit-unhealthy, session end, owner revoke, expiry and semantic drift
  clear reservations. Concurrent commit versus terminal control is serialized:
  terminal state observed before commit prevents consumption.
- Per-action or aggregate overrun denies without revocation. A genuinely
  consumed use or positive aggregate limit revokes as exhausted. Zero-cost
  actions remain governed by use limits without false aggregate exhaustion.
- All returned decisions keep `callback_required=True` and
  `authority_granted=False`; even a verified shadow receipt grants no authority.

## Canonicalization and callback failure

- URI displays reject raw backslashes, authority percent encoding, userinfo,
  query/fragment, noncanonical DNS, alternate/short/hex/dword IPv4, noncanonical
  or unbracketed IPv6, invalid ports, path aliases and encoded separators/dots.
  Path percent identity is preserved.
- Windows displays reject dot/dot-dot, repeated separators, UNC/device/reserved
  devices, ADS and trailing-dot/space ambiguity. Only drive/separator syntax is
  normalized; segment case is preserved.
- State, clock, grant, action, outcome and approval exceptions—including
  `KeyError`, parser and port errors—become typed `GrantV5ContractError` or
  `GrantV5Denied` fail-closed results. Host callbacks all execute outside the
  store lock. Terminal controls need no functioning callback.
- Grants, approvals, bindings, missions, policies, reservations, outcomes,
  receipts, revocations, strings, time, use and cost are bounded. Every material
  `MAX_*` is derived from code by the evidence verifier.
- Low and medium risk only. High, critical and always-explicit actions cannot be
  granted.

No startup, UI, dashboard, mission, provider, owner-data, inbox, Capability
Nexus or live permission path imports or activates R5.

## Normative and historical closure

The verifier derives and freezes the exact direct citation graph for 12 nodes:
`core/workspaces.py`, the master redesign plan, approval policy, capability
matrix, current-state audit, data/memory boundaries, gap analysis, roadmap,
license review, target architecture, threat model and verification-evidence
register. An explicitly cited existing parent omitted from the graph fails.

V1 reconstructs 10/10 historical files. R2, R3 and R4 verifiers execute and
their exact source/artifact manifests are leaves in the R5 DAG. Preserved roots:

- V1: `d1f5d085f0f1254ea26f3bb5221f0cf111cdd584e976bf0381a781261a31a9a4`
- V2: `ff42bcc69d1b4448837d80f42764232a5827172fe6d77c989a8b9fa90d5c0cab`
- V3: `97675a586dea63fa1ed49de68792a563a1000e2a373a8a9aed5d74a56715a7f8`
- V4: `191c2cc94610755f0b8d94ae2de0c7ea87456c07e771319e8589672bf070a05c`

## Verification and acceptance boundary

Base commit: `b2dc0b21f487013cebec34bb148ffb1aeb02611a`. Environment: Python 3.13.7,
pytest 9.0.3, Windows-11-10.0.26200-SP0. The focused/adversarial/concurrency
suite passed 68 tests with zero failures, errors or skips. Ruff `F,E9` and
`py_compile` passed.

Whitespace evidence is intentionally scoped—not claimed for the historical
DAG. The exact untracked-aware command is
`python scripts/check_phase5_grants_r5_whitespace.py`; it checked exactly the R5
core, checker, verifier and test files recorded in the static log.

Rollback is leaving/unsetting the flag or discarding the in-memory store.
Restart restores no grant or reservation and needs no migration. R5 cannot
authorize execution or suppress the trusted callback. External anchoring and
independent acceptance remain pending. This is not Phase 5 exit evidence. No
commit or push was made.
