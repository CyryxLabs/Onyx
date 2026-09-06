# Capability delta — Phase 8 Microsoft Graph Live Read E2E V1

## Added behind one exact default-off flag

- Secret-free Microsoft Entra public-client onboarding from the environment,
  failing closed on any credential-shaped variable.
- Throttle-aware transport wrapper honoring `429 Retry-After` exactly, with
  deterministic bounded backoff when the header is absent and a typed error at
  the retry bound; non-429 responses are never retried.
- Redacted transport observations (route, path, status, sanitized OAuth error
  code, retry delay, attempt) — never tokens, payloads or query strings.
- Six-probe live E2E harness composing the frozen OAuth V1 and Read V1
  contracts: sign-in/read, access expiry refresh, refresh rotation,
  revocation classification, provider failure without retry, rate-limit
  Retry-After honoring.
- Probe-mode sealing: `live` can only be declared over the real stdlib HTTPS
  transport by exact type.
- Typed redacted report with explicit `probes_missing` and strict
  `live_verified` semantics.
- Operator evidence runner writing redacted JSON reports under `runtime/`.

## Not added

- Entra app registration, production client ID, tenant consent or test
  account; live execution remains `BLOCKED_BY_ACCESS`.
- Live identity or Microsoft Graph E2E evidence (requires the onboarding
  runbook to be completed by the owner).
- Provider-side draft or any calendar/mail mutation.
- Tasks, notifications, Drive/OneDrive/Office routes.
- Startup, V13, voice, dashboard or UI wiring.
- Phase 8 aggregate exit or full PRD completion.
