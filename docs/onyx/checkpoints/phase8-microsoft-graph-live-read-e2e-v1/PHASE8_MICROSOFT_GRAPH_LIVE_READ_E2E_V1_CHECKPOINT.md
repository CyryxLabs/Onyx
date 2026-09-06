# Phase 8 Microsoft Graph Live Read E2E V1 checkpoint

This exactly default-off candidate adds the live read-only E2E evidence layer
over the accepted, unmodified OAuth V1 and Graph Read V1 contracts: secret-free
Entra public-client onboarding from the environment, a throttle-aware transport
wrapper that honors `429 Retry-After`, and a six-probe harness with a redacted
typed report (sign-in/read, access expiry refresh, refresh rotation,
revocation, provider failure, rate-limit Retry-After).

Thirty-three focused tests cover exact gating, onboarding identifier
validation, secret-material rejection, accepted-predecessor entry binding,
onboarding/alias identity mismatch, throttle construction, exact Retry-After
honoring including the RFC-valid zero-delay immediate retry, deterministic
bounded backoff, retry-bound exhaustion, Retry-After contract drift, non-429
no-retry, observation contract drift, the full six-probe choreography with
token redaction, live-mode transport sealing, probe preconditions,
terminal-denial revocation classification that rejects a provider-failure
terminal, report subset honesty and duplicate denial, generated-at validation,
disconnect delegation and source-invariant scanning. The report hash binds
every serialized field, including `read_only`.

The cumulative selection contains 337 passing tests and 80 passing subtests
across fifteen fresh processes, with eight inherited and explained
platform-specific skips and zero failure/error.

Limits: no Entra registration/client ID, tenant consent or test account exists
yet, so live execution remains `BLOCKED_BY_ACCESS`; the exact owner steps are
in `docs/onyx/PHASE8_MICROSOFT_GRAPH_LIVE_ONBOARDING.md`. Provider failure and
real throttling cannot be forced against the live service; their behavior is
contract-proven and live reports list them under `probes_missing`. No provider
mutation, startup/voice/UI/dashboard wiring, Phase 8 aggregate exit or full
PRD completion is claimed.
