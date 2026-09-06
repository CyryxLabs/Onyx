# Phase 10 Brand Passport V1 — sources and design basis

This first Phase 10 slice is a hermetic, deterministic inventory contract. It
uses no external service, so the "sources" here are the governing PRD text and
the platform-policy principles the always-on guards encode — not network APIs.

## PRD basis

- `plans/onyx-advanced-entity-redesign.md` Phase 10 item 1: workspace/account
  inventory and separate brand passports for Cyryx Labs, MAAX Studio, Lyra and
  other authorized brands, after OAuth/app-review approval for a first provider.
- Phase 10 guards: never buy followers, run bots/follow-unfollow/spam, use fake
  personas, scrape private data, evade policy, copy competitors or fabricate
  testimonials/stats/logos; first publish per account is explicitly approved.

## Design decisions

- **Inventory only, zero authority.** The slice records who the authorized
  brands and accounts are and enforces their separation. It never publishes,
  never opens a network, and `SocialAccountV1.can_publish` is structurally
  always `False`. Real publishing is a later owner-approved, access-gated slice
  (OAuth/app-review + test account), which is `BLOCKED_BY_ACCESS` until then.
- **Guards as invariants, not toggles.** Every passport must carry the full set
  of always-on guards (`no_follower_buying`, `no_bots_or_automation_abuse`,
  `no_fake_personas`, `no_competitor_copying`,
  `no_fabricated_testimonials_stats_logos`). A passport missing any guard, or
  carrying an unknown one, is rejected — the policy cannot be silently dropped.
- **Strict brand separation.** A `(platform, handle)` pair belongs to exactly
  one brand. This prevents the inventory from being used to impersonate or leak
  one brand's identity into another, which is the core integrity property a
  multi-brand operator needs.
- **Entry-bound to the accepted Phase 9 exit.** Construction is denied unless the
  four-file Phase 9 exit acceptance tuple is byte-exact on disk, so this slice
  cannot be built on top of drifted predecessor evidence.

## Platform-policy principles (encoded as guard names)

The guard names mirror the universally published platform-integrity rules of the
major networks (authentic engagement only; no purchased followers, automation
abuse, impersonation, or fabricated claims). No platform code, asset, or private
document is copied; the guards are Onyx's own restatement of public policy.
