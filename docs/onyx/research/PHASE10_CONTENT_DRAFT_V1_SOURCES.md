# Phase 10 Content Draft V1 — sources and design basis

Hermetic, deterministic content-draft contract. No external service is used; the
basis is the governing PRD content-pipeline requirements and the platform-policy
principles the gates encode.

## PRD basis

- `plans/onyx-advanced-entity-redesign.md` Phase 10 item 3: content pipeline with
  research packet, claim validation, channel copy, original/authorized asset
  provenance, accessibility, and brand/policy review before preview/approval.
- Phase 10 guards: never fabricate testimonials/stats/logos, never copy
  competitors, and the first publish per account is explicitly approved.

## Design decisions (each PRD guard encoded as an invariant)

- **Asset provenance.** Every asset declares `kind` and `source`
  (`original`/`licensed`/`authorized`); `licensed`/`authorized` assets must carry
  a `rights_ref`. Onyx never uses an asset without a declared right — the
  no-unlicensed-assets rule.
- **Claim validation (anti-fabrication).** A claim marked `validated` must cite an
  `evidence_ref`, and a draft can only reach `approved` when every claim is
  validated — so fabricated stats/testimonials cannot pass review.
- **Accessibility.** Every visual asset (image/video) must carry `alt_text`.
- **Brand/policy review gate.** `approved` requires an explicit positive
  policy-review record, mirroring the PRD's brand/policy review + approval step.
- **No publishing.** The status lifecycle stops at `approved`; `published` is not
  representable and there is no publish/schedule method. `is_ready_for_calendar`
  is a readiness predicate handing an approved draft to the separately accepted
  editorial calendar; scheduling and publishing are later gated slices.
- **Entry-bound to the accepted provider-connector slice.** Construction is denied
  unless the four-file Phase 10 provider-connector acceptance tuple is byte-exact.

## Platform-policy principles

The gates restate the universally published platform-integrity rules
(authentic/original content, disclosed sponsorship, accessible media, no
fabricated claims). No platform code, asset, or private document is copied.
