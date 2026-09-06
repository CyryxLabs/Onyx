# Phase 8 Microsoft Graph OAuth V1 — E6 acceptance

- Evidence ID: `VE-P8-MICROSOFT-GRAPH-OAUTH-V1-E6-001`
- Decision date: `2026-07-23`
- Decision: **ACCEPTED — default-off delegated OAuth/read transport contract**
- Candidate manifest: `81dbaba8991478737c7000519281d8c1924a3522aec40b62e3a635bcde3d2b65`
- Artifact root: `9ae6f034f530a6e8353dfccbcf675760d2746684cf1a840da94adab326bf824d`

Findings are `P0=0`, `P1=0`, `P2=0`, and `P3=0`. The gate rehashed eight
candidate artifacts and reproduced **304 passed tests, 80 passed subtests, 0
failed and 0 errors** in fourteen fresh Python processes. Eight skips are the
previously accepted platform-specific Phase 7 checks.

Accepted scope covers the Microsoft identity device authorization contract,
exact delegated read scopes, signed-in account verification, refresh-token
native-vault abstraction and rotation, process-local access-token handling,
one-shot device-session consumption and GET-only composition with the accepted
Microsoft Graph Read V1 adapter. The candidate handles malformed and divergent
scope/account/token responses, vault failure, alias drift/revocation and
refresh failure without destructively deleting the refresh credential.

V1 remains exactly default-off and unwired. It does not provision a Microsoft
Entra application, client ID, tenant consent or test account and does not prove
live identity/Graph E2E. It adds no provider mutation, automatic rate-limit
retry, startup/voice/UI/dashboard wiring, Phase 8 aggregate exit or full Onyx
PRD completion. Immutable Python strings prevent a guaranteed in-place wipe of
process-local bearer-token memory.

