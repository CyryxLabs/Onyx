# Phase 8 Microsoft Graph Live Read V1 — Official Sources

Verified against Microsoft Learn on 2026-07-23.

## Throttling

- [Microsoft Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling)
  defines `429 Too Many Requests`, recommends waiting for the provider's
  `Retry-After` value, and recommends exponential backoff when that header is
  absent.
- [Microsoft Graph service-specific throttling limits](https://learn.microsoft.com/en-us/graph/throttling-limits)
  notes that limits vary by service and that some resources can return `429`
  without a `Retry-After` header.

Live Read V1 therefore honors a valid seconds-based provider delay. When the
delay is missing it uses bounded exponential backoff. If the provider's delay
is larger than the configured local wait budget, Onyx does not retry sooner
than requested.

## Provider errors and authorization

- [Microsoft Graph error responses](https://learn.microsoft.com/en-us/graph/errors)
  defines the standard HTTP error envelope and distinguishes `401`, `403`,
  `429` and provider-side failures.
- [Resolve Microsoft Graph authorization errors](https://learn.microsoft.com/en-us/graph/resolve-auth-errors)
  documents common `401` and `403` causes and the need for a valid access token
  and sufficient delegated permissions.

Live Read V1 forces one refresh after `401`, never retries `403`, and keeps the
terminal class and provider request ID without copying the provider payload
into operational telemetry.

## Refresh and revocation

- [Refresh tokens in the Microsoft identity platform](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)
  requires secure storage, describes rotation and states that applications
  must be prepared to restart interactive authorization after expiration or
  revocation.
- [Microsoft Entra authentication and authorization error codes](https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes)
  documents expired and revoked grant conditions.

The accepted OAuth predecessor owns secure refresh-token storage and account
verification. This successor asks that session to refresh once and reports
renewed authorization as required if the attempt fails.

## Current limitation

The behavior is verified with deterministic provider doubles and the real
accepted adapter/session composition. A real Microsoft Entra application
registration, authorized test account and live endpoint run are still required
for E6.
