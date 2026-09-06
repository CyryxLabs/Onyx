# ADR-0049 — Phase 10 brand passport and social account inventory V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

Phase 10 of the Onyx PRD is the social organic operating system. Its first
requirement is an authorized-account inventory with separate brand passports for
Cyryx Labs, MAAX Studio, Lyra and any other authorized brand, established after
OAuth/app-review approval for a first provider. Publishing, audience research,
content pipelines and community replies are later items, each gated. This ADR
records the first slice: the inventory contract itself, with no publishing
authority and no network.

## Decision

Add `core/phase10_brand_passport_v1.py`, a default-off
(`ONYX_PHASE10_BRAND_PASSPORT_V1`), deterministic, hermetic registry over brand
passports and their social accounts. It is entry-bound to the accepted Phase 9
exit four-file acceptance tuple, so it cannot be constructed on drifted
predecessor evidence.

The contract enforces, structurally:

1. **Always-on policy guards.** Every `BrandPassportV1` must carry the full set
   `{no_follower_buying, no_bots_or_automation_abuse, no_fake_personas,
   no_competitor_copying, no_fabricated_testimonials_stats_logos}`; a passport
   missing any guard, or carrying an unknown one, is rejected. The PRD's Phase 10
   prohibitions are encoded as invariants, not runtime toggles.
2. **Strict brand separation.** Each `SocialAccountV1` belongs to exactly one
   brand, references an existing passport, and uses a platform inside that
   brand's allow-list. A `(platform, handle)` pair can be claimed by only one
   brand, so the registry can never be used to impersonate or leak one brand's
   identity into another.
3. **No publish authority.** `SocialAccountV1.can_publish` is structurally always
   `False`. `is_usable` reflects only that a brand and account are both
   authorized for *future* gated work; it never grants publishing. The first real
   publish per account is a later owner-approved, access-gated slice
   (`BLOCKED_BY_ACCESS` until OAuth/app-review plus a test account exist).

The module calls no model, opens no network, spawns no process, persists nothing
and takes no action.

## Consequences

- Onyx gains an auditable, tamper-evident inventory of authorized brands and
  accounts with enforced separation — the foundation later Phase 10 slices
  (provider connectors, research, content pipeline, publishing, community) build
  on, each still individually gated and accepted.
- The slice claims no live provider connection, no publishing, no audience data
  and no community action; it enables no autonomous social behaviour.
- Any regression in the module invariants, the accepted Phase 9 exit entry-bind,
  or the cumulative gate fails the slice verifier.

## Alternatives considered

- Storing publish capability as a passport flag defaulting off: rejected —
  publishing must be structurally absent at this layer, not a flag one edit away
  from being enabled. It returns as an explicit, separately accepted gated slice.
- Allowing a shared `(platform, handle)` across brands for "cross-posting":
  rejected — it defeats the separation property and invites impersonation; any
  legitimate cross-brand posting is modelled later as distinct authorized
  accounts, never a shared identity.
