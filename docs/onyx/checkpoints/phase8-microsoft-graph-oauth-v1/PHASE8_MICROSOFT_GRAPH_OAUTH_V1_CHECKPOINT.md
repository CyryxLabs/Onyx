# Phase 8 Microsoft Graph OAuth V1 checkpoint

This exactly default-off candidate adds the delegated OAuth lifecycle required
to use the accepted Microsoft Graph Read V1 contract with an authorized public
native-client registration.

Forty focused tests cover exact gating and settings, frozen predecessor entry,
alias/provider/tenant/scope binding, device challenge hygiene, polling cadence,
terminal-session consumption, missing refresh token, granted-scope drift,
account mismatch, vault failure, refresh rotation/failure, token redaction,
route/header denial, revocation and composition with the accepted daily brief.

The cumulative selection contains 304 passing tests and 80 passing subtests
across fourteen fresh processes, with eight inherited and explained
platform-specific skips and zero failure/error.

Limits: there is no real Entra registration/client ID, tenant consent or test
account in this candidate. No live identity/Graph E2E, provider mutation,
startup/voice/UI/dashboard wiring, Phase 8 aggregate exit or full PRD completion
is claimed.

