# ADR-0039 — Phase 8 Microsoft device bootstrap V2 (frozen-V1 defect corrective)

- Status: implemented, live-exercised 2026-07-23/24
- Depends on: accepted Phase 8 OAuth V1 and Live Read E2E V1

## Defect record (frozen predecessor)

The first live execution of the accepted stack was structurally denied inside
frozen `core/phase8_microsoft_graph_oauth_v1.py`: its device-verification host
allowlist (`microsoft.com`, `www.microsoft.com`, `login.microsoftonline.com`)
predates the provider's current behavior. Live observation on 2026-07-23
(tenant `f90d5d7e-…c60e`) returned
`verification_uri = https://login.microsoft.com/device`, a legitimate
Microsoft identity host absent from the frozen allowlist, so
`begin_device_authorization` raised `device verification URI is invalid` on
every live sign-in. Frozen predecessors are never edited; per the constitution
the defect is recorded here and corrected in a versioned successor.

## Decision

Add `core/phase8_microsoft_graph_device_bootstrap_v2.py` behind exact
default-off `ONYX_PHASE8_MS_GRAPH_DEVICE_BOOTSTRAP_V2`. Scope is deliberately
minimal: it performs only the initial device-code sign-in with the corrected
host allowlist (adds `login.microsoft.com`), validates granted scopes and the
signed-in account (`GET /me`) exactly like the frozen contract, and persists
the refresh token into the exact native-vault slot the accepted runner already
restores from — `build_runner_credential_record` rebuilds the deterministic
vault identity (`credential_vault_locator_v1`) for the accepted runner's
workspace/alias, so no control-plane store, secret file or repository
credential is created. Every subsequent OAuth, transport, read and probe
behavior remains the accepted frozen implementation reached through
`restore()`.

Reused public frozen contracts only: onboarding identity, settings/scope
validator, route-pinned stdlib HTTPS client, refresh-token vault binding.

## Consequences

- Live device sign-in works again without touching any frozen byte; the
  accepted live-E2E runner produced its first genuine live report
  (`report_sha256 66281adc…773f`).
- A future OAuth V2 (or the next Phase 8 mutation successor) must fold the
  corrected allowlist into the main lifecycle and retire this bootstrap.
- Eight focused tests cover the corrected allowlist (accept `login.microsoft.com`,
  deny evil/HTTP/suffix/fragment hosts), vault-fingerprint parity with the
  frozen binding, poll cadence, declined/expired/window-expiry, scope-drift and
  account-mismatch denial before any vault write, and source hygiene.

## Rollback

Leave `ONYX_PHASE8_MS_GRAPH_DEVICE_BOOTSTRAP_V2` unset; the factory returns
`None`. Deleting the bootstrap module/script/tests restores the previous tree;
the stored vault refresh token can be removed with the accepted harness
`disconnect()`.
