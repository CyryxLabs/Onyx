# Phase 10 provider connector V1 checkpoint

Third Phase 10 (social organic OS) slice: a default-off, route-pinned, read-only
provider connector contract. It adds one module, one feature flag and no runtime
wiring, and opens no real network in evidence.

`core/phase10_provider_connector_v1.py` (`ONYX_PHASE10_PROVIDER_CONNECTOR_V1`) is
entry-bound to the accepted Phase 10 editorial-calendar four-file acceptance
tuple. Over an injected transport it reads one approved provider's account status
(`ApprovedProviderV1` → `ProviderAccountStatusV1`: handle, verified, follower
count, recent post ids) via a redirect-disabled HTTPS GET whose scheme, host,
port, userinfo, path, query, fragment and timeout must match the registry exactly
(the Phase 9 userinfo-escape hardening is reused). Provider id, platform and
scopes are attributed from the trusted registry, and a response whose handle does
not match the registry-declared `expected_handle` is denied (anti-spoof). There
is no publish method.

The cumulative selection reproduces 570 passing tests and 80 passing subtests
across twenty-six fresh Python processes — the twenty-five inherited Phase 7
stable-core, Phase 8 connector, Phase 9 intelligence and Phase 10 social test
files plus this slice's thirty-two adversarial tests — with eight inherited,
explained platform-specific skips and zero failure/error.

Scope and limits: a read-only, route-pinned status read only. No publishing, no
audience research, no community action. The real provider fetch is owner-gated
(OAuth/app-review + test account) and stays `BLOCKED_BY_ACCESS`; the contract is
verified with an injected transport. The slice claims no startup/voice/UI/
dashboard wiring, no later Phase 10 items and no full Onyx PRD completion.
