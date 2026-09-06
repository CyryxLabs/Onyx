# Onyx target architecture

Document class: **normative Phase 0 architecture baseline**. It remains the
additive-design boundary, not a current implementation or release claim. See
`CURRENT_RELEASE_STATUS.md` for implemented status and open gates.

Status: Phase 0 architecture baseline, 2026-07-14. This document specifies additive evolution only. It does not authorize a rewrite, schema cutover, connector launch, external mutation, or release.

## 1. Architecture decision in one sentence

Keep the current Onyx runtime as the trusted control plane and extend it through versioned sidecar records, typed envelopes, registries and adapters that always return through the existing permission, audit, mission and verification boundaries.

## 2. Current stable core

The following code is the compatibility boundary. New work may wrap or call it, but may not silently rename, fork, bypass or change its default behavior.

| Concern | Current source of truth | Stable contract |
|---|---|---|
| Mission state and recovery | `core/missions.py` | `MissionStore.create`, `plan_summary`, `get`, `list`, `transition`, `approve`, `run`, `cancel`, `claim_next`, `heartbeat`, `release_lease`, `resolve`, `pause`, `events`; `MissionWorker`; `normalize_mission_result`; `verify_mission_result` |
| Tool authorization | `core/permission_broker.py` | `build_request`, `authorize`, `authorize_model_tool`, `authorize_mission_tool`; unknown tools/actions fail closed; approval is an exact SHA-256 digest |
| Tool dispatch | `main.py` | `TOOL_DECLARATIONS`; `OnyxLive._execute_tool`; materialization before authorization; result audit after dispatch |
| Immutable execution inputs | `core/approved_execution.py` | `materialize_source_request`, `validate_materialized_source_request`, `execute_materialized_source`; approved bytes are rechecked and executed from held input |
| Workspace-safe mission reads | `core/mission_tools.py` | `_roots`, `_safe`, `_root_for`, `_open_verified`, `run`; provider-free and descriptor-bound reads |
| Action audit | `core/tool_audit.py` | `append_tool_audit`, `verify_audit`; content-free, hash-chained events with update/delete triggers |
| Memory | `memory/store.py`, `memory/memory_manager.py` | `MemoryStore` CRUD/search/export/retention, explicit privacy switch, bounded injection-framed prompt context, legacy compatibility API |
| Credentials | `core/credentials.py` | environment override followed by Windows Credential Manager/macOS Keychain/Linux Secret Service; no plaintext fallback; verified legacy scrub |
| Local remote surface | `dashboard/server.py`, `dashboard/security.py` | per-install TLS identity, one-time pairing, expiring bearer tokens, one-use scoped WebSocket tickets, authenticated upload/download and device revocation |
| Desktop/voice/Orb | `ui.py`, `main.py`, `core/orb_state.py`, `qml/OnyxOrb.qml` | `OnyxUI` callbacks, trusted desktop approval callback, live voice loop, `OrbHost`/`OrbStateBridge` lifecycle |
| Paths and packages | `core/paths.py`, `packaging/onyx.spec`, `scripts/build_release.py` | `resource_root`, `data_root`, per-user writable layout, host-native PyInstaller bundles and package smoke test |

Current durable mission states remain `draft`, `awaiting_approval`, `running`, `waiting`, `paused`, `succeeded`, `failed`, and `cancelled`. The richer operational lifecycle is metadata layered over these states; it is not a replacement state machine.

## 3. Trust boundaries

```text
Owner / trusted desktop UI
        |
        | exact digest, signed grant, revoke/kill
        v
Onyx Core ----------------------------------------------------+
  intent + workspace context                                 |
  MissionStore + MissionWorker                               |
  permission broker -> immutable audit                       |
  memory adapter -> workspace filters                        |
        |                                                    |
        v                                                    |
Capability Nexus (adapters, disabled until verified)         |
  official API | MCP | CLI/SDK | hardened browser fallback   |
        |                                                    |
        v                                                    |
External providers and local OS -----------------------------+
        |
        | receipt + observed final state
        v
Evidence/claim/action sidecars -> verifier -> mission events
```

The model is not a principal. Model arguments are untrusted proposals. Authorization originates only from the trusted host policy, an exact desktop approval, or a valid bounded grant evaluated by the host.

## 4. Additive target components

### 4.1 Workspace registry

`WorkspaceRegistry` is a local authoritative registry keyed by `workspace_id`. A workspace record contains display name, class (`cyryx`, `client`, `professional`, `personal`), root allowlists, artifact root, credential aliases, browser profile alias, memory namespace, retention policy, data-class ceiling, connector allowlist, network/domain allowlist, export/delete policy and active status. Every enhanced/new service call must carry an explicit valid `workspace_id`; absent, unknown, inactive or malformed workspace identity fails closed.

The registry never stores a credential value. It stores an opaque alias resolved by a workspace-aware extension to `core/credentials.py`. The current Gemini credential may be exposed as `legacy-default` only through a versioned legacy adapter that receives a trusted host-owned legacy-caller marker. User/model/connector payloads cannot set that marker, and enhanced calls never infer `legacy-default` from a missing workspace.

### 4.2 Mission context sidecar

`MissionContextStore` is keyed one-to-one by the existing `missions.id`. It carries `correlation_id`, `workspace_id`, objective, definition of done, scope, exclusions, data classification, allowed targets, budget dimensions, autonomy mode, autonomy expiry, operational phase, checkpoint, rollback plan and recovery status.

The existing mission row continues to own execution state, budgets already enforced by `MissionStore`, lease ownership and current step. Sidecar failure must prevent new enhanced actions, not corrupt or reinterpret the mission row.

Operational phases map to the current state machine:

| Operational phase | Current durable state |
|---|---|
| `INTAKE`, `CLARIFY_OR_SCOPE`, `RESEARCH`, `PLAN`, `POLICY_CHECK` | `draft` |
| `WAITING_FOR_APPROVAL` | `awaiting_approval` |
| `EXECUTE`, `VERIFY`, `CONFIRM`, `MONITOR`, `ADAPT` | `running`, `waiting` or `paused` according to actual execution condition |
| `COMPLETE` | `succeeded` |
| `BLOCKED` | `waiting` |
| `FAILED` | `failed` |
| `CANCELLED` | `cancelled` |

Changing operational phase appends a typed event and is validated against a versioned phase-transition table. It does not call SQL against the mission tables directly.

### 4.3 Evidence and action ledger sidecars

Use typed versioned records:

- `EvidenceRecord`: mission/workspace/source identity, timestamps, content hash or artifact reference, claim links, credibility/freshness and access/license note.
- `Claim`: fact/inference/forecast/recommendation/unknown, evidence links, confidence, validity window, contradictions and verification status.
- `ActionRequest`: exact connector/operation/target, normalized payload hash, idempotency key, risk, approval policy and dry-run flag.
- `ActionReceipt`: provider request ID, outcome including `unknown`, before/after/output/verification/rollback references and error class.
- `EventEnvelope`: schema version, event ID, correlation/mission/workspace IDs, actor, timestamp, type, redacted payload reference and previous hash.
- `AutonomyEnvelope`: signed exact scope, expiry, resources, policy and stop conditions.

Artifacts are stored by content-addressed reference under the workspace artifact root. The canonical relative path is exactly `<first-two-lowercase-sha256>/<lowercase-sha256>`. Publication normalizes the digest to 64 lowercase hexadecimal characters, rejects any noncanonical input, and verifies that the first path component equals the digest's first two characters before joining it to the workspace root. Ordinary SQLite rows and logs contain redacted metadata and hashes, not secrets or full sensitive payloads.

### 4.4 Approval and grant evaluator

`GrantEvaluator` runs inside `core/permission_broker.py` before the existing callback path. It may suppress a dialog only when an unexpired, unrevoked, use-limited grant exactly matches principal, session, workspace, mission, tool, normalized action, targets, data class, cost and payload digest rules. Otherwise the existing `authorize` callback is used unchanged.

High-risk classes listed in `APPROVAL_POLICY.md` cannot be satisfied by a routine session grant. Mode D requires an `AutonomyEnvelope`, but the envelope still cannot waive always-explicit approval classes.

### 4.5 Capability Nexus

Every connector implements a narrow, versioned protocol: capability discovery; health/scopes/version; read/draft/mutate separation; auth refresh through credential aliases; pagination; rate limits/backoff; dry run/test mode; idempotency; receipt capture; post-action observation; quota/cost; and degraded mode.

The preferred order is official API, official CLI/SDK, MCP, then authorized browser fallback. A browser fallback is a distinct declared capability and never hides missing API scopes.

Connectors register as disabled with a truthful capability status until access, license, contract tests and one test-account vertical slice are proven.

### 4.6 Model router and Operator Cells

The router starts with two independent versioned compatibility adapters. The Gemini Live adapter preserves `main.py:OnyxLive` plus `core/live_model.py:resolve_live_model`; the local/text adapter preserves the standalone Ollama and OpenAI-compatible backends in `core/llm_client.py`. With routing flags off, every existing call site, configuration, default, streaming/live semantic and text-generation semantic remains unchanged. Neither adapter proxies, replaces or silently falls back to the other.

Routing considers workspace privacy, modality, evaluation history, tool reliability, context, latency, cost and availability. Privacy policy is a hard constraint, not a score. Live audio/streaming parity and standalone text parity have separate evaluations and activation gates: evidence for one modality never proves the other. Rollback disables routing independently for the affected modality, returning Gemini Live calls to `OnyxLive`/`resolve_live_model` and local/text calls to `core/llm_client.py` without cross-routing.

Operator Cells are versioned role profiles over the same mission engine. They declare allowed capabilities, data class, model requirements, budget, evaluation and handoff. They do not own a second queue, database, permission system or memory store. External-impact work always includes a deterministic or independently instructed verifier.

### 4.7 Layered memory adapter

`WorkspaceMemoryAdapter` fronts the existing `MemoryStore`. It applies hard workspace, user, sensitivity, validity and freshness filters before lexical/vector ranking. New typed memory records are sidecars or schema-versioned additions; current semantic and episodic records remain readable.

Authoritative state remains relational. Object storage holds artifacts. Vector search is discovery only. Graph edges may represent dependencies and provenance, but cannot override source state or policy.

### 4.8 Command Center projections

Desktop and remote UI consume read-only projections generated from the same mission, approval, capability, evidence and cost records. UI actions invoke application services; they never update persistence directly. The current Qt callbacks and dashboard protocol remain until parity tests approve a versioned replacement.

## 5. Proposed persistence layout

Use one SQLite database per authoritative concern under `data_root()` with explicit foreign-reference validation at service boundaries. Do not use cross-database foreign keys.

| Path | Ownership | Change strategy |
|---|---|---|
| `memory/onyx_missions.sqlite3` | existing `MissionStore` | keep schema v3 and APIs stable; future migration only to add indexes/compatibility columns proven necessary |
| `memory/onyx_memory.sqlite3` | existing `MemoryStore` | keep schema v1 readable; workspace/type semantics introduced through sidecars first |
| `runtime/audit/tool_audit.sqlite3` | existing tool audit | append only; no payload expansion |
| `runtime/control_plane.sqlite3` | new sidecars | workspaces, mission contexts, capabilities, grants, envelopes, evidence, claims, action requests/receipts, memory metadata, projections and migration journal |
| `workspaces/<workspace-id>/artifacts/<first-two-lowercase-sha256>/<lowercase-sha256>` | new artifact store | canonical relative path is exactly `<first-two-lowercase-sha256>/<lowercase-sha256>`; normalize/validate 64 lowercase hex and prefix equality before root joining; policy-controlled retention; no secret vault material |

The separate control-plane database reduces risk to the working mission/memory schemas while remaining local and inspectable. It is not a second mission engine or audit ledger. Execution truth still comes from `MissionStore`; action decisions still append to `tool_audit`; sidecar event envelopes add domain provenance and reference those records.

## 6. Migration sequence and rollback

### M0: freeze contracts

Add characterization tests for all stable methods, current database fixtures at schema versions 1/2/3, tool declarations/policies, dashboard auth, credential migration, paths and packaging. Record file hashes of representative fixtures.

Rollback: tests/documentation only; no data change.

### M1a: create inert control-plane schema

Create `control_plane.sqlite3` with schema metadata, empty domain tables/indexes and a transactional migration journal only. M1a creates no workspace/domain rows, does not create `legacy-default`, does not inspect, assign or backfill mission/memory context, and does not touch existing databases. Creating the file/schema is implementation work, not activation.

Rollback: disable feature flag; preserve sidecar for diagnosis or delete only after verified export. Existing runtime ignores it and continues unchanged.

### M1b: reviewed mission/memory context backfill

Only after M1a's schema, rollback and flags-off equivalence evidence is reviewed and accepted, create `WorkspaceRegistry` and the `legacy-default` compatibility row through the explicit `LegacyWorkspaceAdapter`. Then read verified current mission/memory IDs and add reviewed context references idempotently. Record source identity/hash, start/end, counts and read-back verification. Ambiguous assignments remain explicitly pending review; they are not guessed or silently assigned by a generic fallback.

Rollback: disable context dual-read and preserve the sidecar journal. Existing mission/memory databases remain byte-compatible and authoritative.

### M2: dual-read, sidecar-write

Existing mission fields remain authoritative. Enhanced services read the sidecar only when a valid explicit workspace/context row exists; missing or invalid identity fails closed. Only the versioned legacy adapter may select `legacy-default`, and only after validating its trusted host-owned legacy-caller marker. All new typed evidence/grants are written only to the sidecar.

Rollback: turn off `control_plane_v1`; no reverse migration of mission or memory data is required.

Current implementation still stops before this runtime milestone. M2a is a
fixture-only/default-off schema-v2 shadow repository. M2b-a adds the isolated
native-vault HMAC anchor state machine. M2b-b adds an equally isolated,
owner-capability schema-v3 migration: typed append-only records, revisioned
event heads/projections, exact DDL validation, streaming state roots and
crash-recoverable anchor coordination. M2b-c now adds an isolated operational
repository around that migration: an anchored 19-table genesis, per-commit
entry Merkle roots, a commit MMR, exact physical-to-witness/semantic cold
reconciliation and detached public errors. ADR-0009 also adds a legacy-one-scan
upgrade to an authenticated V2 journal head, active generations capped at
1 MiB or 512 frames, immutable content-addressed archives and deterministic
crash-safe checkpoint adoption. Hot membership proofs are logarithmic and hot
journal work is lifetime-independent; cold ledger/archive audit remains
`O(N)`. These modules still import no startup, mission, permission, tool,
provider or UI surface; production owner wiring is deliberately unavailable.
They are not a privilege boundary against same-process monkeypatching,
same-user OS-vault access, administrator/root or host compromise. Runtime
activation remains a separate reviewed gate.

### M3: workspace-aware adapters

Introduce `WorkspaceMemoryAdapter`, credential aliases and artifact roots behind feature flags. Enhanced/new calls without a workspace ID fail closed. `legacy-default` is reachable only through the explicit versioned legacy adapter/trusted caller marker; it is never a generic default. No global search may combine workspaces.

Rollback: disable adapters; retain aliases and sidecar metadata. Never copy secrets back to JSON.

### M4: exact grant evaluation

Add grant lookup before the current approval callback. Shadow mode first records `would_allow`/`would_deny` without suppressing dialogs. Activate only after replay tests show no over-grant.

Rollback: kill switch or feature flag returns all consequential requests to the existing callback.

### M5: first connector vertical slice

Register one read-only provider/test account; then draft; then a reversible mutation with receipt and observation. No second connector until contract, failure and revoke tests pass.

Rollback: disable connector descriptor and revoke its credential alias. Mission execution returns `waiting` for unresolved provider effects.

## 7. Failure semantics

- Unknown schema, tool, action, workspace, capability, target, scope, grant, provider outcome or verification result fails closed.
- A timeout after dispatch is `unknown`, not `failed`; reconcile provider state before retry.
- A restart with an in-flight mission step follows the existing `recovery_wait` behavior.
- Sidecar unavailable: current legacy local behavior may continue only for operations that do not require enhanced workspace/grant/evidence semantics; enhanced mutations stop.
- Audit integrity failure: autonomous execution stops, matching `mark_audit_unhealthy` behavior.
- Credential resolution failure: connector is unavailable; no plaintext fallback.
- Policy or target drift invalidates approval/grant and returns to approval or `waiting`.

## 8. Required contract tests before Phase 4 activation

Here, **activation** means enabling a Phase 4 feature flag for runtime use and satisfying the Phase 4 exit gate. It does not mean starting implementation, creating the inert M1a schema, or running shadow/flags-off tests. Those implementation activities remain non-activated until their review evidence is accepted.

1. Existing tests remain green, especially `tests/test_missions.py`, `tests/test_regressions.py`, `tests/test_memory_store.py`, `tests/test_credentials.py`, dashboard security tests, Orb tests and packaging path tests.
2. Fixture migration from mission schema v1/v2/v3 and memory schema v1 is byte-preserving for legacy records.
3. Old callers produce identical results with extension flags off.
4. Sidecar row loss/corruption never widens access or changes existing mission state.
5. Cross-workspace memory, artifact, credential, browser profile, connector and mission-context attempts return zero unauthorized results.
6. Grant shadow-mode replay shows exact match only; payload/target/cost/workspace/session/expiry changes deny.
7. Every mutation creates `ActionRequest`, permission/audit evidence, `ActionReceipt` and observed-state verification.
8. Unknown external outcomes never retry blindly.
9. Kill switch prevents new mutations, revokes grants and moves affected missions to a safe waiting/reconciliation state.
10. Feature-flag rollback restores current behavior without destructive migration.

## 9. Release constraints

- Proprietary distribution remains gated by exact-artifact PySide6/Qt LGPL compliance, including replaceability, notices and corresponding-source duties, plus font/media rights and repository ownership/license reconciliation.
- macOS and Linux packages exist as build definitions, not proof of clean-machine operational readiness. Host-native CI, signing/notarization and clean-machine tests are required.
- External capabilities remain `BLOCKED_BY_ACCESS`, `BLOCKED_BY_LICENSE` or `BLOCKED_BY_PLATFORM` until current official provider evidence and test-account proof exist.
- Argos (the 100%-proprietary in-house replacement for the dropped third-party World Monitor) carries no third-party source license; each live data provider's API terms still apply.

## 10. Architectural invariants

1. One mission engine, one host permission boundary, one model tool dispatcher and one memory compatibility API.
2. No model, document, web page, connector or remote client can grant itself authority.
3. No secret enters model context, ordinary logs, memory, mission events or artifacts.
4. No workspace fallback broadens scope.
5. No action is called complete without observed evidence proportionate to its effect.
6. No approval fatigue reduction may weaken always-explicit gates.
7. No extension becomes the default before compatibility, rollback and security evidence exist.
