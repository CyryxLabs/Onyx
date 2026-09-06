# Onyx reference-repository clean-room gap matrix

Date: 2026-08-03  
Reference snapshot: `petruff/jarvis_MAAX` commit
`564c97b2cf8ad29983b3ad40411441dbc9e22af3`  
Method: behavior-level comparison only; no source, assets, product names, UI,
notices or license text are copied into Onyx.

Status: current behavior-level comparison and remaining-gap record. It does
not supersede `CURRENT_RELEASE_STATUS.md` and is not a release approval.

## Independent correction — 2026-08-05

An independent repository-to-runtime review found that earlier wording in this
document sometimes treated an architectural analogue, a default-off source
candidate, or an installed projection as if it were complete end-user parity.
That interpretation is rejected.  The following correction is authoritative
for every older row in this document:

- Concrete background text clients are not complete.  Onyx has Gemini Native
  Audio for the live voice path plus Ollama/OpenAI-compatible text seams and a
  route planner; it does not yet have live, receipted Anthropic, Groq and
  OpenRouter clients.  No alternate provider may replace or silently fall back
  from Gemini Native Audio/Charon.
- The device-mesh foundation is not a distributed sidecar.  Enrollment,
  identities, request envelopes and outbound transport contracts exist, but a
  network receiver/listener and a deployable remote agent remain missing.
- The governed workflow graph is not a visual workflow product.  It lacks the
  deep editor, execution monitor, history and broad safe-node catalog visible
  in the reference.
- Site project metadata and deterministic recipes are not a complete site
  builder.  A governed editor, file tree, supervised preview and receipted
  Git/GitHub operations remain missing.
- The HUD operations projection is not parity with the reference's deep Goals,
  Workflows, Sites, Pipeline, Office, Awareness and Knowledge views.
- Research/verifier Cells are not a broad persistent role roster with agent
  inbox, delegation views and team-style lifecycle.
- Pairing, official Discord messaging, site recipes, portable accessibility
  and content lifecycle were source-only/default-off after V21 and were not in
  the V24 live activation chain at the time of this review.  Source existence
  and packaging inclusion are not live evidence.

Current truth must therefore be expressed using four separate states:

1. implemented and live in the selected activation;
2. implemented in source but not activated or installed;
3. implemented but awaiting a real device, credential, account or native host;
4. deliberately rejected because the reference behavior violates Onyx CPU,
   privacy, security, authority or license boundaries.

The reference snapshot itself is not fully green on this Windows host: its
current test run reports 417 passed, 5 failed and 2 dependency-load errors.
Reference UI labels and README claims are never accepted as operational proof.

### Remaining clean-room implementation backlog

| Priority | Missing useful behavior | Required Onyx implementation boundary |
|---|---|---|
| P0/P1 | Deployable remote sidecar receiver/RPC | Authenticated listener, replay-safe durable dispatch, capability-scoped remote agent, reconciliation and physical-device proof |
| P1 | Concrete background text providers | Anthropic plus explicit OpenAI/Groq/OpenRouter routes behind OS-vault aliases, budgets, privacy routing and receipts; voice path unchanged |
| P1 optional | Google Gmail/Calendar | Official OAuth scopes, OS-vault token storage, account binding, pagination, revoke and provider-state receipts |
| P1 | Deep workflow product | Cinematic Cyryx editor/monitor/history over the single governed workflow and Phase 6 executor; no arbitrary code/shell node |
| P1 | Governed site workspace | Controlled editor/file tree, supervised preview and exact repository/branch Git operations with rollback and receipts |
| P1 | Official channels | Finish live Discord wiring and add Telegram Bot API; WhatsApp and Signal remain excluded because the reference implementations are stubs |
| P1 | Goal/agent operations UX | Estimation, natural-language decomposition, configurable accountability, persistent role roster, inbox and delegation views |
| P1 | Portable host adapters | Native macOS/Linux accessibility backends and host-specific tests; source contracts alone are insufficient |
| P2 | Event-only operational analytics | Timeline, trends and reports derived from accepted metadata events, with zero continuous screen/clipboard/process polling |

Until each row has proportional runtime, denial, rollback and installed-host
evidence, the correct status is `PARTIAL` or `SOURCE_CANDIDATE`, never complete.

### Source-candidate progress — 2026-08-05

The following clean-room increments have now passed independent source-level
acceptance.  This is **not** launcher, package, installed-runtime or external
service acceptance:

| Increment | Current state | Independent evidence |
|---|---|---|
| V25 capability-extension composition | `SOURCE_CANDIDATE` | 37 V25/V24 tests; central broker/governance binding, session rotation and pairing-code isolation accepted |
| Network background text providers | `SOURCE_CANDIDATE` | 104 provider/registry/local-text tests; Anthropic, OpenAI, Groq and OpenRouter routes accepted with durable replay, registry `READY` policy and pre-dispatch drift checks |
| Device Mesh receiver | `SOURCE_CANDIDATE` | 85 integrated plus 13 selected adversarial tests; HMAC ledger, bounded receiver and lifetime-growth acceptance passed |
| Telegram official connector | `SOURCE_CANDIDATE` | 39 Telegram/messaging tests; one-call outbox, leases, reconciliation and v1-to-v2 migration accepted |
| Goal/Agent Operations | `SOURCE_CANDIDATE` | 27 goal/agent and operational-goal tests; exact Phase 6 evidence, scoped roster/inbox/delegation, quotas and authenticated policy accepted |
| Event-only operational analytics | `SOURCE_CANDIDATE` | 48 analytics/bridge/goals/workflow tests; immutable attestations, authenticated heads, pagination and 1,000-event bounded-growth acceptance passed |

These candidates still require an explicit successor activation, production
account/key resolvers, release-closure inclusion, SBOM reconciliation, a clean
build and exact-installed acceptance.  The Device Mesh additionally requires a
real TLS mount, external ledger key and physical second-device proof.  Network
providers, Telegram and Google require owner credentials/account consent and
real-provider receipts.  None may silently replace Gemini Native Audio/Charon.

## Current clean-room implementation status

The following original Onyx implementations now exist and pass their focused
contracts. V20 transactionally composes them around the exact live Phase 6
session with zero polling, and V21 exposes bounded local goal/status operations
to Gemini Live through one additive tool. The Windows 1.1.9 V19/V21 candidate
is built, exact-installed and real voice/provider-rotation accepted. This does not transfer to
macOS/Linux and does not close signing, legal, SBOM, live Graph, clean-host or
long-session gates.

| Candidate | Source | Focused result |
|---|---|---|
| Operational goals and commitments | `core/operational_goals_v1.py` | 7 passed |
| Read-only operational daily rhythm | `core/operational_rhythm_v1.py` | 13 focused; installed V19 HUD accepted |
| Governed event automation | `core/governed_automation_v1.py` | 7 passed |
| Low-CPU event awareness | `core/event_awareness_v1.py` | 6 passed |
| Authenticated device mesh foundation | `core/device_mesh_v1.py` | 8 passed |
| Certificate-pinned mesh HTTPS transport | `core/device_mesh_https_v1.py` | 10 passed |
| Owner-controlled personality suggestions | `core/personality_preferences_v1.py` | 7 passed |
| Evidence-backed site project lifecycle | `core/site_projects_v1.py` | 6 passed |
| Webhook/time/workspace event adapters | `core/automation_adapters_v1.py` | 5 passed |
| Qt-native workspace event publisher | `core/native_workspace_events_v1.py`; V20/V21 binding | 4 module plus 3 binding regressions passed |

The integrated V20/V21, Phase 6, Advanced Operations, voice lifecycle and
native QML-close selection passed 252 tests; the V12-to-V21 activation chain
passed 136 tests and the 78-file source-acceptance manifest passed two tests. The V19
Windows package passed its release pipeline, canonical install, exact
7,288-file inventory and all nine installed gates. Normal installed V21
startup opened Gemini microphone/receive/playback, survived repeated real
provider rotations with exactly one microphone/playback lifetime and produced
zero Application Errors at the acceptance boundary. Exact
evidence is in
`operations/ONYX_1_1_9_V19_WINDOWS_ACCEPTANCE_2026-08-04.md`.
The installed candidate additionally provides an original, owner-invoked HUD pill
for bounded goal, attention, automation and awareness projection. It performs
no polling or external dispatch. It includes non-sensitive rule/device/site/
preference counts, governed rule authoring over exact approved Phase 6
missions, owner-authorized preference promotion, local device enrollment and
controlled-root site lifecycle commands. These surfaces are rebuilt and passed
bounded installed acceptance. V19 also includes the original read-only
morning/midday/evening rhythm. Its installed eight-hour attempt 1 is in progress
with an atomic incremental receipt; `IN_PROGRESS` is not acceptance. The
remaining external, physical and richer-UX gates are listed below.

## Decision boundary

The reference repository is governed by the Jarvis Source Available License
2.0. Its terms do not permit stripping notices and freely redistributing its
implementation as a Cyryx Labs product. Onyx therefore uses a clean-room
boundary: inspect observable capabilities, document the useful behavior, then
implement an original version through Onyx's existing authority, mission,
audit, credential, voice and UI contracts.

The reference snapshot is not a release baseline. Its dependency-only install
completed when lifecycle scripts were suppressed, but its full test run
reported 417 passes, five test failures and two dependency-load errors. It also
contains a CLI source defect (`existsSync` is called without being imported).

## Capability matrix

Status meanings:

- `PRESENT`: Onyx already has the capability.
- `STRONGER_IN_ONYX`: Onyx has a materially stronger governed implementation.
- `PARTIAL`: a useful slice exists, but the end-user behavior is incomplete.
- `MISSING`: no equivalent operational surface was found.
- `SOURCE_CANDIDATE`: an original default-off implementation now has source
  contracts, but live activation, packaging and installed acceptance remain.
- `LIVE_SOURCE_CANDIDATE`: source activation and routing are proven, but the
  frozen and installed application has not yet passed acceptance.
- `WINDOWS_INSTALLED_CANDIDATE`: the module is composed in the exact installed
  Windows V21 runtime and passed bounded installed acceptance; missing UX,
  physical, external-service, long-session and other-platform gates remain.
- `STUB_ONLY`: the reference advertises the feature but its implementation is
  incomplete; it is not a capability to copy.
- `REJECT_SECURITY`: the behavior violates Onyx authority, privacy or evidence
  rules and must not be reproduced as designed.
- `REJECT_LICENSE`: names, source, assets or UI that cannot cross the clean-room
  boundary.

| Capability observed in reference | Onyx status | Decision |
|---|---|---|
| Primary real-time conversational model and natural voice | `STRONGER_IN_ONYX` | Preserve Gemini Live `gemini-2.5-flash-native-audio-preview-12-2025` and Charon. Do not introduce Edge TTS, ElevenLabs, Whisper or system-voice fallback. |
| Persistent owner identity and name changes | `STRONGER_IN_ONYX` | Preserve Owner Profile V8 journal/anchor and the live voice/UI update path. Reference profile storage is not authoritative enough. |
| Model/provider registry and routing | `PRESENT` | Keep the existing provider adapters and privacy-hard routing. Reference multi-provider text adapters may inform compatibility tests only. |
| Persistent missions, leases, recovery and kill | `STRONGER_IN_ONYX` | Keep the single MissionStore/MissionWorker. Never create a second executor. |
| DAG planning, budgets, retries and postconditions | `STRONGER_IN_ONYX` | Phase 6 already provides typed DAG plans, host-owned policy labels, exact mission materialization and independent verification. |
| Multi-agent roles and delegation | `PRESENT` | Extend only as Operator Cells over the single mission engine. Do not allow agent-local registries to bypass host authority. |
| OKR hierarchy, scores, deadlines and daily rhythm | `WINDOWS_INSTALLED_CANDIDATE` | Installed V19 binds hierarchy/lifecycle commands to exact Phase 6 and adds deterministic morning, midday and evening focus/action/warning projections to the existing HUD with zero mutation, polling, workers or dispatch. Live calendar/reminder projection remains an external Graph gate. |
| Commitments/tasks and due-date tracking | `WINDOWS_INSTALLED_CANDIDATE` | Task and daily-action levels share the verified hierarchy and installed V21 command schema; calendar/reminder projection binding remains. |
| Event-driven workflow automation | `WINDOWS_INSTALLED_CANDIDATE` plus `LIVE_SOURCE_CANDIDATE` | Installed V20 composes the bounded explicit-drain queue. The installed command surface adds end-user rule authoring over exact already-approved Phase 6 bindings. Current source V21 enables the default-off Qt publisher through V20, forwarding native workspace notifications into the existing queues with no drain or second executor; rebuilt packaging and installed acceptance remain. |
| Cron, webhook, file, process, clipboard and screen triggers | `WINDOWS_INSTALLED_CANDIDATE` plus `LIVE_SOURCE_CANDIDATE` | Installed V20 composes authenticated webhooks, explicit-timezone occurrences and workspace-bound file normalization. Current source activation watches only explicit controlled paths, hashes path metadata and uses zero polling. Rebuilt installed proof remains; polling/process/clipboard/screen behavior remains intentionally rejected. |
| Natural-language workflow builder | `WINDOWS_INSTALLED_CANDIDATE` | The installed V21 tool lets the conversational model propose a typed automation-rule command; the host derives identity/scope and refuses any plan/mission not already approved in Phase 6. No generated JavaScript or direct execution exists. |
| Proactive awareness and activity context | `WINDOWS_INSTALLED_CANDIDATE` plus `LIVE_SOURCE_CANDIDATE` | Installed V20 composes the zero-worker metadata-first queue and the installed Cyryx HUD projects its bounded attention result on owner request. Current V20/V21 source activation binds the Qt workspace publisher; rebuilt installed proof plus foreground/calendar/mail/connectivity/mission publishers remain. |
| Recursive home-directory watcher | `REJECT_SECURITY` | Do not watch the entire home directory. Roots must be explicit, finite and workspace-bound. |
| Clipboard polling every 1-2 seconds | `REJECT_SECURITY` | Use native change notifications where available; otherwise keep the adapter disabled. Never persist raw clipboard content by default. |
| Process polling and screen capture every few seconds | `REJECT_SECURITY` | Replace with OS events/foreground-window changes and capture-on-demand. The reference defaults are incompatible with Onyx CPU and privacy goals. |
| Personality/style learning | `WINDOWS_INSTALLED_CANDIDATE` | Installed V20 composes provenance-scored suggestions. Installed commands expose suggest/get/promote/reject/rollback, route promotion through owner authority and project only approved style values into the next live-session prompt. Identity, safety, tools, providers and voice are unrepresentable. A richer owner review view remains. |
| Local knowledge vault, entities, facts and relationships | `PRESENT` | Preserve Onyx memory/control-plane lineage and provenance rules. Similarity is retrieval, not authority. |
| Content pipeline and downloadable documents | `SOURCE_CANDIDATE` | Phase 10 retains governed draft artifacts. The new durable lifecycle projection records only digest/metadata, reserves before any provider effect, requires an exact provider receipt for published state and sends nothing itself. Rebuilt package and real provider acceptance remain. |
| Gmail/Google Calendar | `PARTIAL` | Onyx DayOps uses Microsoft Graph. Google may be a future connector, but credentials belong in the OS vault and OAuth tokens must not be flat files. |
| Telegram/Discord/WhatsApp/Signal channels | `SOURCE_CANDIDATE` | Original Discord official API adapter now reserves metadata before one exact call, reads its bot credential only from the OS vault, pins account/channel scope, suppresses mentions, binds nonce and provider receipt, and enters reconciliation on uncertain outcome. It is default-off and not live without an owner credential/account registry. WhatsApp/Signal remain external connector work; unofficial session scraping remains forbidden. |
| Local browser automation through CDP | `PARTIAL` | Onyx has governed read-only browser missions. Mutating browser operations require a typed capability, domain/account binding, approval/grant and post-action verification. Arbitrary page JavaScript remains forbidden. |
| Cross-platform desktop accessibility automation | `SOURCE_CANDIDATE` | Windows keeps its stronger native controls. A new Darwin/Linux seam permits only exact application/role/name targets and four typed actions after central authority, then requires a matching native postcondition receipt. No shell, coordinates, script or polling is representable. Actual native adapters and host validation remain. |
| Raw shell, unrestricted file writes and arbitrary browser JavaScript | `REJECT_SECURITY` | Reference tools reach executors without a universal authority boundary. Onyx must route every effect through permission broker, workspace scope, immutable plan and audit. |
| Remote sidecar machines | `WINDOWS_INSTALLED_CANDIDATE` plus `SOURCE_CANDIDATE` | Installed V20 composes the authenticated registry foundation. Current source adds a salted-hash, five-attempt, five-minute, one-time pairing ceremony plus the existing explicit-send certificate-pinned TLS transport. Pairing issues no credential or authority by itself. Receiver integration and real-device acceptance remain. |
| Sidecar token in CLI arguments/YAML and JWT without expiry/audience/issuer | `REJECT_SECURITY` | Never reproduce. Tokens must not appear in process arguments or world-readable config. |
| Sidecar fair event scheduler and detached RPC state | `PARTIAL` | The fairness and two-stage timeout concepts are useful. Reimplement with bounded queues, cancellation/reconciliation and durable receipts. |
| Site/project builder and preview | `WINDOWS_INSTALLED_CANDIDATE` plus `SOURCE_CANDIDATE` | Installed V20 composes the receipt-bound controlled-root lifecycle. The source successor adds company-site, knowledge-portal and operations-console recipes using the Cyryx palette; each returns only a deterministic hash-bound Phase 6 file plan and performs zero writes/network/process calls. Rebuilt installed proof remains. |
| Direct GitHub push and token-bearing CLI URL | `REJECT_SECURITY` | Use credential helpers/API aliases, exact repository/branch scope and verified push receipts. |
| Cinematic dashboard/office/goal/workflow UI | `WINDOWS_INSTALLED_CANDIDATE` | The external React UI remains rejected. The installed original Cyryx HUD operations pill sits over the accepted arc-free Orb, preserving voice, approvals and callbacks; deeper workflow/device/site views remain. |
| Windows/Linux/macOS autostart | `SOURCE_CANDIDATE` | The DEB ships a bounded systemd-user unit, macOS carries an Aqua LaunchAgent template, and Windows now has an unchecked current-user Run-key installer task removed on uninstall. Native Linux/macOS receipts and rebuilt Windows installed proof remain required. |
| Windows/macOS/Linux install, upgrade, rollback and uninstall | `PARTIAL` | Remains a release gate. Reference test failures and native-Windows lifecycle gaps provide no reusable proof. |

## Clean-room implementation blocks

### Block A — operational control plane

1. Persistent OKR/commitment projection bound to owner, workspace and Phase 6
   plan/mission identifiers.
2. Append-only event lineage and explicit revision history.
3. Evidence-gated progress: `completed` is derived only from a verified Phase 6
   result and matching definition-of-done receipts.
4. Morning plan, attention queue and evening review are read projections; they
   cannot mutate execution truth implicitly.

### Block B — governed automation runtime

1. Versioned trigger/rule definitions compile to existing Phase 6 plans.
2. Event-driven bounded queue with coalescing, backpressure and zero idle polling.
3. Automatic dispatch may run only an already-approved, still-valid mission or
   finite grant; changed payload/target means new authority.
4. Webhook, time, file and OS-event adapters are separately feature-gated and
   independently tested.

### Block C — low-CPU awareness

1. Native events first; capture-on-demand second; polling disabled by default.
2. Metadata-first context; content collection requires explicit scope.
3. Redaction before persistence/provider use, bounded retention and owner-visible
   pause/delete controls.
4. Performance gates cover idle/minimized CPU, active frame time, queue growth,
   memory and multi-hour continuity.

### Block D — authenticated device mesh

1. Per-device asymmetric identity and enrollment through a trusted local flow.
2. Expiring issuer/audience/device-bound credentials stored in the OS vault.
3. Capability advertisements are claims, not authority; each request is still
   authorized by the Onyx host against workspace/mission/grant scope.
4. RPC request is durably registered before transport send; late/unknown outcomes
   enter reconciliation instead of blind retry.

### Block E — operational surfaces

1. Goal, workflow, awareness, device and site-builder projections in the Cyryx
   HUD/dashboard.
2. Official channel/provider adapters, each with account/recipient binding.
3. Site projects remain controlled worktrees and evidence artifacts, not a
   direct shell escape.

## Explicit non-regression invariants

- No replacement or fallback of Gemini Live/Charon.
- No second mission engine, permission broker, tool dispatcher, memory authority
  or permanent UI shell.
- No feature may classify an unknown action as read-only or safe.
- No raw credential in JSON/YAML, command line, log, URL or model context.
- No task/goal/workflow is successful solely because a model emitted text.
- No observer performs continuous screenshot/OCR/cloud upload by default.
- No copied reference names, source, visual assets or notices enter product
  artifacts.

## Verification required before a capability is called operational

For every remaining surface: authority-bypass negatives, crash/restart and
idempotency tests, flags-off regression, resource measurement, physical or
external-service acceptance where applicable and evidence-index linkage. The
bounded Windows installed result is not macOS/Linux, long-session, live Graph,
clean-host, signed-release or full product-completion proof.
