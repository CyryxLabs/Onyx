# Phase 8 Microsoft Graph Read V1 — E6 acceptance

- Evidence ID: `VE-P8-MICROSOFT-GRAPH-READ-V1-E6-001`
- Decision date: `2026-07-23`
- Decision: **ACCEPTED — default-off first-provider read/draft contract**
- Candidate manifest: `91a97a56729e396b84da60d30db5d33d71c8e315343d544792e7183d436dc261`
- Artifact root: `abb152e611e1b58adc55b88207497d64188ad9485d2b6a32ada5f8c364528291`

Findings are `P0=0`, `P1=0`, `P2=0`, and `P3=0`. The gate rehashed eight
artifacts and reproduced **264 passed tests, 80 passed subtests, 0 failed and
0 errors** in thirteen fresh Python processes. Eight skips are the previously
accepted Phase 7 platform-specific checks.

Accepted scope covers Microsoft Graph global v1.0 calendar-view read, normalized
daily briefing, bounded mail metadata search, message read with body-scope
enforcement, local event/email drafts, exact workspace/principal/account alias
binding, scope checks, credential rotation/revocation and same-origin/same-route
provider paging. Message bodies remain untrusted content.

V1 remains exactly default-off and unwired. Its transport has GET authority
only; it adds no OAuth onboarding, live HTTP implementation, provider-side
draft, event creation/invitation/cancellation, shared-calendar mutation or mail
send/update/delete authority. Tasks, notifications, Drive/OneDrive/Office,
Phase 8 aggregate exit and the full Onyx PRD remain pending.
