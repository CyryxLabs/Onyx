# ADR-0052 — Phase 10 content draft and provenance V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

Phase 10 item 3 of the Onyx PRD is the content pipeline: research packet, claim
validation, channel copy, original/authorized asset provenance, accessibility and
a brand/policy review before preview/approval. The first three Phase 10 slices
established the account inventory, the approval-gated editorial calendar and the
read-only provider connector. This ADR records the fourth slice: the content-draft
and provenance contract, still with no publishing authority.

## Decision

Add `core/phase10_content_draft_v1.py`, a default-off
(`ONYX_PHASE10_CONTENT_DRAFT_V1`), deterministic, hermetic contract entry-bound to
the accepted provider-connector four-file acceptance tuple. It enforces,
structurally:

1. **Asset provenance.** `AssetProvenanceV1` declares `kind` and `source`
   (`original`/`licensed`/`authorized`); `licensed`/`authorized` require a
   `rights_ref`. No asset without a declared right.
2. **Claim validation (anti-fabrication).** A `validated` `ContentClaimV1` must
   cite an `evidence_ref`, and an `approved` draft must have every claim
   validated — fabricated stats/testimonials cannot pass.
3. **Accessibility.** Every visual asset (image/video) must carry `alt_text`.
4. **Brand/policy review gate.** A draft reaches `approved` only with an explicit
   positive `PolicyReviewRecordV1`.
5. **No publishing.** The status lifecycle is `draft -> in_review -> approved`;
   `published` is not representable and there is no publish/schedule method.
   `is_ready_for_calendar` is a readiness predicate only.

The module calls no model, opens no network, spawns no process, persists nothing
and takes no action.

## Consequences

- Onyx can hold provenance-checked, claim-validated, accessible, policy-reviewed
  content drafts ready to hand to the separately accepted editorial calendar —
  the content half of the PRD pipeline, without any ability to publish here.
- The slice claims no publishing, no live provider action, no analytics; it
  enables no autonomous social behaviour.
- Any regression in the provenance/claim/accessibility/policy gates, the
  entry-bind or the cumulative gate fails the slice verifier.

## Alternatives considered

- Letting an `approved` draft carry unvalidated claims flagged "opinion":
  rejected for V1 — the simplest honest gate is that approval requires every
  claim validated; a nuanced opinion/claim taxonomy is a later successor.
- Storing a `published` status disabled by a flag: rejected — publishing must be
  structurally unrepresentable here; it returns as a separately accepted,
  owner-gated slice.
- Importing the editorial calendar to auto-schedule an approved draft: rejected —
  this slice only marks readiness; scheduling remains the calendar's job and
  publishing a later gated slice.
