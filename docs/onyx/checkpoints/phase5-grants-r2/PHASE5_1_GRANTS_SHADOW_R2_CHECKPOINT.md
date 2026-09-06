# Phase 5.1 bounded session grants R2 — shadow checkpoint

Status: candidate, default off, not accepted and not activated.

R2 supersedes the rejected V1 candidate while preserving every V1 byte and its
10-entry historical manifest. V1 was rejected because raw grants could be
issued without a trusted host composition, its action/approval digests did not
semantically bind the complete scope, recoverable identifiers were too broad,
version/clock rollback could resurrect a grant, public decision construction
could override safety fields, and its evidence graph lacked an exact acyclic
root.

## R2 contract

- `ONYX_GRANT_EVALUATOR` remains off unless its value is exactly `1` or `true`
  after case/whitespace normalization.
- A non-public sentinel-backed `TrustedHostGrantAuthority` resolves principal,
  authenticated session, active workspace, mission allowlist, action policy,
  risk and always-explicit classification. This is an honest API composition
  boundary, not cryptographic secrecy against arbitrary same-process code.
- `SessionGrantStore` is opened once by that authority and accepts only a
  verified, exact, single-use trusted callback approval ID. It has no API that
  accepts caller-built `SessionGrant` values and no persistence API.
- `TypedActionRequest.v2` binds schema/policy/authority/principal/session/
  workspace/mission/capability/tool/operation/target/payload/risk/explicitness/
  data class/cost/request time. Its digest is recomputed before every decision.
- Approval digest, scope digest and approval-record digest are recomputed and
  compared with `hmac.compare_digest` before issue. Exact runtime digest,
  identity and target matching also uses constant-time comparisons.
- All recoverable strings route through `memory.store.contains_secret`. IDs
  reject path/relative/token shapes, and workspace IDs use the exact
  `core.workspaces` pattern `^[a-z][a-z0-9-]{2,63}$`.
- Expiry and host schema, policy or audit-head drift append a permanent in-memory
  revocation while holding the store lock; rolling clock/version/state backward
  cannot resurrect the grant.
- Revoke, kill, logout/session end and audit-unhealthy invalidate immediately.
- `ShadowGrantDecision.callback_required` is frozen `True` and
  `authority_granted` is frozen `False`, including public construction.
- Low/medium risk only; always-explicit, high and critical actions cannot be
  registered. Lifetime is at most 24 hours, targets 1–32 exact SHA-256 values,
  uses 1–10,000 and costs 0–10^15 integer micro-units.

No startup, UI, dashboard, mission, provider, owner-data, inbox, Capability
Nexus or live permission path imports this module.

## Verification

Base commit: `b2dc0b21f487013cebec34bb148ffb1aeb02611a`, with unrelated shared worktree
changes preserved. Environment: Python 3.13.7, pytest 9.1.1,
Windows-11-10.0.26200-SP0.

The exact focused command and output are frozen in
`phase5-grants-r2.raw.log`. Result: 67 passed, zero failures, errors or skips.
Ruff `F,E9`, `py_compile`, untracked-aware whitespace checks and the V1
historical reconstruction are frozen in `phase5-grants-r2.static.log`.

`scripts/verify_phase5_grants_r2.py` enforces a two-level acyclic evidence DAG:
the one-entry top manifest hashes only the artifact manifest; the exact artifact
manifest hashes eight leaves including code, tests, verifier, checkpoint, JUnit,
raw log, static log and canonical bundle. The bundle contains leaf hashes but no
manifest hash. Tests cover canonical success plus missing, extra, reordered,
CRLF, leaf tamper, noncanonical JSON and attempted cycle fields.

## Rollback and limits

Rollback is to leave/unset the flag or discard the in-memory store. Restart
restores no grant and requires no data migration. R2 remains a provider-free
shadow evaluator and cannot authorize or suppress the existing callback. It is
not Phase 5 exit evidence and does not implement the Approval Inbox, Capability
Nexus, connectors, autonomy envelopes or live activation. No commit or push was
made.
