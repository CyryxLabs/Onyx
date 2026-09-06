# Onyx threat model

Document class: **normative Phase 0 security baseline**. It remains a security
review input, not a current release-readiness claim. Current operational and
external gates are listed in `CURRENT_RELEASE_STATUS.md`.

Status: Phase 0 security baseline, 2026-07-14. Review whenever a connector, workspace class, execution surface, model provider, data class or package channel changes.

## 1. Scope and security objective

Onyx is a local owner-operated assistant with cloud-model and external-tool reach. The security objective is to preserve the owner's authority, workspace separation, secret confidentiality, evidence integrity and recoverability while allowing bounded day-to-day automation. Onyx is not a legal principal and a model response is never authorization or proof.

In scope: desktop UI, voice/text input, remote dashboard, model calls, tool dispatch, mission persistence/worker, native/browser control, file/document processing, memory, credential vault, connectors, artifacts, audit, packaging and updates.

Out of scope for a security guarantee: compromise of the host OS administrator/kernel, malicious firmware, an already-compromised provider account, or physical attacks against an unlocked device. These remain operational risks and must not be hidden by product claims.

## 2. Assets

- Owner identity, preferences, private conversations and local files.
- Cyryx, client, professional and personal workspace data and their separation.
- API/OAuth credentials, cookies, pairing/session tokens, private keys and device tokens.
- Mission intent, exact approved plan, budgets, idempotency keys and checkpoints.
- Source bytes approved for execution and generated artifacts.
- Evidence, claims, action requests/receipts and completion status.
- Audit chains and migration journals.
- External accounts, public reputation, ad spend, purchases and production systems.
- Release artifacts, signing identities, dependencies and license provenance.

## 3. Principals and trust levels

| Principal/input | Trust | Rule |
|---|---|---|
| Local owner at trusted desktop approval UI | authorization source | May approve exact requests and issue/revoke bounded grants; still subject to non-bypassable product safety and platform law/terms |
| Authenticated remote owner session | authenticated input, not equivalent to local high-risk approval by default | May converse and request work; high-risk approval requires an explicitly designed trusted confirmation channel |
| Onyx host runtime/policy code | trusted computing base | Must validate schemas, policy, digests, paths, state and receipts independently of model text |
| Model/provider | untrusted planner | May suggest calls and content; cannot approve, classify itself safe, choose a broader workspace or assert success |
| Documents, memory, web pages, email and tool output | untrusted data | Never interpreted as system/developer policy or authorization |
| Connector/provider response | untrusted until validated and observed | Parse against schema, retain provider IDs, reconcile uncertain outcomes |
| Browser/native UI state | fallible observation | Verify target/context before and after; drift pauses execution |
| Installed dependency/update | untrusted supply-chain input | Pin, scan, license-review, build reproducibly where possible and sign artifacts |

## 4. Existing controls confirmed in code

- `core/permission_broker.py` ignores model approval claims, rejects unknown tools/actions, builds exact digests and fails closed when the callback or audit is unavailable.
- `core/tool_audit.py` stores content-free, hash-chained events and blocks update/delete through SQLite triggers.
- `core/missions.py` hash-chains per-mission events, uses bounded budgets and leases, rejects paid mission steps, does not replay an in-flight step after restart and discards late results after cancellation/pause/lease loss.
- `core/approved_execution.py` binds approval to canonical path, source SHA-256, size, arguments and timeout; it rechecks bytes before execution.
- `core/mission_tools.py` requires configured absolute workspace roots, blocks secret-shaped paths, rejects link/reparse escape and reads through verified descriptors.
- `memory/store.py` rejects secret-shaped content/metadata, uses secure-delete/WAL hardening, bounds prompt context and frames memory as untrusted data.
- `core/credentials.py` uses OS credential stores without plaintext fallback and verifies migration before scrubbing legacy fields.
- `dashboard/server.py` uses a per-install TLS certificate, one-time pairing, one-hour bearer tokens, 15-second one-use scoped WebSocket tickets, login throttling and authenticated upload/download endpoints.

These controls are real but not a claim that future workspace isolation, connector OAuth, full DLP, sandboxing, signed updates or multi-provider routing already exist.

## 5. Threat register

Likelihood and impact are qualitative for Phase 0. Residual risk must be reassessed with runtime tests.

| ID | Threat | Likelihood / impact | Current control | Required additive control / acceptance test |
|---|---|---|---|---|
| T01 | Prompt injection in web, email, document, memory or tool output changes policy or triggers tools | High / Critical | Memory framing; host permission boundary | Typed instruction/data separation; provenance on context blocks; injection corpus; show that injected text cannot change tool, workspace, target, grant or approval |
| T02 | Model invents a tool/action or marks itself approved | Medium / Critical | `MODEL_TOOL_POLICIES`, action allowlists, exact callback digest | Preserve fail-closed behavior; contract test every declared tool and action; reject model-supplied approval/grant IDs unless host-resolved |
| T03 | Approval fatigue causes indiscriminate acceptance | High / High | Per-action dialog; coarse owner-autonomy toggle | Risk-scoped expiring grants and batch review; always-explicit classes excluded; usability telemetry without payload content; tests for scope invalidation |
| T04 | Coarse owner autonomy performs unintended external mutation | Medium / Critical | Allowlist, protected source root, audit fail-closed | Replace as default path with four modes plus exact grants; keep legacy toggle disabled by default; shadow evaluation before activation |
| T05 | Cross-workspace memory/context/credential/artifact leakage | High until implemented / Critical | No first-class workspace boundary today | Mandatory `workspace_id`, deny-on-missing for enhanced paths, hard filters before ranking, separate aliases/profiles/roots; adversarial zero-leakage suite |
| T06 | Secret reaches prompt, logs, events, screenshots or artifacts | Medium / Critical | credential vault; secret heuristics; redaction/content-free audit | Central DLP classifier; field-level schemas; screenshot/clipboard redaction; canary-secret tests across every sink; never rely only on regex |
| T07 | Path traversal, symlink/reparse or TOCTOU redirects file operation | Medium / High | descriptor-bound mission reads; hardened uploads; source hash; several native file controls | Reuse bound-handle patterns for all new artifact/connectors; cross-platform race tests; forbid sidecar artifact path supplied by model |
| T08 | Mission restart/retry duplicates an external effect | Medium / Critical | stable step idempotency key; restart becomes `waiting`; late-result rejection | Connector idempotency contract, action request/receipt, provider reconciliation before retry, duplicate-response tests |
| T09 | Provider timeout is treated as failure and action is blindly retried | Medium / Critical | structured `waiting` result support | Mandatory `unknown` receipt and reconcile operation; state-machine test with timeout-after-commit |
| T10 | Audit tampering or audit outage hides autonomous action | Low / Critical | hash chains; immutable triggers; autonomous fail-closed | Startup verification; periodic head checkpoint/export; kill switch on failure; sidecar references existing audit IDs rather than copying payloads |
| T11 | SQLite sidecar corruption changes permission or state | Low / Critical | current stores detect many DB errors | Sidecar integrity constraints, signed/hash-chained envelopes, backups, transactional migrations; corruption must deny enhanced action and leave legacy state unchanged |
| T12 | Stolen/long-lived dashboard device token gives remote control | Medium / High | expiry, device revoke, bearer expiry, WS tickets | Encrypt/persist device registry only if required; per-device listing/revoke; bind sensitive approvals to trusted desktop; rate and anomaly detection |
| T13 | Self-signed TLS is ignored by user or vulnerable LAN permits impersonation | Medium / High | unique certificate with requested SANs | Fingerprint/pairing confirmation; certificate pinning in packaged companion; clear local-network threat disclosure; never claim public-CA trust |
| T14 | Dashboard AES design is mistaken for transport/auth security | Medium / Medium | HTTPS + bearer auth is primary; AES-CBC exists for commands | Document AES as defense-in-depth/legacy compatibility, add authenticated encryption only through versioned protocol, no downgrade without explicit migration test |
| T15 | Browser UI drift clicks wrong account/target or leaks data | High / Critical | per-tool approval only | DOM/accessibility-first targeting, domain/account/element context checks, headed preview, before/after evidence, fail closed on dialogs/drift, isolated profiles |
| T16 | Native automation types into password manager, banking or unrelated session | Medium / Critical | action policies; owner autonomy exclusions are incomplete for context | App/window allowlists, foreground verification, forbidden app classes, takeover/stop, rate limits and tests for focus change/DPI drift |
| T17 | OAuth token has excessive scope or remains active after workspace removal | Medium / Critical | only Gemini vault exists currently | Least scopes, alias-only records, scope health, rotation/revoke, workspace disable hook and connector-specific tests |
| T18 | Sensitive data silently falls back to a less trusted model/provider | Medium / Critical | no router today | Hard privacy constraints and explicit fallback policy; test outage cannot cross residency/data-class boundary |
| T19 | Malicious connector/MCP server advertises deceptive schemas | Medium / Critical | not implemented | Pin server identity/transport, schema allowlist/version, per-capability policy, output validation and provenance; unknown capability disabled |
| T20 | Public post, message, ad, purchase, deploy or deletion exceeds owner intent | Medium / Critical | exact tool approval; many capabilities absent | Always-explicit classes, target/payload/cost digest, preview, receipt and observed-state verification; no generic mutation connector |
| T21 | Ad budget runaway or hidden API cost | Medium / Critical | current missions require provider cost 0 | Runtime hard daily/total ceilings independent of prompt; stop-loss; quota/cost telemetry; test boundary and concurrent spend |
| T22 | Uncertain payment/booking is retried | Low / Critical | travel booking absent | Final confirmation, provider idempotency/reconciliation and verified receipt; no payment details in model/general memory |
| T23 | Night learning poisons trusted memory or modifies code/policy | High / High | explicit memory write; privacy switch | Candidate-only memory, source/corroboration gates, bounded resources; changes become review proposals; no autonomous deploy/permission expansion |
| T24 | Memory supersession silently deletes history | Medium / High | current keyed semantic update deletes prior rows | New sidecar records preserve supersession links/status; migration must not use existing category/key replacement for authoritative decision history |
| T25 | Export/delete omits replicas, FTS, WAL, artifacts or provider copies | Medium / High | memory export/forget and WAL handling | Workspace data inventory, deletion tombstone/reconciliation, artifact/sidecar/provider coverage and explicit residual disclosure |
| T26 | Dependency, installer or update compromise | Medium / Critical | host-native build, manifest hashes, package smoke | Locked dependencies, SBOM, scanning, provenance, signed packages/updates, notarization and clean-machine verification |
| T27 | License violation exposes Cyryx or forces source disclosure | Medium / Critical | plan gates identify PySide6/Qt LGPL and Cyryx Labs LLC License risks | Exact-artifact legal/license inventory and release blocker; preserve replaceability/notices/corresponding-source duties; never vendor unapproved code/assets; world-intelligence is the in-house proprietary Argos (no third-party source license) |
| T28 | Logs/telemetry become a second sensitive database | Medium / High | content-free tool audit | Redacted structured telemetry, retention limits, no message bodies/tokens/payment/identity; schema and canary tests |
| T29 | Kill switch is unavailable while worker/connectors continue | Low / Critical | worker stop and device revoke exist separately | One host-owned mutation barrier checked before dispatch; revoke grants/sessions; reconcile active actions; offline test |
| T30 | UI reports completion/capability from code presence rather than evidence | High / High | mission verifier for structured results | Capability truth status plus evidence timestamp; UI distinguishes verified/partial/unverified/blocked/simulated; acceptance tests inspect source-of-truth projection |
| T31 | Native ledger anchor is mistaken for protection against arbitrary same-process or same-user code | Medium / Critical | M2b-c remains isolated/default-off; fixed native-vault namespaces, authenticated V2 head, Merkle/MMR witnesses and immutable archive chain | Keep the boundary explicit: same-process code can monkeypatch/inspect Python and same-user processes can invoke the user's vault. Require separate production-owner privilege isolation before any stronger claim |
| T32 | A correctly anchored producer omits both a derived row and its witness | Medium / Critical | Externally anchored 19-table genesis; exact physical/witness reconciliation; semantic derivation checks | Preserve independent audited-table registry and adversarial omission tests for links, relations, action states, event history/heads and projections |
| T33 | Lifetime journal growth causes CPU amplification or unsafe rotation recovery | Medium / High | V2 authenticated head; active generation capped at 1 MiB/512 frames; immutable content-addressed archives; deterministic successor adoption | Monitor active-generation bound and archive storage; cold-audit the full authenticated archive chain; define retention/deletion only through a later reviewed policy |

## 6. High-risk abuse cases

### 6.1 Malicious document requests credential export

The document is parsed as evidence. Its instruction is tagged untrusted, never enters the policy channel, cannot select a credential alias and cannot satisfy authorization. Any attempted secret-shaped persistence is rejected. Acceptance: a corpus of role-change, tool-call and exfiltration strings produces no tool dispatch and no persisted secret.

### 6.2 Model changes recipient after approval

Normalization and digesting happen after recipient resolution and payload materialization. A different recipient, account, body classification, attachment hash or send time invalidates the approval/grant. Acceptance: mutate each field between review and dispatch; every request is denied.

### 6.3 Provider commits then times out

The receipt is `unknown`; the idempotency key and provider request ID are retained. The mission moves to `waiting` while the connector queries the provider. It must never issue the mutation again until the final state is reconciled. Acceptance: simulated timeout-after-commit yields exactly one provider-side object.

### 6.4 Browser changes account or domain

The action cursor validates origin, workspace profile, account marker, element and surrounding confirmation text immediately before click. Any mismatch pauses. Acceptance: domain redirect, modal insertion, account switch and selector reuse all prevent the click.

### 6.5 Compromised model proposes broad autonomy

Only the host creates an `AutonomyEnvelope`; the evaluator independently checks exact workspace, mission, resources, actions, expiry, stop conditions and signature. Always-explicit classes remain excluded. Acceptance: model-provided envelope/signature/approval fields never authorize.

## 7. Security gates by autonomy mode

- Observe: no external mutation path exists; reads still obey workspace, data and network policy.
- Assist: drafts/previews are artifacts only; publishing/sending/applying is a separate operation.
- Supervised Execute: every external mutation uses an exact, fresh approval unless a narrower always-safe grant applies.
- Bounded Delegate: exact signed envelope plus per-action policy; high-risk classes still interrupt for explicit approval.

Detailed rules are in `APPROVAL_POLICY.md`.

## 8. Incident response and kill switch

The global kill switch must be available from the trusted desktop independently of model/provider state. Activation must atomically:

1. Set a host-owned `mutations_blocked` flag checked immediately before dispatch.
2. Revoke session grants and autonomy envelopes.
3. Stop claiming new mission work and request worker shutdown.
4. Revoke connector tokens/sessions where supported and remote device sessions locally.
5. Mark dispatched-but-unverified actions for reconciliation; do not label them cancelled or failed prematurely.
6. Preserve redacted audit/evidence and produce an incident export.

Recovery requires local owner confirmation, verified audit integrity, credential/connector health and explicit reactivation. It must never happen automatically after restart.

## 9. Verification evidence required to close Phase 0 risks

- Threat-to-test traceability for T01-T31.
- Red-team fixtures for injection, secrets, path races, workspace crossing, grant drift, browser drift and timeout-after-commit.
- Package/license/SBOM evidence for each release target.
- Test-account evidence for each connector mutation, including revoke, rate limit, retry, cancel and uncertain outcome.
- Independent review of authentication, grants, workspace filters and migration rollback before activation.

Residual risk is accepted only by the owner with a named scope, evidence, expiry and mitigation. Silence or a passing narrow unit test is not acceptance.
