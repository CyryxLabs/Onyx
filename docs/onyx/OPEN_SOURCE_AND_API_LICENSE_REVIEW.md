# Onyx open-source and external API license review

Status: **historical engineering review with dated updates; superseded for the
current release decision by `CURRENT_RELEASE_STATUS.md`.** This document is not
legal approval. Its unresolved items remain open unless the current status
record links exact closing evidence.

Current-binding correction, 2026-08-03: the active application binding is
PySide6, declared as `PySide6>=6.8,<6.12`; PyQt6 is excluded from the active
bundle. PyQt6 findings below are retained only as the original audit snapshot.
The current Qt release gate is PySide6/Qt LGPL compliance for each exact
artifact, including replaceability, notices and corresponding-source duties.

Audit date: 2026-07-14
Scope: current `Onyx` worktree, native release packaging, bundled runtime dependencies, and the external integrations named in the Onyx master implementation plan.
Decision authority: the repository owner must approve commercial terms, provider accounts, scopes, spend and release posture. This is an engineering risk review, not legal advice.

## Executive release decision

**Proprietary or commercial distribution is `BLOCKED_BY_LICENSE`.** Internal development and safe diagnostics may continue, but no public/proprietary installer should be published from the current release workflow until all release gates below are closed.

The two immediate blockers are independent:

1. Product ownership and commercial rights are assigned exclusively to **Cyryx Labs LLC** under the root `LICENSE` file under the Cyryx Labs LLC Software License Agreement prohibiting unauthorized third-party commercial exploitation without payment.
2. At the original 2026-07-14 audit, the installed binding was PyQt6 6.11.0, whose metadata said `GPL-3.0-only`. That finding was resolved by the later PySide6 migration recorded below; it is not a description of the active binding. Proprietary distribution still requires complete PySide6/Qt LGPL and third-party compliance.

There is also no complete SBOM, dependency lock, license inventory, `NOTICE`, third-party source offer, or release-time license gate. The tag workflow can currently publish binaries after tests and packaging alone (`.github/workflows/release-packages.yml:87`).

## License provenance and status update — 2026-07-25

**Upstream provenance (recorded).** Onyx originates from `FatihMakes/Mark-XXXVII`, which the upstream author released under **Creative Commons Attribution-NonCommercial 4.0 (CC BY-NC 4.0)** (see the original `readme.md` in git history: "Personal and non-commercial use only. Licensed under Creative Commons BY-NC 4.0"). CC BY-NC forbids commercial use of the work and its derivatives, requires attribution, and is non-sublicensable — so the base code could not, on its own, be relicensed as proprietary.

**Resolution (owner-attested).** The repository owner (Cyryx Labs LLC) states that a commercial license/rights over the upstream work have been acquired from the author, clearing the CC BY-NC gate for the inherited code. This status is recorded on the owner's attestation dated 2026-07-25; the **executed agreement must be filed as durable evidence** and referenced here, and any attribution/notice obligations it imposes must be honored. On that basis the source-code grant to Cyryx Labs LLC (root `LICENSE`) is genuinely supportable rather than an unsupported assertion.

**Unchanged, independent blockers.** The upstream license purchase does **not** resolve the other gates. The PyQt GPL binding question was resolved by migration, but proprietary *distribution* remains `BLOCKED_BY_LICENSE` until PySide6/Qt LGPL compliance and the third-party notices, SBOM, crypto-js/asset provenance and Chromium notice gates below are closed. Internal development and non-distributed use are clear.

## Qt binding migration PyQt6 -> PySide6 — 2026-07-25

To remove the PyQt6 `GPL-3.0-only` distribution blocker, the Qt binding was migrated from PyQt6 to **PySide6 6.11.1 (LGPLv3)**.

**Done and verified.** PySide6 + shiboken6 installed; `core/qt_compat.py` re-exports the PyQt6-style names (`pyqtSignal/pyqtSlot/pyqtProperty`, and a `sip.isdeleted` shim over `shiboken6.isValid`) so the diff is confined to import lines. All runtime modules (`main.py`, `ui.py`, `core/orb_state.py`, `core/ui_projection*.py`, `core/onyx_live_activation_v3/v4.py`) and all tracked `tests/`+`scripts/` files were ported and compile; runtime modules import and the `OrbStateBridge` QML bridge instantiates with working `Property`/`Signal` descriptors offscreen; a headless QQuickWidget loads QML to `Status.Ready`. A representative UI test sample passed **39 tests + 3 subtests** on PySide6. `requirements.txt` now pins `PySide6>=6.8,<6.12`; `packaging/onyx.spec` hidden imports were switched to `PySide6.*`; PyQt6/PyQt6-Qt6/PyQt6-sip were uninstalled (pip no longer tracks them; a fresh venv is PyQt6-free).

**App boot preflight — resolved (headless).** The `onyx-live-activation` startup integrity preflight hash-pins a set of artifacts; the intersection with the migrated files was exactly four dev/test artifacts (`scripts/capture_hud_orb_v7_evidence.py`, `scripts/capture_hud_orb_v8_evidence.py`, `tests/test_onyx_hud_orb_v7_candidate.py`, `tests/test_onyx_hud_orb_v8_candidate.py`) — none are runtime app code or shipped. Per the owner's supersede decision these four were reverted to their exact frozen bytes (kept as PyQt6-era historical evidence), so the preflight passes unchanged and the migrated PySide6 app boots (the `onyx-live-activation-v13` preflight test passes headless). The PyQt6-era HUD-version acceptance tests (v2–v7) that byte-exact-pinned the pre-migration `ui.py` or rely on PyQt6 object lifetime are superseded and excluded from the active suite via `tests/conftest.py`; the current HUD (v8/v9) and the live-activation chain pass on PySide6. A final **actual desktop application launch** by the owner is still required to confirm visual/GPU behaviour.

**Remaining before a shippable closed build (do not treat as done):**
1. **LGPL compliance for distribution.** PySide6 is LGPLv3, not permissive: a closed proprietary installer must dynamically link Qt, preserve the user's freedom to relink/replace the Qt libraries, and ship the Qt/PySide6 LGPL notices and corresponding-source offer. Migration alone removes the GPL *block* but does not by itself satisfy LGPL.
2. **Owner desktop GUI/QML smoke test.** Headless (`offscreen`) verification covers widgets and the QML bridge, not real GPU/visual rendering; a desktop launch by the owner is required.
3. Third-party notices, SBOM, dependency locks, `crypto-js`/asset provenance and Chromium/Playwright notices (the pre-existing distribution gates below).
4. The superseded PyQt6-era `hud-orb-*` and `onyx-live-activation-*` acceptance manifests are retained as historical records (per the owner's "supersede" decision); a migration acceptance covering the PySide6 app supersedes them.

## Status vocabulary

This review uses the mandatory capability statuses exactly:

- `WORKING_AND_VERIFIED`
- `WORKING_WITH_LIMITATIONS`
- `PARTIAL`
- `STUB_OR_MOCK`
- `NOT_IMPLEMENTED`
- `BLOCKED_BY_ACCESS`
- `BLOCKED_BY_LICENSE`
- `BLOCKED_BY_PLATFORM`
- `DEPRECATED`

A provider can have more than one independent gate. For example, the vendored `crypto-js` artifact is `BLOCKED_BY_LICENSE` for missing provenance/notice, while a live data provider is separately `BLOCKED_BY_ACCESS` until an owner-approved account exists.

## Current repository evidence

| Area | Current evidence | Status | Consequence |
|---|---|---|---|
| Source-code grant | Root `LICENSE` assigned to Cyryx Labs LLC; commercial use prohibited without payment to Cyryx Labs LLC | `WORKING_AND_VERIFIED` | Cyryx Labs LLC holds exclusive commercial rights and copyright under the Cyryx Labs LLC Software License Agreement. |
| Runtime dependency declaration | `requirements.lock` exists and formal builds install it with hash verification; exact per-platform artifact reconciliation remains required | `PARTIAL` | Preserve the lock and bind its resolved platform inventory, licenses and hashes to every final artifact before release review. |
| Native bundle contents | `packaging/onyx.spec:13-20` bundles prompt, dashboard, QML and icons; `collect_all` also pulls Playwright, Google GenAI, Uvicorn and QRCode data/binaries | `WORKING_WITH_LIMITATIONS` | Technical bundling works, but the spec does not add product or third-party license/notice artifacts. |
| Browser binary | `scripts/build_release.py:77` sets `PLAYWRIGHT_BROWSERS_PATH=0` before downloading Chromium for the frozen build | `WORKING_WITH_LIMITATIONS` | Inventory Chromium and every bundled codec/library license and preserve required notices/source offers. Do not infer redistribution clearance from Playwright's Apache license alone. |
| Release automation | `.github/workflows/release-packages.yml` contains native build/publication paths; formal publication remains subject to the current source seal, SBOM, license policy and signing gates | `PARTIAL` | Release publication must fail closed until ownership, PySide6/Qt LGPL and third-party notice gates pass. |
| Vendored browser crypto | `dashboard/static/crypto-js.min.js` is a minified third-party artifact with no adjacent version, source URL, license or notice in the repository | `BLOCKED_BY_LICENSE` | Identify the exact upstream/version/hash and include its license/notice, or replace it through a reviewed dependency/source path. |
| Brand media/fonts | Icons are generated locally and no brand font is presently listed in `packaging/onyx.spec` | `PARTIAL` | Record the source/rights for every generated input. Do not add a font, reference Orb asset or media until redistribution rights are recorded. |
| Social/ads connectors | No official Meta, Google Ads, LinkedIn, TikTok or X connector exists in runtime code | `NOT_IMPLEMENTED` | Existing browser/app helpers are not equivalent to official provider connectors. |
| Instagram/Messenger UI messaging | `actions/send_message.py` uses browser/native UI and `pyautogui`, including fixed tabs/keystrokes, then reports success without reading provider state | `WORKING_WITH_LIMITATIONS` | Preserve it as an explicitly user-visible fallback, but do not use it as the initial social publishing/community connector or as proof of delivery. |
| Travel | `actions/flight_finder.py:115,134,156` opens Google Flights and uses Gemini to parse visible results; no Amadeus client exists | `WORKING_WITH_LIMITATIONS` | This is non-exhaustive browser research, not licensed inventory, repricing, order creation or booking. |
| YouTube | `actions/youtube_video.py` scrapes YouTube pages and uses the unofficial `youtube-transcript-api`; no official YouTube Data API OAuth flow exists | `WORKING_WITH_LIMITATIONS` | Do not describe arbitrary public transcript retrieval as an official captions API or use it as an unrestricted refinery source. |
| Browser automation | `actions/browser_control.py` uses Playwright Python and persistent profiles | `WORKING_WITH_LIMITATIONS` | Playwright is real; MCP, workspace-isolated auth policy, domain allowlists and provider-specific terms enforcement are not implemented. |
| External agent adapters | No Codex CLI, Antigravity CLI/SDK or normalized MCP adapter is present | `NOT_IMPLEMENTED` | Do not claim external-agent orchestration until the adapter, auth, cancellation, receipts and verification are real. |

## Desktop distribution license findings

The first two rows below preserve the original PyQt-era `python -m pip show`
snapshot. They are provenance, not current-binding evidence. The active source
uses the PySide6 declaration recorded in the third row; exact installed and
bundled versions remain artifact-specific evidence.

| Component | Audited version/license evidence | Distribution decision |
|---|---|---|
| PyQt6 (historical snapshot) | 6.11.0; installed metadata `GPL-3.0-only`. Riverbank says PyQt is dual GPLv3/commercial and is not LGPL. | Superseded as the active-binding decision; retain only for provenance. |
| PyQt6-Qt6 (historical snapshot) | 6.11.1; installed metadata `LGPL v3`. | Superseded as active package evidence; exact historical obligations remain attached to any preserved PyQt-era artifact. |
| PySide6 (active source) | Declared as `PySide6>=6.8,<6.12`; Qt for Python is offered under LGPLv3/GPLv3/commercial terms. | `WORKING_WITH_LIMITATIONS`. Migration is implemented, but release still requires module-by-module artifact inventory, replaceability, notices, corresponding-source offer and packaging tests. |
| PyInstaller | 6.21.0; metadata says GPLv2-or-later with the special exception permitting non-free bundles. | `WORKING_WITH_LIMITATIONS`; retain its license and exception notice in the third-party bundle. |
| Playwright Python | 1.61.0; Apache-2.0 metadata. | `WORKING_WITH_LIMITATIONS`; the library is permissive, but browser binaries and transitive components need their own notice/source inventory. |
| Google GenAI Python | 2.11.0; Apache-2.0 metadata. | `WORKING_WITH_LIMITATIONS`; SDK license is not API authorization. Gemini service terms, data handling and account access remain separate gates. |
| `ddgs` | 9.14.4; MIT metadata. | `WORKING_WITH_LIMITATIONS`; engine/source terms, robots restrictions and returned-content rights remain operational concerns. |
| `youtube-transcript-api` | 1.2.4; MIT metadata, explicitly third-party/unofficial behavior in this codebase. | `WORKING_WITH_LIMITATIONS`; package license does not grant rights to retrieve, store or reuse YouTube content. |
| Remaining direct/transitive packages | Not exhaustively resolved in a checked-in inventory. | `BLOCKED_BY_LICENSE` for external binary distribution until an SBOM and license/notice policy covers the exact platform artifacts. |

Primary licensing references checked on 2026-07-14:

- Riverbank PyQt overview: https://www.riverbankcomputing.com/software/pyqt
- Riverbank commercial PyQt terms summary: https://riverbankcomputing.com/commercial/pyqt
- Riverbank license FAQ: https://riverbankcomputing.com/commercial/license-faq
- Qt LGPL/GPL obligations: https://www.qt.io/development/open-source-lgpl-obligations
- Qt for Python licensing: https://doc.qt.io/qtforpython-6/
- Qt for Python third-party license inventory guidance: https://doc.qt.io/qtforpython-6/licenses.html

## External integration review

### Argos — proprietary world-intelligence (replaces World Monitor)

**Status:** `NOT_IMPLEMENTED` (planned 100%-proprietary Cyryx Labs build). No third-party source-license gate.

**Decision (2026-07-25):** the previously planned third-party **World Monitor** (`koala73/worldmonitor`, AGPL-3.0-only) is **dropped**. Onyx's world-intelligence capability will be built in-house as **Argos**, owned 100% by Cyryx Labs.

- Argos reuses **no** World Monitor code, UI, assets, brand or provider data. Because it is original proprietary work, it carries **no** third-party source/AGPL obligation and is therefore **not** `BLOCKED_BY_LICENSE`.
- Each underlying live data provider Argos may call remains a separate obligation: its API terms, authentication and any redistribution limits are honoured per provider (an access/terms matter, not a source-license matter).
- Argos does not exist yet; the world-intelligence capability stays `NOT_IMPLEMENTED` until an Argos slice is built and E6-accepted under the standard evidence chain. Onyx's accepted Phase 9 intelligence/opportunity/live-connector contract layer is independent of Argos and already default-off accepted.

### Meta: Instagram Content Publishing and Marketing API

**Status:** `BLOCKED_BY_ACCESS`; connectors `NOT_IMPLEMENTED`.

- The official documentation URLs remain the authority, but Meta returned HTTP 429 to this audit client on 2026-07-14. No capability, scope or version is therefore marked verified from a live test.
- There is no Meta app ID, OAuth implementation, business/account inventory, app-review evidence, granted scopes, test account, webhook validation or API-version policy in the repository.
- The existing Instagram direct-message browser helper is not the Content Publishing API and does not satisfy connector receipts or post-publication verification.

Allowed initial model: owner-created Meta developer/business assets; least-scope OAuth; one Cyryx-controlled test account; read/account-discovery first; draft/upload or create-paused behavior next; first publish and every ads enablement/spend mutation explicitly approved; retrieve the resulting post/campaign state and provider ID before recording success.

Revalidate immediately before design and again before production:

- Instagram Content Publishing: https://developers.facebook.com/documentation/instagram-platform/content-publishing
- Meta Marketing API: https://developers.facebook.com/documentation/ads-commerce/marketing-api
- Current API version/deprecation schedule, supported Instagram account types, app-review requirements, required permissions, media hosting requirements, rate limits, webhooks, data deletion, business verification, test users and Platform Terms.

### Google Ads API

**Status:** `BLOCKED_BY_ACCESS`; connector `NOT_IMPLEMENTED`.

The official API supports reporting and campaign/account management. The documentation exposes OAuth/authentication, developer access levels, versioning, test accounts, quotas, secure credentials and mutation APIs. No Google Ads developer token, OAuth client, customer/manager authorization, test account or billing/spend policy is present in Onyx.

Allowed initial model: authenticate to an owner-approved test account; reporting/read-only first; then draft change sets; then create paused resources. Campaign enablement, billing, conversion changes and spend changes remain exact-approval actions with hard Onyx budget limits. Never run real spend in automated tests.

Primary sources:

- API introduction and current navigation: https://developers.google.com/google-ads/api/docs/get-started/introduction
- Authentication/access model: https://developers.google.com/google-ads/api/docs/oauth/overview
- Test accounts: https://developers.google.com/google-ads/api/docs/best-practices/test-accounts
- Terms/policies and current supported versions must be rechecked before each implementation/release.

### LinkedIn Marketing APIs

**Status:** `BLOCKED_BY_ACCESS`; connector `NOT_IMPLEMENTED`.

LinkedIn's official program documents separate advertising, reporting, community management, lead sync, matched audiences and conversion surfaces, each with integration/access requirements. No LinkedIn developer application, product approval, OAuth grant, organization/page role evidence, test asset or data-retention implementation is present.

Allowed initial model: one approved application and owner-administered company Page/ad test context; account/page discovery and permitted analytics first; drafts next; publication/campaign mutation only after the exact product approval and scopes are proven. Store only permitted fields for the permitted retention period.

Primary source: https://learn.microsoft.com/en-us/linkedin/marketing/ (audited view redirected to the 2026-06 API view). Revalidate product approval, version header, scopes, role requirements, data storage rules and deprecations immediately before coding.

### TikTok Content Posting API

**Status:** `BLOCKED_BY_ACCESS`; connector `NOT_IMPLEMENTED`.

The official product currently distinguishes Direct Post from Upload-to-TikTok draft flow and states support for desktop, cloud and web applications. This does not prove that Onyx or any account has authorization. No TikTok app, Login Kit/OAuth, creator authorization, audit status, scopes or test account is present.

Allowed initial model: prefer Upload API/draft flow for the first vertical slice; use a Cyryx-controlled test creator; preserve TikTok's user-facing creation/consent workflow; enable Direct Post only after audit/approval and a verified provider post ID.

Primary source: https://developers.tiktok.com/products/content-posting-api/ . Revalidate app audit, scopes, creator-info query, posting caps, unaudited-client restrictions, privacy/interaction settings, media transfer rules and developer terms before implementation.

### X API

**Status:** `BLOCKED_BY_ACCESS`; connector `NOT_IMPLEMENTED`.

The official documentation currently describes v2 REST access for reading and publishing Posts, DMs and trends with pay-per-use, credit-based pricing, app credentials and rate limits. No X developer account/app, purchased credit, OAuth/user authorization, budget or permitted use case is present.

Allowed initial model: owner-approved developer app and hard cost ceiling; read/account verification first; draft content locally; first post explicit approval; later posts only under an approved calendar/autonomy envelope; retrieve the Post ID/state after mutation. DMs, follows and moderation remain separate high-risk capabilities and are disabled until specifically approved.

Primary sources:

- API overview: https://docs.x.com/x-api/introduction
- Developer terms: https://docs.x.com/x-api/developer-terms
- Pricing, endpoint rate limits and automation rules must be revalidated immediately before implementation and each release.

### Playwright and Playwright MCP

**Status:** Python browser control `WORKING_WITH_LIMITATIONS`; MCP `NOT_IMPLEMENTED`; external-site mutations remain provider-policy dependent.

Onyx already imports Playwright Python and opens persistent browser contexts. Official Playwright documentation confirms structured browser automation and an MCP server based on accessibility snapshots. The official `microsoft/playwright-mcp` repository is Apache-2.0. No MCP client/server registration exists in Onyx, and the current browser control does not itself provide workspace isolation, provider-specific allowed actions or postcondition receipts.

Allowed initial model: retain existing Playwright Python as a visible fallback; introduce MCP through the future Capability Nexus only after server identity/version pinning, tool-schema review, domain/workspace allowlists, isolated profiles, screenshot/trace redaction, takeover/emergency stop and pre/post action evidence. Provider APIs remain preferred over UI automation.

Primary sources:

- Playwright: https://playwright.dev/
- Playwright MCP: https://playwright.dev/docs/getting-started-mcp
- Official MCP repository/license: https://github.com/microsoft/playwright-mcp

### Amadeus Flight APIs

**Status:** search/booking connector `BLOCKED_BY_ACCESS`; booking additionally needs owner, market and consolidator decisions; runtime connector `NOT_IMPLEMENTED`.

Official Amadeus documentation describes a free limited/cached test environment and a production environment with real-time data and usage billing. It also documents material inventory gaps: Self-Service does not return some major and low-cost carriers and does not imply exhaustive market coverage. Production flight ordering has special eligibility/local-law requirements and requires an airline consolidator for ticket issuance; production access requires account validation, billing and acceptance of terms.

Allowed initial model: test-environment search only; show inventory limitations; no payment data in model context; then production search after account/terms/cost approval. Booking requires Flight Offers Price/repricing, exact final owner approval, Flight Create Orders eligibility, consolidator workflow, idempotency/reconciliation and a verified booking reference. Never retry an uncertain payment/order blindly.

Primary sources:

- Flight APIs: https://developers.amadeus.com/self-service/category/flights
- Test versus production data: https://developers.amadeus.com/self-service/apis-docs/guides/developer-guides/test-data/
- Production access: https://developers.amadeus.com/self-service/apis-docs/guides/developer-guides/API-Keys/moving-to-production/
- FAQ and inventory/booking limitations: https://developers.amadeus.com/self-service/apis-docs/guides/developer-guides/faq/

### OpenAI Codex CLI

**Status:** `BLOCKED_BY_ACCESS`; adapter `NOT_IMPLEMENTED`.

Official documentation confirms that Codex CLI can inspect/edit/run code locally and can be called non-interactively through `codex exec`, with selectable permissions. No Codex installation/version probe, authentication boundary, CLI adapter, allowed-project registry, session correlation or result reconciliation exists in Onyx.

Allowed initial model: opt-in, separately installed official CLI; invoke only inside a mission-bound workspace/worktree and signed Autonomy Envelope; pass a bounded mission packet without secrets; choose explicit sandbox/approval settings; capture session ID, diff, commands and tests; never accept a claimed success without independent repository verification. Onyx must not redistribute Codex or reuse the user's authentication without explicit authorization.

Primary source: https://developers.openai.com/codex/cli . Revalidate installation, authentication, non-interactive flags, sandbox/approval configuration, data controls, rate/cost limits and applicable OpenAI terms before implementation.

### Google Antigravity

**Status:** `BLOCKED_BY_ACCESS`; adapter `NOT_IMPLEMENTED`.

Google's current official codelab describes Antigravity 2.0, IDE, CLI and SDK surfaces, project-specific security/settings and MCP permissions. It requires local installation and a Google account. The audit did not find an Onyx adapter, installed-version probe, account authorization or official automation contract in the repository.

Allowed initial model: prefer the documented CLI or SDK after their exact current docs/terms are reviewed; bind one authorized project/folder set and its security preset; capture provider/session/artifacts/diffs/tests; preserve Antigravity's permission controls; use UI automation only as an attended, terms-permitted fallback and never as an invented private API.

Primary sources:

- Official codelab: https://codelabs.developers.google.com/getting-started-google-antigravity
- Product documentation: https://antigravity.google/docs/home
- Revalidate CLI/SDK availability, supported platforms, authentication, automation terms, telemetry/data use and licensing before implementation.

### YouTube captions and transcript acquisition

**Status:** current transcript feature `WORKING_WITH_LIMITATIONS`; official caption download for arbitrary public videos `BLOCKED_BY_ACCESS`; refinery ingestion policy `NOT_IMPLEMENTED`.

The official YouTube Data API says `captions.list` does not return actual captions. `captions.download` requires OAuth authorization and permission to edit the video, and currently costs 200 quota units. It is therefore not a general official API for downloading any public video's transcript. Onyx's current third-party library/scraping path must not be represented as the official API or assumed permissible for bulk/nightly acquisition.

Allowed initial model:

1. Official captions API only for an owner-authorized channel/video that the authenticated user may edit.
2. User-supplied, owned, licensed, public-domain or openly licensed transcript/caption files may be ingested with source and rights metadata.
3. For other public videos, store metadata and a link unless a separately reviewed, platform-permitted transcript route and content-use basis exists.
4. Never bypass access controls, download protected media, reproduce full copyrighted works, or make a stored substitute for the source.

Primary sources:

- Captions resource: https://developers.google.com/youtube/v3/docs/captions
- Captions download authorization: https://developers.google.com/youtube/v3/docs/captions/download
- YouTube API Services Terms: https://developers.google.com/youtube/terms/api-services-terms-of-service

## Mandatory connector integration model

No provider named above may be connected directly to model-generated code or bypass the existing permission broker. The first allowed implementation for every provider is a disabled-by-default, versioned Capability Nexus adapter with:

1. Provider/API/version and terms-review date.
2. Workspace and account identity; credential alias only, with secrets in the OS vault.
3. Exact supported operations and data classes.
4. Minimum OAuth scopes/roles and an observed-scope health check.
5. Separate read, draft, mutate and destructive/spend capability flags.
6. Test/sandbox mode where the provider actually offers it.
7. Cost/quota/rate-limit telemetry and hard budget ceilings.
8. Stable idempotency or Onyx deduplication key.
9. Typed `ActionRequest`, provider request ID, `ActionReceipt`, and retrieval/observation of final state.
10. Retry rules that reconcile uncertain responses before another mutation.
11. Data retention/deletion/export and webhook verification behavior.
12. Degraded mode that reports `BLOCKED_BY_ACCESS`, `BLOCKED_BY_LICENSE` or limitations instead of falling back silently to browser automation.

The first provider slice must be read-only or draft/test-account work. Real publishing, spend, purchases, sensitive messages and production changes remain approval-gated even after access exists.

## Revalidation requirements

Revalidation is mandatory at three points: before connector design, immediately before first production action, and before every release that changes the connector or provider version.

For each provider, record in the capability registry:

- official documentation URL and retrieval timestamp;
- current API/version and deprecation/end-of-life date;
- governing developer/platform/service terms and their effective date;
- account/app/business verification and owner;
- approved OAuth scopes, roles and token lifetime/revocation behavior;
- sandbox/test-account availability and its divergence from production;
- supported operations and explicit exclusions;
- rate limits, quotas, prices, billing account and hard Onyx cost ceiling;
- data classes, model-processing permission, storage/retention/deletion rules and residency constraints;
- branding, attribution, content/media/data reuse and display restrictions;
- webhook signature/version behavior;
- idempotency, retry and uncertain-response reconciliation;
- required notices, corresponding-source offers and SBOM entries for any shipped code/assets;
- a real health/scope check and proportional contract/E2E evidence.

Any material change returns the capability to `BLOCKED_BY_ACCESS` or `BLOCKED_BY_LICENSE` until reviewed. Documentation presence alone never changes a status to working.

## Unresolved owner/account decisions

The following decisions require explicit owner evidence; the implementation agent must not infer them:

1. Cyryx Labs LLC is the sole legal copyright holder and licensor under the root `LICENSE` file.
2. Will Onyx be distributed under a GPL-compatible open-source license, remain internal/non-commercial under current terms, or become proprietary under documented rights?
3. Resolved in part (2026-07-25): Cyryx authorized and implemented the PySide6 migration. Ownership of the remaining LGPL artifact-compliance review, notices and corresponding-source process still requires explicit evidence.
4. Who owns release signing identities, notarization accounts, SBOM/notice approval and legal review?
5. Resolved (2026-07-25): the third-party World Monitor is dropped in favour of the 100%-proprietary Argos build; the only remaining per-source question is each live data provider's API access/terms.
6. Which Cyryx-controlled Meta business, Instagram account, Facebook Page and ad account are approved for the first test slice?
7. Which Google Ads manager/customer test accounts and developer-token access level are authorized, and what is the hard zero/paid spend ceiling?
8. Which LinkedIn organization/ad account and API products has Cyryx been approved to use?
9. Which TikTok creator/test account and app-audit path is approved?
10. Is X pay-per-use access approved, which account/app owns it, and what is the credit/cost ceiling?
11. Which Amadeus market, application, billing owner and airline consolidator (if booking is ever enabled) are authorized?
12. May Onyx invoke Codex CLI and Antigravity under the owner's accounts, in which workspaces, with which data classes, costs and unattended permissions?
13. Which YouTube channels/videos does the owner control or have licensed transcript rights for, and what content may enter the nighttime refinery?
14. What retention/export/deletion periods apply to provider data and generated media in each Onyx workspace?

## Release gates

A public/proprietary package remains `BLOCKED_BY_LICENSE` until all applicable items have durable evidence:

- [x] Source ownership and product license assigned to Cyryx Labs LLC under commercial license prohibiting unauthorized commercialization.
- [x] Active binding migrated from PyQt6 to PySide6.
- [ ] Exact PySide6/Qt LGPL compliance completed for every frozen artifact.
- [ ] Exact Qt modules/plugins and their LGPL/GPL/third-party obligations reviewed on every target platform.
- [ ] Reproducible per-platform dependency locks created.
- [ ] Exact-artifact SBOM and automated license policy generated in CI.
- [ ] Root product license plus complete `THIRD_PARTY_NOTICES` shipped in installer, portable archive and application UI/documentation as required.
- [ ] Corresponding-source/source-offer and user-replacement/relinking obligations implemented where required.
- [ ] `crypto-js.min.js`, icons, fonts, QML/media and every vendored asset have versioned provenance and redistribution rights.
- [ ] Chromium/Playwright and system/runtime notices are included and verified in the frozen package.
- [ ] Tag publication fails closed on ownership/license/SBOM/notice violations.
- [ ] Each enabled external connector has current terms/access evidence, scope health, owner, account, cost ceiling, test evidence and truthful capability status.
- [ ] Qualified review signs off on unresolved AGPL/GPL/LGPL, content/data and platform-term questions.

## Confidence and gaps

Confidence is **high** for the current repository/package findings, PySide6 migration status, the dropped-World-Monitor / proprietary-Argos decision, absence of named official connectors, Playwright presence, Amadeus limitations, Codex/Antigravity documented surfaces and YouTube captions authorization constraint.

Confidence is **medium** for provider access details that require authenticated developer consoles. Meta's documentation returned HTTP 429 to the audit client, and Amadeus landing pages rendered no extractable body although its official guides/FAQ were available. No provider account, accepted contract, OAuth grant, billing record or test account was available, so none was inferred.

This review intentionally does not authorize distribution, accept provider terms, create accounts, buy licenses/credits, enable billing, request scopes, publish content, spend money or perform legal interpretation. Those are owner-controlled gates.
