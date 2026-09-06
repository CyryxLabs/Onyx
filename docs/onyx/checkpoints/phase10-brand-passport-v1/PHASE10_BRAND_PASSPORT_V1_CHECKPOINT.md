# Phase 10 brand passport V1 checkpoint

First Phase 10 (social organic OS) slice: a default-off, deterministic, hermetic
brand + social-account inventory contract. It adds one module, one feature flag
and no runtime wiring.

`core/phase10_brand_passport_v1.py` (`ONYX_PHASE10_BRAND_PASSPORT_V1`) is
entry-bound to the accepted Phase 9 exit four-file acceptance tuple. It records
`BrandPassportV1` records (brand id, legal name, authorization, allowed
platforms, disclosure requirement and the always-on policy guards) and
`SocialAccountV1` records (account id, brand, platform, handle, brand/test type,
authorization and scopes), and builds a `BrandRegistryV1` that enforces unique
ids, account→existing passport, platform∈brand allow-list, strict
`(platform, handle)`→one-brand separation, and authorized-brand/account
usability. `can_publish` is structurally always `False`; the module calls no
model, opens no network, spawns no process, persists nothing and takes no action.

The cumulative selection reproduces 504 passing tests and 80 passing subtests
across twenty-four fresh Python processes — the twenty-three inherited Phase 7
stable-core, Phase 8 connector and Phase 9 intelligence test files plus this
slice's thirty-two adversarial tests — with eight inherited, explained
platform-specific skips and zero failure/error.

Scope and limits: inventory only. No live provider connection, publishing,
audience data or community action is part of this slice. The first real publish
per account is a later owner-approved, access-gated slice (`BLOCKED_BY_ACCESS`
until OAuth/app-review plus a test account). The slice claims no startup/voice/
UI/dashboard wiring, no later Phase 10 items and no full Onyx PRD completion.
