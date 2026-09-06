# Onyx approval and autonomy policy

Document class: **normative Phase 0 baseline**. It is retained for policy
history and is not the current release-status authority. Use
`CURRENT_RELEASE_STATUS.md` for the shipped candidate and
`DOCUMENTATION_INDEX.md` for document precedence.

Status: Phase 0 normative policy, 2026-07-14. Current runtime behavior remains authoritative until this policy is implemented and verified. This document reduces approval fatigue through exact bounded authority; it does not grant blanket access.

## 1. Policy goals

1. Routine reading, research, drafting, local organization and reversible preparation should feel natural.
2. Authority must be granted by the owner/host, never inferred from a model, document, page, memory or provider response.
3. Approval binds to the exact meaningful action: workspace, principal/session, mission, tool/operation, target/account, normalized payload or allowed transformation, data class, amount/cost and expiry.
4. High-impact actions always pause for explicit approval even in delegated mode.
5. Unknown policy, state, target, scope, outcome or audit health fails closed.

## 2. Compatibility with the current boundary

`core/permission_broker.py::authorize_model_tool` remains the single model-tool authorization entry point. `build_request` and `authorize` remain the trusted exact-digest callback path. `authorize_mission_tool` remains the mission-step boundary. `main.py::OnyxLive._execute_tool` continues to materialize runtime arguments before authorization. `core/approved_execution.py` continues to bind executable source bytes.

The new evaluator is an additive pre-check inside the host boundary:

```text
validate tool/action/schema
  -> classify workspace/data/risk
  -> materialize target/payload/cost
  -> block if kill switch/audit unhealthy
  -> evaluate exact grant or autonomy envelope
  -> if not covered, call existing trusted approval UI
  -> append decision audit
  -> dispatch
  -> receipt + observe final state
```

Model fields such as `approved`, `approval_id`, `grant`, `risk`, `workspace_id` or `autonomy_mode` are proposals only. The host resolves all authoritative records.

## 3. Four autonomy modes

### Mode A — Observe

Allowed without per-request dialogs after workspace/session selection:

- Monitor authorized sources and connector health.
- Read data already covered by workspace policy and least scopes.
- Search, summarize and alert.
- Build evidence/claims and show uncertainty.

Forbidden: external mutation, local file mutation, memory promotion, sending, publishing, scheduling, purchasing, deploying or applying a change.

### Mode B — Assist

Includes Mode A and permits:

- Research, plan, draft and create previews/change sets in a workspace artifact area.
- Create candidate memories and proposed decisions.
- Run deterministic validation against drafts.

Draft and preview artifacts are not external mutations. Moving a draft into a live provider, production repository, public channel or authoritative memory is a new action governed separately.

### Mode C — Supervised Execute

Includes Modes A/B. External or authoritative mutations execute one by one after an exact approval unless a low/medium-risk session grant covers them. The review shows human-readable target/account, payload summary, data class, expected effect, cost, reversibility, idempotency and verification plan.

Current cautious behavior maps here until the new policy exists.

### Mode D — Bounded Delegate

Includes Modes A/B and may execute covered low/medium-risk actions without repeated dialogs only under a signed, expiring `AutonomyEnvelope` and exact runtime policy. High-risk/critical and always-explicit actions remain gated.

An envelope contains:

- ID, schema/policy version, principal, session, workspace and mission.
- Issued/start/expiry times and revocation state.
- Allowed repositories/branches/directories/apps/domains/accounts/connectors/models/tools/actions/data classes.
- Forbidden actions/targets/data classes.
- Maximum money, tokens, compute, API calls, storage, network and wall-clock time.
- Deployment environment and permitted side effects.
- Required tests, evidence, verifier and postconditions.
- Notification/escalation rules, approval policy and stop conditions.
- Canonical digest and host signature/MAC over the complete envelope.

No envelope is global or indefinite. A missing workspace/mission, wildcard external target, unknown policy version or unverifiable stop condition is invalid.

## 4. Risk classes

| Class | Examples | Default treatment |
|---|---|---|
| Low | public-source reads; local status; deterministic draft formatting; read-only inventory inside an exact workspace root | A/B may proceed under active workspace policy; log provenance |
| Medium | reversible local file creation in a dedicated artifact root; calendar draft; provider draft object; approved batch content preparation | C exact approval or D exact grant/envelope; receipt and verification required |
| High | external send/publish; repository push; shared-calendar mutation; production configuration draft apply; ad targeting change; sensitive data export | explicit approval, narrow target/payload, independent verification; routine grants cannot cover unless a named policy explicitly permits a bounded repeated action and it is not always-explicit |
| Critical | payment/purchase; ad enablement/spend expansion; production deployment/destructive migration; auth/secret/role change; legal/crisis/security communication; sensitive deletion; protected-branch merge | always explicit immediately before commitment; no suppression by session grant/envelope |

Risk is assigned by host policy using operation, effect, target, environment, data class, amount, reversibility and verification. Model/provider labels cannot lower it. Unknown maps to the more restrictive treatment.

## 5. Always require explicit approval

The following cannot be pre-approved by a routine session grant and cannot be waived by Mode D:

- Purchase, payment, billing change or final travel booking.
- Enable ads, remove/increase a spend cap or exceed a pre-approved amount/window.
- Public statement outside an explicitly approved content calendar/payload class.
- Legal commitment, contract, representation, filing or acceptance of terms.
- Production deployment, destructive migration, production data mutation or rollback with material impact.
- Merge to a protected branch.
- Delete or export confidential/restricted data.
- Change authentication, secrets, roles, permissions, OAuth scopes or security controls.
- Send a sensitive or consequential message.
- Crisis, political, legal, personnel, security or incident communication.
- Install unreviewed software with privileged access.
- Disable/alter audit, DLP, workspace isolation, kill switch or approval policy.
- Any action whose final state cannot be verified.

Approval must show exact target/account/environment, material payload, amount/cost/currency, expiry and expected final state. A material change invalidates it.

## 6. Grants that avoid approval fatigue

### 6.1 Session grant

A session grant is immutable, local, expiring and use-limited. Required fields:

`grant_id`, schema/policy version, owner principal, authenticated session ID, `workspace_id`, optional `mission_id`, tool/capability and operation, exact roots/domains/accounts/recipients or target pattern from an approved finite set, max data class, payload rule/digest, risk ceiling, per-action and aggregate cost, use count, issued/start/expiry, approval digest, revoke state and audit head.

Default maximum lifetime is one active local session and never beyond 24 hours. More restrictive capability policies may impose minutes or one use. Logout, workspace switch, audit failure, policy/schema change, credential rotation, kill switch or target/payload drift invalidates the grant.

### 6.2 Calm batch approval

A batch is a reviewed finite manifest of exact actions, not a generic category. Each item has its own normalized digest/idempotency key and may be independently failed, revoked or reconciled. Adding/replacing an item requires new approval. Examples: schedule ten already-reviewed posts or create five calendar holds for named attendees/times.

### 6.3 Approved policy window

Repeated low/medium-risk actions may use a finite policy window, such as reading one mailbox for a daily brief or publishing already-approved calendar items. The policy specifies workspace/account, operation, schedule, content class, limits, dates, exception/escalation rules and verification. It never covers a changed recipient/account, confidential disclosure or always-explicit class.

### 6.4 No-dialog cases

Only these need no per-request dialog when host policy and workspace selection already cover them:

- Immediate safety stop, pause, revoke or kill.
- Pure computation on already-authorized in-memory inputs with no new disclosure.
- Public/provider-free data operations that expose no local/private information and create no effect.
- Read-only operations under Mode A and an authenticated, least-scope workspace connector.
- Draft/preview creation under Mode B in the dedicated workspace artifact area.
- Exact action covered by a valid session grant or Mode D envelope and not an always-explicit class.

All are still subject to audit/provenance appropriate to risk.

## 7. Exact matching rules

Before any permission decision the host canonicalizes:

- Workspace, mission, principal and authenticated session.
- Connector/provider/API version, operation and real account/tenant.
- Canonical local path/root or normalized URL/domain/resource ID.
- Resolved recipient/attendee/channel/repository/branch/environment.
- Payload bytes or a policy-defined normalized payload hash.
- Attachments/artifacts by content hash.
- Amount, currency, spend cap, token/API/compute/time limits.
- Data classification and intended disclosures.
- Dry-run/live mode, idempotency key, verification and rollback plan.

Comparison is constant-time for digests. Wildcards are forbidden for external recipients, payments, production, credentials, roles and sensitive exports/deletes. Relative paths and unresolved aliases cannot be approved.

## 8. Request lifecycle

1. Validate schema and action allowlist.
2. Resolve workspace from trusted session/mission, never only from request text.
3. Resolve aliases and materialize exact target/payload without exposing secrets.
4. Compute risk and policy from host-owned tables.
5. Check kill switch, audit integrity, capability health/scopes/license and budget.
6. Build `ActionRequest` and idempotency key.
7. Match a grant/envelope or show the existing trusted desktop approval.
8. Revalidate state, target, payload, expiry and limits immediately before dispatch.
9. Append authorization decision to `tool_audit`; dispatch once.
10. Store `ActionReceipt`, retrieve/observe provider state and compare with intent.
11. Mark succeeded only with sufficient postcondition evidence. Unknown/partial goes to reconciliation or `waiting`.

Approval never means success; it means permission to attempt the exact action.

## 9. UI requirements

The approval surface must prioritize comprehension over raw JSON while retaining an expandable canonical detail view and digest. It shows:

- Onyx workspace and real external account/tenant.
- Mission and why the action is needed.
- Action, exact target/recipient/environment and material payload summary.
- Data class and what leaves the machine.
- Expected effect, reversibility, verification and rollback/recovery.
- Money/resource cost, risk class and grant duration/use scope if offered.
- Buttons for deny, approve once, approve finite batch, grant exact bounded window, and cancel/kill where eligible.

It must never offer a broad grant for an always-explicit class. Deny is the safe default. Grant details are editable only by narrowing scope.

## 10. Remote approval

An authenticated remote dashboard session may request work, pause/kill, and approve low/medium-risk actions only after a separately designed trusted-channel review. Existing bearer authentication alone is not proof of local physical presence or sufficient for critical approval. Until device-bound signatures and an approval-specific UI are implemented and tested, always-explicit approvals use the trusted desktop callback.

## 11. Revocation and emergency behavior

- Revoke and kill are prompt-free.
- Revocation is effective before the next dispatch, not eventually after a queue drain.
- In-flight external calls are cancelled only when provider semantics are safe; otherwise they are reconciled.
- Kill switch blocks all new mutations, invalidates grants/envelopes and stops new mission claims.
- Restart does not restore grants unless their signed persistence policy explicitly allows it; default is session-only.

## 12. Compatibility migration

1. Keep current `cautious` and `autonomous` configuration readable.
2. Map `cautious` to Mode C behavior while flags are off.
3. Map legacy owner autonomy only to a compatibility profile with its current allowlists; do not silently promote it to Mode D.
4. Introduce grant evaluation in shadow mode, recording no payload content.
5. Activate A/B read/draft suppression first, then one low-risk grant class, then one medium reversible class.
6. Deprecate the coarse toggle in UI only after the new modes have parity, migration, revoke and rollback tests. Continue reading it for rollback compatibility.

Rollback: disable the grant evaluator and mode UI; all consequential actions return to current exact callback behavior. Existing settings are not deleted.

## 13. Mandatory tests

- Every declared tool/action has a host policy; unknown values deny without prompting.
- Model-supplied approval/grant/risk/workspace fields cannot authorize or lower risk.
- Exact-digest tests mutate each meaningful field and prove denial.
- Grant expiry, use exhaustion, logout, revoke, workspace switch, audit failure, policy change and kill switch deny.
- Batch additions/substitutions deny; remaining valid items retain independent digests.
- Always-explicit classes prompt in all four modes.
- Low-risk A/B flows avoid repetitive dialogs without allowing mutation.
- Mode D cannot exceed targets, time, spend, calls, compute, data class or stop conditions.
- Dispatch timeout after provider commit creates one effect and enters reconciliation.
- Approval UI renders the complete payload/details and defaults to deny.
- Existing permission, mission, regression and audit tests remain green with flags off.

## 14. Policy acceptance criteria

- 100% of always-explicit test actions fail without a fresh exact approval.
- 100% of external mutations have an action request, decision audit, receipt and observed-state verification or explicit unknown/blocked status.
- Zero cross-workspace grant matches.
- Zero secret values in approval records, audits, events or logs.
- Routine read/draft scenarios complete without one dialog per tool call while remaining within a visible, revocable scope.
