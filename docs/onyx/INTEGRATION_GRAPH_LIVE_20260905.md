# Graph live count/status audit — 2026-09-05

## Result

**CURRENT: token-size defect fixed in source and bounded live read passed at 2026-09-05T06:12:30Z.** See the authorized successor implementation and freeze evidence below. The original blocked audit is retained as historical evidence, not current status.

**Original result:** Microsoft accepted the existing refresh credential and returned HTTP 200, but V1 rejected the newly returned refresh token before account verification or mailbox/calendar reads. At that earlier point no counts were available.

Scope: `C:\MAAX_Assistant\Onyx-Remediation-Clean-20260823-151210`, existing owner DayOps profile/native credential. Installed executable still reported **1.1.30** during this audit. This is not 1.1.31 release certification.

User authorized real count/status-only Graph reads, normal OAuth refresh and necessary local store initialization. No new consent, remote email/event creation, send, upload or other remote data write was authorized or performed. This document is separate from the earlier integration-readiness audit, which was not edited.

## Current evidence

First attempt started at **2026-09-05T05:57:15.043504Z**. The authenticated existing profile was passed through `DayOpsProfileV19.public_environment()` to `create_canonical_dayops_graph_factory_v1`. That factory initialized the existing local control-plane store/registry, validated the existing workspace/alias binding and restored through `MicrosoftGraphOAuthSessionV1` and the native refresh-token vault. No test account or new alias was provisioned.

| Attempt | Provider result | Local result | Elapsed |
|---|---|---|---|
| Initial count/status read attempt | OAuth refresh HTTP 200; HTTP call 0.269 s | `GraphOAuthV1Denied` during existing-session restore; no Graph GET | 0.670 s |
| Diagnostic: classify the rejection | OAuth refresh HTTP 200 | Safe allowlisted reason: `provider text contract drift`; bearer type, expiry range and literal required scopes passed | 0.530 s |
| Diagnostic: identify failing field | OAuth refresh HTTP 200 | Returned refresh token exceeds both character and UTF-8 byte limits; other inspected text fields pass | 0.455 s |

Three refresh requests total, each using the already-consented credential. The second and third were targeted diagnostics of the first failure, not an automatic retry loop. Each diagnostic allowed at most one refresh POST; HTTP timeout was bounded to ten seconds. No device authorization/sign-in endpoint or consent flow was invoked. All factories were closed after use.

The diagnostic emitted only booleans and status metadata:

- Profile MAC authenticated successfully.
- Required scope count: 3; granted scope count: 6. Literal granted scopes already cover the required set; URI normalization is not the blocker.
- Token type is bearer; access expiry is inside the existing 60–86,400-second contract.
- Access token, token type and scope text are nonempty, within their respective limits and contain no control characters.
- Returned refresh token is nonempty with no control characters, but exceeds the configured character limit and UTF-8 vault limit.
- No tokens, account identifiers, subjects, message bodies, event details or provider response payloads were printed or written to this report.

## Root cause and effect

`core/phase8_microsoft_graph_oauth_v1.py:45` sets `MAX_REFRESH_TOKEN_BYTES = 1_800`. `_refresh_token` at line 522 first calls `_text(value, MAX_REFRESH_TOKEN_BYTES)`. `_text` at line 499 raises `GraphOAuthV1Denied("provider text contract drift")` when the string exceeds the limit.

During `_accept_token_payload`, the response refresh token is validated **before** `_verify_account(access_token)` and before `self._vault.set_refresh_token(refresh)`. Consequently, this run did not reach account verification, did not persist the rejected replacement token through that path, and did not dispatch a mailbox/calendar GET. Successful OAuth HTTP status alone does not prove usable Onyx Graph access.

The diagnostic left this validation intact. No token truncation, substitution, omission of the returned refresh token, direct bearer workaround, changed limit or new consent was used to bypass it.

At 01:59 EDT, the source OAuth module matched the installed 1.1.30 integrity-source copy: SHA-256 `c6311042dae3d2e19c8e3f2b90278feb3830be40c6ccd45e0a59ac6bfc2ff548`. Execution used the existing development Python/module environment, not the frozen desktop process.

## Planned bounded read, not reached

The initial harness was limited to existing Graph read transport routes and refresh-token POSTs. After successful restore it would have re-attested the adapter binding and performed one page per collection:

- `GET /v1.0/me/messages` with `$select=id`, `$top=1`, `$count=true`.
- `GET /v1.0/me/calendarView` for the following 24 hours, with `$select=id`, `$top=1`, `$count=true`.

Only HTTP status, elapsed time, returned-item count, optional provider total count and `has_more` would have been emitted. No pagination or personal-content printing was planned. These reads were **NOT RUN** because the factory failed first. The factory's normal `/me` identity verification also was **NOT RUN**.

The general live-E2E script was inspected but not executed because it can enter a device-consent flow and builds a separate harness. Existing production factories/transport were reused instead, with an in-memory HTTP observer delegating unchanged payloads to the existing `StdlibGraphOAuthHttpV1`. The observer imposed request/time limits and recorded status only; it did not weaken authentication or endpoint checks.

## Remaining action

Engineering must handle the provider's larger replacement refresh token within the native-vault storage boundary before this Onyx path can complete. Review the native backend capacity and authenticated storage design; do not simply increase the constant without validating the backing vault contract. Add a regression for an oversized replacement token and verify safe rotation/persistence against the actual supported backend. Source changes and release work remain with the parent, outside this audit's authorization.

After the fix is reviewed and deployed, repeat the same bounded count/status read with the existing consent. No new consent is currently indicated by these HTTP 200 refresh responses. If a later refresh returns a consent-required error, report that separate condition rather than initiating consent automatically.

## Implementation log / evidence boundary

IDS: searched existing Graph live/readiness documents and modules. **REUSE** production profile, canonical Graph factory, OAuth HTTP client and native credential resolver. **CREATE** only this specifically requested separate report because it records a new live failure beyond credential presence. No source/release edits, tests or stored fixtures were added. Necessary local store initialization and provider refresh were explicitly authorized; no unrelated work was reverted.

Self-review: distinguished HTTP 200 from completed account validation; distinguished missing counts from zero; confirmed rejection precedes Graph GET and token persistence. This is a diagnosed live blocker, not an integration success or a request for new consent.

## Authorized token-size correction / source freeze

The user subsequently authorized necessary Graph/vault source changes and regressions, preserving historical predecessors and excluding main/UI, release manifests, HUD and Google-chain changes. The earlier no-source-change boundary and remaining-action section above describe the initial audit only.

### Capacity and design, reported before changes

The provider replacement exceeds V1's 1,800-byte contract but fits **2,048 UTF-8 bytes**. The existing cross-platform native primitive already permits 2,048 bytes; its limit was not increased. Windows generic credentials support a 2,560-byte blob, so this fix remains below that platform maximum. [Microsoft CREDENTIALW documentation](https://learn.microsoft.com/pt-br/windows/win32/api/wincred/ns-wincred-credentialw).

An actual Windows Credential Manager synthetic probe passed: write/read 2,048 bytes; replace with a different 2,048-byte value; fresh-process read/hash equality; reject 2,049 bytes while retaining the prior value; remove the uniquely named synthetic credential and verify absence. No test token or secret was printed. This validates this host/backend, not untested macOS/Linux backends.

V2 uses the existing protected native primitive and one record per credential, in the additive `CyryxLabs.Onyx.GraphOAuth.v2` service. It performs one native replacement followed by exact constant-time readback. No file/JSON token, plaintext fallback, chunking, truncation, global limit relaxation or multi-record transaction is used. Native last-writer-wins behavior remains: an uncertain/mismatched readback fails closed without deleting or rolling back another writer. This is not compare-and-swap concurrency protection.

Until a V2 record exists, V2 reads the existing V1 credential without modifying it. Successful rotation writes only V2. A V2 disconnect writes a protected tombstone so the V2 path cannot revive its retained V1 fallback. The historical V1 record remains; this is local V2 disconnect behavior, not provider-wide revocation or old-binary logout certification.

OAuth V2 first runs the unchanged V1 factory's evidence, identity, alias and settings validation. Acceptance preserves bearer type, scope subset, expiry, account verification and alias attestation; the refresh validator alone admits the native-capacity bound. Access activation occurs only after protected persistence/readback. The transport successor admits an exact V2 session to the unchanged GET engine. Canonical factory wiring selects both successors. Final review also aligned the host connection controller's existing provisioning injection to the same V2 vault for status/disconnect; no consent was initiated or tested.

### Live evidence after the fix

At **2026-09-05T06:12:30.452028Z**, the existing public profile MAC validated, and the canonical production factory restored using existing consent. Each allowed route was limited to one request, ten-second HTTP timeout, no automatic retry, no pagination and a 45-second dispatch budget. The observer delegated to the existing stdlib client; it did not substitute bearer tokens or weaken account/scope checks.

| Route | HTTP | Evidence | HTTP elapsed |
|---|---|---|---|
| OAuth refresh | 200 | Replacement accepted and persisted with native readback | 0.246 s |
| `/me` | 200 | Existing account binding verified; identity not printed | 0.389 s |
| `/me/messages` | 200 | `$select=id`, `$top=1`, `$count=true`; 1 returned, provider total 219, more pages available | 0.670 s |
| `/me/calendarView` | 200 | Next 24 hours, same select/top/count bounds; 0 returned, provider total 0, no more pages | 0.227 s |

Connected restore completed in **0.852 s**; complete bounded roundtrip in **1.752 s**. No provider/account blocker remained on these routes. Counts are this point-in-time query only; no identifiers, mail/event contents, tokens or provider response payloads were emitted. Factory closed after use. No remote sends, writes, events, uploads, consent or permission changes occurred.

This exercised updated source modules against the real provider/native vault, not the frozen desktop executable. Installed/release 1.1.31 certification remains with the parent. The later host status/disconnect injection was regression-tested, not exercised against the owner's real disconnect endpoint (which would log them out).

### Tests and review

Final result: **132 passed in 6.53 s**, with `PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, a unique unused system-temp basetemp, and:

```text
python -m pytest --noconftest -p no:cacheprovider -q --tb=short --basetemp <unique-temp> tests/test_graph_refresh_v2.py tests/test_dayops_graph_factory_v1.py tests/test_phase8_microsoft_graph_oauth_v1.py tests/test_phase8_microsoft_graph_live_read_v1.py tests/test_dayops_connection_v19.py tests/test_dayops_persistent_v19.py tests/test_phase8_microsoft_graph_read_v1.py tests/test_dayops_provisioning_v14.py
```

Scoped `python -m ruff check --no-cache` passed for all four touched source modules and the new test module. `npm run lint` and `npm run typecheck` were attempted and unavailable: this isolated Python snapshot has no `package.json` (ENOENT). No claim of npm/typechecker success.

Regressions cover 1,801/2,048 bytes and UTF-8 boundaries, over-capacity/control/surrogate rejection, V1 limit preservation, read-only migration, protected tombstone behavior, write failure, competing/readback failure without rollback, corrupt successor fail-closed, account/scope rejection before persistence, and no bearer activation on rejected/failed rotation. Host status/disconnect dependency selection is checked. Initial new-test run had three assertion failures because `GraphOAuthV1Denied` is not a subclass of `GraphOAuthV1Error`; corrected the expected exception tuple, without changing production validation. Final suite is green.

Self-critique before testing focused on native byte capacity and persistence-before-activation. Final review identified and fixed the direct host vault-injection mismatch before freezing. No claim of new-consent onboarding, voice/device certification, cross-platform native validation or frozen executable parity is added.

### IDS implementation log / exact source hashes for parent build

Searched existing vault/OAuth/DayOps modules, tests, and source/hash references first. **REUSE** the unchanged native primitive, V1 construction/evidence validation and GET engine. **CREATE** the two narrowly scoped successors and synthetic regression file. **ADAPT** only canonical Graph wiring and the host provisioning-vault injection, plus this authorized report. No predecessor manifests or Google closure files were edited by this agent. Parent owns packaging, closure rebinding, security review and release evidence.

| Created/adapted file | Frozen SHA-256 |
|---|---|
| `core/graph_refresh_vault_v2.py` (new) | `fc1843166f06ad3cf9678effdad26b1eec060fb3bfb2c96492f00ba50e880e1b` |
| `core/phase8_microsoft_graph_oauth_v2.py` (new) | `f45429a0279198f5f67c7388ab3828e892f38ab70455daae87f43208a956583f` |
| `core/dayops_graph_factory_v1.py` (composition) | `48426b8b062e321408fab4afefb54952ae949d248d88627c7fe128481ec81b5f` |
| `core/dayops_connection_v19.py` (vault injection) | `a6fc03b455e3a6616e3cdae6a1522cc689c013e669f8643dfc6dbc3e6ac08630` |
| `tests/test_graph_refresh_v2.py` (new) | `7f2b0ab14f1e7df4172bd53b88adb5b97079b46c80617297e00e00df7b510bf9` |

Pre-change composition hashes: factory V1 `7cbeb2a69d1250f2520b40f583110144b797dd5e243328636690131a82caa782`; host connection V19 `b01f5e342026321632fa63fa34adba88b767f86794b78c606e3ee30ba95daddd`. The latter was read and its source/hash references searched before its injection change.

| Unchanged predecessor/dependency | Verified SHA-256 |
|---|---|
| `core/native_vault.py` (also pinned by Google activation) | `526be0df7c9e4ef5a2d63391a0f3f8293f2f257a8e39f6e468cd8801a60cd5d5` |
| `core/phase8_microsoft_graph_oauth_v1.py` | `c6311042dae3d2e19c8e3f2b90278feb3830be40c6ccd45e0a59ac6bfc2ff548` |
| `core/phase8_microsoft_graph_live_read_v1.py` | `c0893398a8fe1f5709773bee28666e59896f13f4b3b3684dc06c4d73a17fecfb` |
| `core/dayops_graph_factory_v19.py` | `a08243578dc441e44124f870ff278f3c00983835c8c7b2bf787aece2afd631a3` |

Source freeze declared after final tests. Remaining action is parent build/security/closure validation and packaged-app parity testing; no new user consent is indicated or requested. This agent stops the token-size defect branch here and will not edit further source during that freeze.
