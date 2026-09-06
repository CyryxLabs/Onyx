# ADR-0033 — Phase 7 Layered Memory V1

- Status: candidate
- Date: 2026-07-23
- Depends on: accepted Workspace Memory V1

## Context

The PRD requires memory to extend through adapters into seven separate layers:
session working, episodic mission, semantic institutional, decision,
procedural, preference and temporal status. It also requires entity
resolution, deduplication, contradiction and supersession handling, freshness,
correction, retention, export, deletion, source deletion, poisoning defenses
and zero cross-workspace leakage.

The accepted Workspace Memory V1 adapter securely retrieves approved legacy
semantic and episodic records. It is intentionally read-only and does not
provide the seven-layer lifecycle contract. Its accepted implementation scans
the shared `memory_metadata` table, so a successor must coexist without
changing or confusing that frozen parser.

## Decision

Add an exactly default-off `LayeredMemoryCatalogV1` sealed to one active
workspace, principal, control-plane connection and HMAC key. Store records in
the existing `memory_metadata` table under a content-addressed `lmem_`
namespace. Keep the table schema version at 1 and never use the predecessor's
`active` row status, allowing Workspace Memory V1 to ignore successor rows
without modification.

Each record has exactly one of seven typed layers plus:

- stable entity kind/key and normalized content hashes;
- source IDs, sensitivity, confidence, validity, freshness and retention;
- candidate/approved/rejected/superseded/corrected/deleted lifecycle;
- explicit correction, supersession and contradiction links;
- immutable content identity with signed lifecycle transitions;
- `untrusted_data` content and permanently false instruction authority;
- prompt-injection signal classification and secret-pattern rejection.

Entity resolution requires a new live value for an existing layer/entity to
declare a correction, supersession or contradiction. Corrections and
supersessions transition the prior row atomically while preserving its signed
record. Retrieval applies workspace, principal, lifecycle, source,
sensitivity, validity and freshness filters before lexical ranking.

Deletion and retention replace content, source IDs, tags and entity labels
with a signed tombstone. Source deletion tombstones every affected record in
the bound principal scope. Deterministic export omits HMAC and key
fingerprints and cannot include another principal or workspace.

## Consequences

- All seven memory layers now have a typed governed persistence contract.
- The accepted Workspace Memory V1 adapter remains byte-for-byte unchanged and
  continues to retrieve its own `active` sidecars.
- There is no global vector index and no cross-workspace post-filtering.
- Memory can inform reasoning only as untrusted evidence; procedural or
  preference records do not become runtime instructions.
- The candidate adds no network, process, provider, model, browser, action,
  UI, dashboard or live-runtime seam.
- General semantic/NLP entity extraction is not claimed; V1 receives explicit
  typed entity keys and relations from governed intake.

## Rollback

Leave `ONYX_PHASE7_LAYERED_MEMORY_V1` unset. The factory returns before entry
verification or host binding. Existing Workspace Memory, Company Graph,
Founder Command, V13, UI and voice behavior remain unchanged.
