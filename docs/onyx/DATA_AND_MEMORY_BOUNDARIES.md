# Onyx data and memory boundaries

Document class: **normative Phase 0 baseline**. It is retained for design
history and does not state current release readiness. Use
`CURRENT_RELEASE_STATUS.md` and `DOCUMENTATION_INDEX.md` for current status and
precedence.

Status: Phase 0 normative design, 2026-07-14. Current storage remains unchanged until versioned migrations and tests are approved.

## 1. Boundary principle

Every stored, retrieved, disclosed, exported or deleted item belongs to one owner principal and one workspace. Workspace, sensitivity, source validity and freshness filters run before relevance ranking. Similarity, a model assertion or a file path never grants authority.

## 2. Current state confirmed in code

### Paths

`core/paths.py` separates packaged read-only assets (`resource_root`) from writable owner data (`data_root`). Source checkouts deliberately preserve the historic in-repository layout. Frozen Windows, macOS and Linux releases use per-user application-data roots, with `ONYX_DATA_DIR` as the explicit override. Writable subdirectories are config/certs, memory, runtime/audit and uploads.

### Memory

`memory/store.py` schema v1 stores semantic and episodic records in `memory/onyx_memory.sqlite3`, with source/citation, salience, optional session/task/category/key metadata, deterministic dedupe, optional FTS5, secure-delete/WAL settings, retention, atomic export and a memory audit table. `memory/memory_manager.py` preserves the legacy structured API and imports `long_term.json` without deleting it.

Current memory is not workspace-aware. Searches can span every record in the database. Keyed semantic updates delete older rows with the same category/key, so that path cannot represent authoritative supersession history. `memory_audit` is an operational audit but is not hash-chained.

### Secret and injection controls

Memory writes reject secret-shaped fields/content; prompt context is bounded, cited and explicitly framed as untrusted reference data. `core/missions.py` also redacts secret/injection patterns from persisted mission values. These are useful controls, not complete DLP or classification.

### Credentials

`core/credentials.py` stores the current Gemini credential in the OS vault and keeps non-secret settings in `config/api_keys.json`. It has one global service/account identity, not per-workspace aliases. No secret is intentionally stored in memory.

### Other data

- Missions: `memory/onyx_missions.sqlite3`, schema v3, including steps, results and hash-chained events.
- Tool audit: `runtime/audit/tool_audit.sqlite3`, content-free and hash-chained.
- Dashboard TLS key/certificate: `config/certs`; key is per-install and filesystem-protected where supported.
- Dashboard bearer, WebSocket, pairing and device tokens: process memory only in the current implementation.
- Uploads: `uploads`, authenticated and hardened against link/race attacks.
- Dashboard history: bounded process memory; it may contain conversation/status messages and is not durable by design.

## 3. Workspace classes

The initial registry supports separate records for:

| Class | Examples | Default sharing |
|---|---|---|
| `cyryx` | Cyryx Labs, MAAX Studio, Lyra | only explicitly related Cyryx workspaces; no client/personal inheritance |
| `client` | each external customer or engagement | isolated per client; no cross-client retrieval |
| `professional` | employer or other professional context | isolated from Cyryx, clients and personal |
| `personal` | owner personal administration | isolated from every business workspace |

Each workspace has its own policy, allowed roots/domains/accounts/connectors, credential aliases, browser profile, memory namespace, artifact root, data-class ceiling, retention, export/delete scope and audit projection. There is no implicit “all workspaces” operational mode. Cross-workspace comparison requires a new explicit mission naming each workspace and a policy-approved sanitized result workspace.

Enhanced/new calls must provide an explicit valid workspace and fail closed when it is absent, unknown, inactive or malformed. `legacy-default` is a compatibility identity, not a fallback: only a versioned legacy adapter with a trusted host-owned legacy-caller marker may select it. The marker cannot originate in user, model, document, connector or remote-client payloads.

## 4. Data classification

| Class | Examples | Model/connector treatment |
|---|---|---|
| Public | published Cyryx pages, official docs, public research | may use workspace-approved remote provider; provenance required |
| Internal | nonpublic plans, ordinary project status, internal drafts | approved workspace providers only; no public disclosure |
| Confidential | client material, financials, private communications, unreleased product data | least-context disclosure, provider/data-residency policy, no fallback to a less trusted model |
| Restricted | credentials, private keys, auth codes, session cookies, full payment/passport data, protected personnel/security data | never enter model context, general memory, mission event, ordinary log or general artifact; use vault or user-entered checkout only |

Classification is assigned from trusted workspace/source policy and DLP inspection. A model may propose a higher class but cannot lower it. Unknown sensitive input defaults to the more restrictive treatment.

## 5. Layered memory model

1. Session memory: current interaction/mission context; expires with policy and is not automatically durable.
2. Episodic mission memory: redacted actions, outcomes, receipts and lessons linked to mission/evidence.
3. Semantic institutional memory: approved verified entities, facts, relationships and definitions.
4. Decision memory: proposals, approved/rejected/superseded decisions and rationale; history is never silently deleted.
5. Procedural memory: versioned skills/workflows with provenance, evaluations and release approval.
6. Preference memory: explicit owner preferences with workspace/scope, sensitivity and revocation.
7. Temporal status memory: current state, owner, verified time, validity/refresh and definition of done.

New items use typed `MemoryItem` semantics: ID, workspace, namespace, type, content/artifact reference, source references, sensitivity, confidence, timestamps/validity, supersession link and `candidate|approved|superseded|rejected` status.

## 6. Write policy

Durable memory is opt-in through the existing privacy switch and one of these host-owned causes:

- The owner explicitly requests/approves the memory.
- A mission policy permits a narrowly typed episodic receipt/lesson.
- A verified source enters `candidate` through the Knowledge Refinery.
- A reviewed promotion changes candidate to approved.

The assistant must not store raw transcripts, complete emails, credentials, auth/session data, full payment/passport data or unnecessary personal identifiers. Store the minimum fact, provenance and validity needed. Consequential facts require a primary/authoritative source or corroboration. Low-confidence material remains candidate research.

Every write records workspace, source references, sensitivity, confidence, reason/policy, actor, timestamp and prior/superseded link. Duplicate content is linked or merged without erasing provenance.

## 7. Retrieval policy

Retrieval order is mandatory:

1. Resolve authenticated principal, active workspace and mission from trusted host state.
2. Enforce workspace and permitted cross-workspace set.
3. Enforce user/access policy and sensitivity ceiling.
4. Exclude expired/invalid/rejected records; mark stale records rather than silently treating them current.
5. Enforce source availability/license/deletion constraints.
6. Apply lexical/vector/graph ranking.
7. Return bounded, provenance-rich content framed as untrusted data.

Vector similarity never bypasses steps 1-5. Candidate, disputed and stale records are labeled and cannot satisfy a fact-required operational gate without fresh verification.

## 8. Proposed additive storage

Keep existing memory rows intact. Add to `runtime/control_plane.sqlite3`:

- `workspaces` and `workspace_policies`.
- `memory_items` metadata keyed to existing `memories.id` or a content-addressed artifact.
- `memory_sources`, `memory_supersessions`, `memory_contradictions` and `memory_access_policy`.
- `artifact_index` containing workspace, digest, media type, class, source, created/expiry and relative content-addressed path.
- `deletion_jobs`/`export_jobs` with store-by-store receipts.

New authoritative memory uses sidecar metadata and may retain content in existing `MemoryStore` only when the content/class is supported. Sensitive or large content is an encrypted/content-addressed artifact reference, never packed into metadata. Restricted secrets remain exclusively in the OS/provider vault and are referenced by alias only.

The sidecar database is not a second search authority. `WorkspaceMemoryAdapter` joins/filters authoritative metadata before calling existing lexical search or any future vector index.

## 9. Credential boundaries

- A credential alias contains provider, workspace, account/tenant identifier, scope metadata, vault locator and rotation/revoke timestamps; never the secret.
- OS vault service/account names become workspace/provider specific through a versioned naming function.
- The existing `Onyx.GeminiAPIKey`/`gemini` entry remains the `legacy-default` alias and is not moved or deleted during Phase 4.
- Environment credentials are explicit process-wide overrides and must be rejected for multi-workspace use unless bound by startup configuration to one workspace.
- OAuth access/refresh tokens, cookies and private keys never enter SQLite, memory, model prompts or ordinary logs.
- Connector health may expose configured/absent/backend/scopes/expiry, never token material.

## 10. Artifact boundaries

Artifacts live under a workspace-owned root. The canonical relative path stored in `artifact_index` is exactly:

`<first-two-lowercase-sha256>/<lowercase-sha256>`

The physical path is the workspace artifact root joined with that relative path. Before joining, normalize the computed SHA-256 to exactly 64 lowercase hexadecimal characters, reject user-supplied/noncanonical digests, require the first component to equal the digest's first two characters, and reject separators, traversal or alternate encodings. Metadata stores original display name separately and never uses it as a filesystem path. Writes use an exclusive temporary file, content hash, verified handle and atomic no-replace publication following the hardened dashboard upload pattern. Symlinks/reparse points, device files and cross-root paths are rejected. Before a consequential use, the digest and policy are rechecked.

Screenshots/traces are classified before persistence and redacted for credentials, payment/identity data and unrelated applications. Raw browser profiles, cookies and password stores are not artifacts.

## 11. Provider and model disclosure

Context assembly computes a disclosure manifest: workspace, provider/model, data classes, source item IDs/artifact hashes, redactions, purpose and retention expectation. The model router may only select providers authorized for the highest data class in the packet. Fallback cannot lower privacy/residency. Connector mutation receives only fields required for the operation.

Provider copies and retention are tracked as external residuals in export/delete reports. Onyx must not claim local-only processing when a cloud model or provider receives content.

## 12. Retention, correction, supersession and deletion

- Retention is per workspace and memory layer. Episodic/debug data is shorter-lived than approved decisions/facts.
- Correction creates a new record linked by `supersedes`; the prior record becomes superseded but remains auditable according to policy.
- Contradictions are preserved and surfaced. Newer is not automatically truer.
- Time-sensitive facts have `valid_until` or a refresh requirement.
- Source deletion/permission loss makes dependent memory unavailable or stale according to policy; it does not fabricate a replacement source.
- Forget/delete uses a job that inventories relational rows, FTS/vector/graph indexes, artifacts, WAL/backups and supported provider copies; each store returns a receipt.
- Secure deletion limitations of SQLite, filesystem snapshots, backups and providers are disclosed. Logical deletion plus verified key destruction may be the enforceable method for encrypted artifacts.

## 13. Export

Export is workspace-scoped, owner-approved and data-class aware. It contains schema/policy versions, records, provenance, supersession/contradiction links, artifact manifest and residual/omission report. Restricted vault material is never exported. Confidential/restricted export is always explicitly approved and written to a verified destination outside protected databases/sidecars using atomic publication.

Cross-workspace exports are separate packages unless the owner explicitly approves a named combined sanitized report.

## 14. Migration and rollback

1. Characterize current memory schema v1, legacy JSON import, FTS fallback, privacy, retention, export and forget behavior.
2. **M1a:** create only the inert sidecar schema, empty tables/indexes and migration journal. Create no workspace/domain row or `legacy-default`, do not read/backfill context, and do not change `onyx_memory.sqlite3`; prove deterministic schema, read-back and flags-off rollback.
3. Stop for review. Starting implementation or creating M1a is not activation; activation means enabling the workspace-aware feature flag and satisfying the Phase 4 exit gate.
4. **M1b:** only after M1a review acceptance, create `WorkspaceRegistry` and the `legacy-default` compatibility row through the explicit `LegacyWorkspaceAdapter`, then backfill verified mission/memory context references transactionally and idempotently. Verify every referenced ID and content hash; ambiguous assignments remain pending review rather than being guessed or generically defaulted.
5. Run dual-read comparison: the legacy API remains identical through its explicit versioned legacy adapter/trusted marker; enhanced adapters require an explicit workspace and fail closed when it is missing.
6. Assign every new record to an explicit workspace. A reviewer may explicitly assign an ambiguous legacy record to `legacy-default`, but runtime lookup never does so implicitly.
7. Enable hard-filter retrieval per workspace behind a feature flag only after Phase 4 exit evidence is accepted.

Rollback disables the adapter and returns to the existing `MemoryStore`; it never writes secrets to JSON, deletes legacy data or merges workspace databases. Sidecar data remains available for audit/export.

## 15. Tests and acceptance criteria

- Legacy memory records, citations, IDs and exports survive migration; existing APIs remain compatible.
- Missing/unknown workspace denies enhanced retrieval; no fallback to all records.
- Pairwise tests across every workspace class produce zero unauthorized memory, artifact, credential alias, browser profile or mission references.
- Filters run before ranking; an extremely similar record in another workspace is never returned.
- Candidate/rejected/superseded/stale/contradicted records cannot masquerade as current approved fact.
- Secret canaries in every input field never reach memory, FTS/vector index, artifact metadata, mission event, audit, log, prompt or export.
- Prompt-injection corpus remains quoted/framed as data and cannot invoke policy/tools.
- Delete/export inventories all stores and reports unresolved provider/backup residuals truthfully.
- Workspace switch invalidates cached retrieval context and grants.
- Sidecar outage/corruption denies enhanced access and leaves current databases usable.
- Current `tests/test_memory_store.py`, credential, mission, dashboard and path suites remain green.

## 16. Non-negotiable invariants

1. Restricted secrets are vault data, never memory.
2. Workspace is an authorization boundary, not a search filter convenience.
3. Evidence/provenance travels with a memory item.
4. Candidate knowledge is not operational truth.
5. Supersession preserves history; deletion follows explicit policy.
6. Export/delete claims enumerate residuals and limitations.
7. Cloud disclosure is labeled honestly.
