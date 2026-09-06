# Phase 5.1 bounded session grants R3 — shadow checkpoint

Status: candidate, default off, not accepted and not activated.

R3 supersedes the rejected V2 candidate while preserving every V1 and V2
evidence byte. V2 remains rejected because its authority composition could be
constructed through public preview/factory surfaces, its grant resolver did not
bind the complete human-approved operation scope, its clock and approval replay
boundaries were incomplete, and its evidence did not include the complete
transitive local dependency closure.

## R3 contract

- `ONYX_GRANT_EVALUATOR` remains off unless its value is exactly `1` or `true`
  after case and whitespace normalization. When off, evaluation does not call a
  resolver, approval callback, provider or execution path.
- `HostServices` pins existing host callbacks for grant/action resolution,
  approval, policy/workspace/mission state and a monotonic clock. The caller
  supplies only an opaque invocation reference. This is an API boundary, not a
  cryptographic claim against arbitrary same-process reflection.
- The pinned resolver returns the actual capability, tool, operation, finite
  sorted targets, account, path, effect, environment, data class, risk-relevant
  policy inputs and cost bounds. The approval callback sees that complete scope
  and its canonical digest in human-readable form.
- Scope digests are reusable across permitted repeated actions. Each action gets
  a separate audit digest bound to its invocation, resolved fields, state,
  monotonic time and sequence.
- The store uses only its pinned monotonic clock and a high-water mark. Expiry,
  schema drift, policy drift, audit-head drift, identity drift, logout, kill and
  audit failure revoke permanently for the lifetime of the in-memory store.
- Approval attestations carry a strictly increasing host sequence. An older or
  repeated sequence cannot issue a grant even after deterministic cleanup.
- Every recoverable string routes through `memory.store.contains_secret`.
  IDs, slugs and workspace IDs reject long or token-like values; targets,
  Windows/POSIX paths and URIs are normalized and bounded before comparison.
- Missions, policies, targets, grants, approvals and revocations are bounded.
  Invalid or contradictory grant specifications fail before approval. Capacity
  cleanup removes only the oldest revoked grant; active-capacity exhaustion
  fails closed.
- Low and medium risk only. Always-explicit, high and critical actions cannot
  receive a session grant. `callback_required` is frozen `True` and
  `authority_granted` is frozen `False` for every public decision.
- Concurrent evaluation is serialized against revoke, kill, audit failure,
  session end, use count and aggregate cost accounting.

No startup, UI, dashboard, mission, provider, owner-data, inbox, Capability
Nexus or live permission path imports or activates this module.

## Verification

Base commit: `b2dc0b21f487013cebec34bb148ffb1aeb02611a`, with unrelated shared worktree
changes preserved. Environment: Python 3.13.7, pytest 9.0.3,
Windows-11-10.0.26200-SP0.

The focused R3 suite passed 54 tests with zero failures, errors or skips. Ruff
`F,E9`, `py_compile`, whitespace checks, the 10-file V1 historical
reconstruction and the R2 semantic verifier all passed. The exact semantic
counts and environment are bound in the canonical bundle and checked against
JUnit and the logs.

`scripts/verify_phase5_grants_r3.py` enforces a two-level acyclic evidence DAG,
canonical manifests and JSON, exact leaf sets, the transitive local import
closure, code-derived limits, current base commit and environment, timezone-
aware JUnit timestamp, semantic test counts and an honest root-anchor status.
Tamper tests cover false counts, limits, base, dependency closure, environment,
timestamp and anchor plus missing, extra, reordered, CRLF, self/cycle, raw,
static and leaf corruption.

## Rollback and acceptance boundary

Rollback is to leave or unset the flag, or discard the in-memory store. Restart
restores no grant and requires no migration. R3 cannot authorize execution or
suppress the existing callback. The evidence root is not externally anchored;
external anchoring and independent acceptance remain required before any live
activation. This is not Phase 5 exit evidence. No commit or push was made.
