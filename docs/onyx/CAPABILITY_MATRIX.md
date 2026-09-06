# Onyx capability matrix

Document class: **cumulative historical evidence matrix**. Its Phase 0 header
and individual dated rows must not be read as the current release decision.
Current release status and unresolved gates are authoritative only in
`CURRENT_RELEASE_STATUS.md`; precedence is defined by
`DOCUMENTATION_INDEX.md`.

Status: Phase 0 evidence matrix, 2026-07-15. Each row describes the development tree at its recorded evidence point, not the target design or current release decision. Documentation, a declaration, a build recipe or a UI label is not proof that a capability works.

Current-binding correction, 2026-08-03: the active UI binding is PySide6, not
PyQt6. PyQt references in frozen or dated evidence remain historical; current
release qualification still requires exact-artifact PySide6/Qt LGPL review.

## Status vocabulary

Only these nine values are valid:

1. `WORKING_AND_VERIFIED`
2. `WORKING_WITH_LIMITATIONS`
3. `PARTIAL`
4. `STUB_OR_MOCK`
5. `NOT_IMPLEMENTED`
6. `BLOCKED_BY_ACCESS`
7. `BLOCKED_BY_LICENSE`
8. `BLOCKED_BY_PLATFORM`
9. `DEPRECATED`

Current command-scoped evidence is registered in `VERIFICATION_EVIDENCE.md`. The Phase 0 baseline scope passed 276 tests (`VE-UNIT-001`); later isolated/default-off checkpoints have their own scoped records, including M1b (`VE-M1B-001`), M2a (`VE-M2A-001`) and the non-activated native anchor infrastructure (`VE-M2B-A-001`). Pip consistency (`VE-PIP-001`), Ruff F/E9 (`VE-RUFF-001`) and compileall (`VE-COMPILE-001`) also passed at their recorded input snapshots. Browser integration did not run because Chromium launch was blocked by sandbox `spawn EPERM` (`VE-BROWSER-001`), while readiness remained not operationally verified (`VE-READINESS-001`). A verified row must cite its proportional evidence ID; unit results do not prove browser, live-provider, physical-device, LAN/mobile, native-release, same-user compromise or runtime integration behavior.

Security classes used below are: `L` local/read-only; `M` local mutation or sensitive observation; `H` external mutation, identity, publication, money or privileged execution; `C` credential/private/cross-workspace data. `H` never means pre-authorized.

## Host-native activation boundary

The current Windows normal bootstrap and packaged native-startup smoke both
resolve to V19. On macOS and Linux, the normal bootstrap prepares the V14
envelope but the Windows-only V14 through V9 launchers deliberately fall back
until V8; the packaged smoke now resolves to that same effective V8 activation.
Those non-Windows artifacts are therefore labelled
`portable-v8-fallback-capability-limited` and explicitly record
`v15_v19_parity: false`. A native smoke pass on those hosts proves only the V8
window/host startup contract under the bounded provider-free fence; it does not
prove V15, V16, V17, V18 or V19 capability parity. Every release manifest must
contain the exact host activation contract, and public-release eligibility
fails closed if the contract is absent, unsupported or mismatched.

The separate default-off portable-current gate is only a negative-boundary
proof. It reports
`activation_profile=portable-current-negative-boundary-default-off`,
`evidence_scope=portable_current_negative_boundary_gate`,
`safe_unavailability=true`, `host_constructed=false`,
`normal_activation=unavailable`, `smoke_activation=none`,
`highest_proven_activation=none`, `boundary_reached=pre_v16`, and safely refuses
the pathname-bound V16 governance engine. Its declared V19 value is a roadmap
target, while `next_unimplemented_activation=v16` identifies the next missing
portable implementation. This gate is not evidence that V15 or V19 executed.

## Current core and interaction capabilities

| Capability | Status | Exact evidence path/symbol | Environment dependency | Security class | Tests/verification | Owner | Limitations | Next action |
|---|---|---|---|---|---|---|---|---|
| Onyx identity and truthful contract | `WORKING_AND_VERIFIED` | `core/identity.py`; `core/prompt.txt`; `main.py:_load_owner_name` | Local config | L | `VE-UNIT-001`; `tests/test_missions.py:test_current_user_facing_branding_is_onyx` | Onyx Core | First-contact/name UX is not a separate governed profile service | Preserve contract; add first-contact persistence test |
| Live conversational loop | `WORKING_WITH_LIMITATIONS` | `main.py:OnyxLive`; `_build_config`; `speak`; `interrupt` | Gemini access, network, microphone/audio stack | C | Readiness and regression tests where dependencies load | Onyx Core | Cloud-oriented; availability and latency depend on provider/device | Add modality/provider readiness and explicit degraded state |
| Speech-to-text and text-to-speech | `WORKING_WITH_LIMITATIONS` | `core/stt.py`; `core/tts.py`; `core/audio_contract.py` | Audio device, OS codecs/libraries | C | Audio/readiness tests where supported | Onyx Core | Not proven on every release target; no claim of fully local inference | Host-native device and interruption tests |
| Model tool declarations/dispatch | `WORKING_WITH_LIMITATIONS` | `main.py:TOOL_DECLARATIONS`; `OnyxLive._execute_tool` | Imported action dependencies | H | `tests/test_regressions.py`; dispatcher paths | Onyx Core | Direct registry; no versioned Capability Nexus | Freeze declarations/policies as compatibility fixtures |
| Exact permission broker | `WORKING_AND_VERIFIED` | `core/permission_broker.py:authorize`, `authorize_model_tool`, `authorize_mission_tool`, policy maps | Trusted desktop callback | H | `VE-UNIT-001`; permission and mission tests; unknown actions fail closed | Onyx Core/Security | No persisted bounded grants or approval inbox | Add shadow-only exact grant evaluator |
| V17 live Governance and Founder Snapshot | `WORKING_WITH_LIMITATIONS` | `core/governance_nucleus_v1.py`; `core/onyx_live_activation_v16.py`; `core/onyx_live_activation_v17.py`; `docs/onyx/operations/ONYX_V17_FOUNDER_SNAPSHOT_ACCEPTANCE_2026-07-31.md` | Windows V15/V16 base, native vault, trusted local UI and approved local evidence | H/C | 2026-07-31: 46 Founder/V17 passes; 77 wider passes, 2 platform skips and 105 subtests; frozen and installed V17 preflight/Governance/Founder smokes passed; artifact alias+digest was reopened after restart; native protected owner/SYSTEM DACL and exact rollback gates passed | Onyx Core/Security | Windows installed-host and provider-free read-only Founder proof only; artifacts are unsigned; live Gemini/audio, external business sources, macOS/Linux and clean-machine release remain unverified | Add real approved owner sources/connectors, sign Windows artifacts and run host-native macOS/Linux plus live audio/provider gates |
| V18.1 governed Document Intake and host attachment provisioning | `WORKING_WITH_LIMITATIONS` | `core/document_intake_live_v1.py`; `core/onyx_live_activation_v18.py`; `main.py:_on_file_attachment_v18`; `ui.py:_dispatch_selected_file`; `scripts/bootstrap_onyx_live_v18.pyw`; `docs/onyx/operations/ONYX_V18_DOCUMENT_INTAKE_ACCEPTANCE_2026-07-31.md` | Windows V17 base, trusted artifact root, control plane, alias catalog and Approved Source registry | H/C | 2026-07-31: post-review focused UI/attachment/smoke/mutex gate 71 passed; final pre-mutex consolidated gate 260 passed, 9 skipped and 36 subtests, including uncertain alias commit retention, exact callback rollback and Phase 11 transient-busy startup degradation; V18 normal GUI now delegates to the exact V17 shared mutex while diagnostics bypass it; source stable-bootstrap smoke passed first+controller-reopen with four citations each and zero network/provider/process/prompts; 17/47/191 counts in the acceptance record are historical precursor gates | Onyx Core/Security | Source-level provider-free local attachment/read proof only; smoke proves in-process controller reopen, not two-process restart; V18.1 package smoke is coded but no new bundle or installed host was produced; successful Windows smoke can emit a pre-existing non-fatal Qt/COM teardown diagnostic; GC failure during pinned-state finalization may retain a fail-closed handle until process exit | Build/install V18.1, then run installed preflight, second-launch mutex check and packaged Document Intake smoke; retain explicit close/retry and V17 rollback |
| Immutable approved execution | `WORKING_AND_VERIFIED` | `core/approved_execution.py:materialize_source_request`, `validate_materialized_source_request`, `execute_materialized_source` | Filesystem/OS handles | H | `VE-UNIT-001`; race/materialization coverage in `tests/test_regressions.py` | Onyx Core/Security | Applies to current supported paths, not future connectors automatically | Require the same contract for each mutation adapter |
| Mission store and durable state | `WORKING_AND_VERIFIED` | `core/missions.py:MissionStore` public methods | SQLite/local writable data root | M | `VE-UNIT-001`; restart, transition, audit and budget tests | Mission Orchestrator | Rich operational lifecycle is not stored as a separate typed context | Freeze schemas v1/v2/v3; add sidecar only |
| Persistent mission worker/recovery | `WORKING_AND_VERIFIED` | `core/missions.py:MissionWorker`, `worker_once`, leases/heartbeats | Local thread, SQLite | M | `VE-UNIT-001`; claim, heartbeat, ownership-loss and restart tests | Mission Orchestrator | Executes only current explicit provider-free mission tools | Keep one worker; add typed connector requests later |
| Structured mission result verification | `WORKING_AND_VERIFIED` | `core/missions.py:normalize_mission_result`, `verify_mission_result`; `core/mission_tools.py:run` | None beyond local runtime | M | `VE-UNIT-001`; result/evidence/postcondition tests | Mission Orchestrator/Verifier | Step evidence is not a cross-source claim/action ledger | Add typed evidence/claim/action sidecars |
| Provider-free workspace mission tools | `WORKING_AND_VERIFIED` | `core/mission_tools.py:_roots`, `_safe`, `_root_for`, `_open_verified`, `run` | Authorized local roots | M | `VE-UNIT-001`, `VE-MISSION-DOCTOR-001`; traversal/symlink/descriptor tests | Mission Orchestrator | Narrow local tools only; not a general Operator Cell catalog | Use unchanged as first Operator Cell substrate |
| Hash-chained tool audit | `WORKING_AND_VERIFIED` | `core/tool_audit.py:append_tool_audit`, `verify_audit` | SQLite/local data root | H | `VE-UNIT-001`; audit/tamper tests | Onyx Core/Security | Content-free; no provider receipt or domain claim semantics | Reference it from new sidecars; do not add secrets/payloads |
| Local semantic/episodic memory | `WORKING_AND_VERIFIED` | `memory/store.py:MemoryStore`; `memory/memory_manager.py` | SQLite; optional FTS5 | C | `VE-UNIT-001`; persistence, search, privacy, export and concurrency tests | Memory | One global namespace; keyed updates do not preserve full supersession graph | Add pre-ranking workspace/type/validity adapter |
| Secret-safe OS credentials | `WORKING_AND_VERIFIED` | `core/credentials.py:get`, `set`, `delete`, `status`, `migrate_legacy` | Windows Credential Manager/macOS Keychain/Linux Secret Service | C | `VE-UNIT-001`; backend, migration and no-secret-output tests | Onyx Core/Security | One Gemini service/account; no workspace aliases | Retain as `legacy-default`; add opaque aliases |
| 3D Orb and adaptive fallback | `WORKING_AND_VERIFIED` | `qml/OnyxOrb.qml`; `core/orb_state.py:OrbStateBridge`; `ui.py:OrbHost` | PySide6, Qt Quick 3D; physical GPU unverified | L | `VE-UNIT-001`; QML readiness, lifecycle and software fallback tests | Onyx Experience | No physical GPU/frame-time evidence; cinematic shell remains incomplete | Add host-native frame-time/idle CPU/GPU gates |
| Official Onyx application icon | `WORKING_WITH_LIMITATIONS` | `packaging/assets/onyx-app-icon-master-v2.png`; `scripts/generate_icons.py`; `ui.py:_application_icon_path`; `docs/onyx/ONYX_APP_ICON_V2.md` | OS shell/icon cache; host-native packager | L | `tests/test_onyx_app_icon_v1.py`; 9 icon/shortcut tests; Qt offscreen runtime load | Onyx Experience/Release | Windows desktop links and generated ICO/ICNS/PNG are verified; final macOS/Linux shell rendering still needs host-native release evidence | Preserve the hash-bound transparent Orb-only V2 master and validate signed packages on each OS |
| Desktop HUD/command UI | `WORKING_WITH_LIMITATIONS` | `ui.py:OnyxUI`, current callbacks and overlays | PySide6, desktop session | C | UI/regression coverage where Qt loads | Onyx Experience | Transitional widget shell; no complete mission/evidence/connector command center | Preserve callback parity; migrate projections incrementally |
| Authenticated remote dashboard | `WORKING_WITH_LIMITATIONS` | `dashboard/server.py:DashboardServer`; `dashboard/security.py` | FastAPI/Uvicorn, TLS, LAN/firewall/device routing | C | `tests/test_dashboard_upload_security.py`; dashboard security regressions | Onyx Experience/Security | Network reachability varies; no full remote approval/command-center parity | Add authenticated read-only projections then exact remote approvals |
| Hardened remote upload/download | `WORKING_AND_VERIFIED` | `dashboard/server.py:_verified_upload_root`, `_open_upload_temp`, `_publish_upload_no_replace`, `_open_verified_download` | FastAPI multipart and filesystem semantics | C | `VE-UNIT-001`; race/link tests | Onyx Experience/Security | In-process/loopback proof only; mobile LAN path remains unverified (`VE-READINESS-001`) | Keep fail-closed; add workspace artifact routing |
| File control | `WORKING_WITH_LIMITATIONS` | `actions/file_controller.py`; central broker policy | OS filesystem/handle semantics | H | Extensive path/race regression coverage | Local Actions/Security | Allowed roots and platform semantics vary; no workspace registry | Bind roots to workspace and typed action receipts |
| Browser control | `WORKING_WITH_LIMITATIONS` | `actions/browser_control.py:_BrowserSession`, `_SessionRegistry`, `browser_control` | Playwright, installed browser, authenticated profile | H/C | Browser regressions where Playwright loads | Local Actions | No workspace profile isolation, domain allowlist, MCP or post-action provider receipt | Add isolated profiles, target policy, takeover and reconciliation |
| Computer/desktop control | `WORKING_WITH_LIMITATIONS` | `actions/computer_control.py`; permission policy | OS GUI, pyautogui/pywinauto and foreground state | H/C | Regression tests on supported platform paths | Local Actions | UI drift, DPI/dialog/account-state risk; not an Away Mode boundary | Require signed bounds, redaction, checkpoints and kill switch |
| Local code helper/project generation | `WORKING_WITH_LIMITATIONS` | `actions/code_helper.py`; `actions/dev_agent.py` | Local toolchain/filesystem | H | Materialization, path and project regressions | Engineering Operator | No normalized external agent, worktree contract, independent verifier or draft-PR lifecycle | Add Project Autopilot after trust sidecars |
| Search/news utility | `WORKING_WITH_LIMITATIONS` | `actions/web_search.py`; proactive briefing instruction in `main.py` | Network, `ddgs`, source availability | L/C | Action/regression tests where dependency loads | Intelligence Operator | Results are not a durable claim graph; source/terms/freshness vary | Emit typed cited evidence before intelligence projections |
| Social UI messaging fallback | `WORKING_WITH_LIMITATIONS` | `actions/send_message.py` | Authenticated user-visible application/browser state | H/C | Unit/policy coverage in `VE-UNIT-001`; browser execution blocked in `VE-BROWSER-001` | Local Actions | No provider receipt, official scope, reliable recipient resolution or delivery verification | Keep separately labeled; never promote official connector status from UI fallback |
| Screen/camera understanding | `WORKING_WITH_LIMITATIONS` | `actions/screen_processor.py`; capture functions imported in `main.py` | Screen/camera permissions, OpenCV/MSS, model access | C | Regression/readiness coverage where devices exist | Onyx Core | Sensitive visual data; no complete screenshot redaction/classification | Add workspace/data-class policy and redaction evidence |
| Reminders/proactive utilities | `WORKING_WITH_LIMITATIONS` | `actions/reminder.py`; `actions/proactive.py`; mission-independent declarations | OS scheduler/notifications | M | Regression tests on supported OS | Executive Operator | Not a unified durable task/calendar system | Adapt through future task connector; preserve local fallback |
| YouTube research | `WORKING_WITH_LIMITATIONS` | `actions/youtube_video.py` | Network, site behavior, unofficial `youtube-transcript-api` | C | Conditional regression tests | Intelligence Operator | Not official captions access; rights and arbitrary-public-video coverage are limited | Add source authorization/retention policy; report blocked states honestly |
| Native packaging definitions | `PARTIAL` | `packaging/onyx.spec`; `scripts/build_release.py`; `.github/workflows/release-packages.yml`; `core/paths.py` | Host-native builders, browser binaries, signing tools | H | `tests/test_packaging_paths.py`; package smoke path | Release Engineering | Definitions are not clean-machine proof; dependencies unlocked; release license blocked | Lock, inventory, sign/notarize and test each host/architecture |

## Governed operations and business capabilities

| Capability | Status | Exact evidence path/symbol | Environment dependency | Security class | Tests/verification | Owner | Limitations | Next action |
|---|---|---|---|---|---|---|---|---|
| M1a inert control-plane schema / canonical Windows activation | `BLOCKED_BY_PLATFORM` | `core/control_plane.py`; `core/paths.py::windows_local_app_data_dir`; `VE-M1A-WINDOWS-001` | Native `FOLDERID_LocalAppData`, compatible profile owner/DACL and enabled current-token capability SIDs | H | Inert schema, rollback, ACL and concurrency suite passes; live canonical Windows probe fails closed before creating managed paths | Onyx Core/Security | Schema is verified only behind explicit opt-in and is not wired into startup. This managed sandbox token exposes no enabled `TokenCapabilities`, while canonical LocalAppData has a write ACE for an unavailable capability SID. | Re-run the canonical probe under the intended installed-user token; do not weaken owner, DACL or capability checks |
| Workspace registry/isolation | `PARTIAL` | `core/workspaces.py:WorkspaceRegistry`; `LegacyWorkspaceAdapter`; `VE-M1B-001`; ADR-0002 | Explicit `ONYX_WORKSPACE_REGISTRY_V1`; initialized control-plane sidecar | C | Fail-closed identity/isolation, marker-forgery and inactive/unknown workspace tests | Onyx Core/Security | Registry and the only permitted `legacy-default` adapter exist, but are default-off, absent from startup and verified only with isolated fixtures. Credential, browser and all other legacy contexts remain global. | Obtain M1a platform acceptance, review pending candidates and prove shadow dual-read before any runtime activation |
| Mission context sidecar/operational phases | `PARTIAL` | `core/workspaces.py:LegacyContextBackfill`; `core/control_plane.py` schema v2; `VE-M1B-001` | Explicit backfill opt-in plus stable legacy mission/memory sources | H/C | Idempotence, lease fencing/recovery, concurrent convergence, partial failure, source mutation and independent full-field read-back tests | Mission Orchestrator | The synthetic fixture has exactly two missions (one assigned, one pending) and two ambiguous memories (both pending). The M1b command was not run against owner stores; a separate earlier read-only reconnaissance was not incorporated into M1b execution or evidence. Existing stores remain authoritative and byte-preserved. | Review fixture evidence and pending-candidate workflow; do not enable startup integration |
| Evidence, claims and action ledgers | `PARTIAL` | `core/domain_ledger.py`; isolated `core/control_plane_v3.py`, `core/domain_ledger_v3.py`, `core/ledger_anchor.py`, `core/native_vault.py`, `core/control_plane_v5.py`, `core/mission_evidence_v5.py`; historical/rejected Phase 4 exit R1-R5; accepted `VE-P4-EXIT-R6-E6-001` | All enhanced repositories remain explicit/default-off; production owner wiring and external providers remain unavailable | H/C | R12 binds 80 files; R6 binds 12 source inputs and 5 artifacts; stored and fresh independent runs each passed 72 tests plus 6 subtests; three independent reviews passed with 0 P0/P1/P2 | Verifier/Security | Phase 4 default-off exit is accepted for implementation handoff only. No production import, owner wiring, external provider, grant, approval inbox or runtime activation is claimed. | Begin Phase 5 implementation default-off; require separate proportional evidence and explicit approval before any live grant, connector or activation |
| Bounded session grants/autonomy envelopes | `PARTIAL` | Accepted default-off Session Grants R11: `core/session_grants_v11.py`; `VE-P51-GRANTS-R11-E6-001` | Trusted signing key/session identity | H | R11 external E6 acceptance binds exact-match, drift, expiry, revoke, replay and kill behavior in shadow mode | Onyx Core/Security + Cyryx owner | Accepted only for isolated default-off handoff; no startup/live authority or exact low-risk enablement | Build and independently accept the exact low-risk enablement slice; never waive always-explicit gates |
| Approval inbox/calm batch approval | `PARTIAL` | Accepted frozen V15: `core/approval_inbox_v15.py`; `VE-P52-APPROVAL-INBOX-V15-E6-001` | Isolated/default-off contracts only | H | 130 focused and 1,032 combined passes; regressions 172 tests plus 265 subtests; three external reviews passed with 0 P0/P1/P2 | Onyx Experience/Security | Accepted only as a read-only, non-authoritative projection; no approve/deny/dispatch authority and no startup/live/UI/dashboard wiring | Preserve V15; build a separately reviewed Phase 5 integration checkpoint without widening authority |
| Capability Nexus connector registry | `PARTIAL` | Current source-integrity successor `VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001`; `docs/onyx/acceptance/VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001.manifest.json`; frozen V32 retained as historical-only | Isolated/default-off contracts only | H/C | Exact 32-version implementation/test catalog plus 32 immutable historical manifests; independent current/history root and tamper gates | Capability Nexus | Descriptor discovery, legacy parity and one local read-only adapter remain default-off; the successor changes no dispatch, startup, runtime or UI wiring | Use the current successor for working-tree claims; preserve V1–V32 manifests as historical tombstones and complete remaining live integration gates separately |
| MCP client/server integration | `NOT_IMPLEMENTED` | No runtime MCP registry/adapter | MCP transport/server access | H/C | No protocol, auth, cancellation or receipt tests | Capability Nexus | Browser Playwright is not MCP | Prove one local read-only MCP adapter |
| Provider/model router | `PARTIAL` | Gemini Live: `main.py:OnyxLive` + `core/live_model.py:resolve_live_model`; local/text: `core/llm_client.py` Ollama/OpenAI-compatible backends | Gemini credentials/network for Live; configured local/OpenAI-compatible endpoint for text | C | Current model/readiness tests only; no modality-specific router parity bundle | Model Router | Two independent current paths exist, but no shared registry, privacy constraint engine or cost/eval routing; Live and text parity/rollback are unproven independently | Preserve both as separate versioned compatibility adapters with unchanged call sites/defaults; add separate Live and text parity/eval/rollback gates before routing |
| Operator Cells | `PARTIAL` | Accepted default-off guild chain: `core/guild_profiles_v1.py` (`VE-GUILD-PROFILES-V1-E6-001`), `core/guild_handoff_v1.py` (`VE-GUILD-HANDOFF-V1-E6-001`), `core/guild_workflow_v1.py` (`VE-GUILD-WORKFLOW-V1-E6-001`), `core/guild_execution_intent_v1.py` (`VE-GUILD-EXECUTION-INTENT-V1-E6-001`) — 2026-08-17/19, autonomous-session acceptances, no independent human review | Accepted Phase 10 content-draft entry evidence; first-party AEXOS pack (`CyryxLabs/aexos-engine`); exact Phase 11 autopilot bytes for the intent slice | H/C | 170 adversarial guild tests across the four slices; final 31-file cumulative gate 796 passed, 96 subtests, 17 platform skips | Mission Orchestrator | Descriptive substrate plus inert execution-intent binding, exactly default-off and unwired; intents are version-pinned to the exact autopilot, forward-only, owner-approval-required by construction, and `is_dispatchable` is structurally False; no dispatch, session, grant or budget surface exists | Build A9.5 (governed away-mode envelope with hard budgets, KPIs and the decommission policy), then the separately gated runtime dispatch slice |
| Guild audience/strategy substrate | `WORKING_AND_VERIFIED` | Accepted default-off `core/phase10_audience_strategy_v1.py` (`VE-P10-AUDIENCE-STRATEGY-V1-E6-001`, 2026-08-19, autonomous-session acceptance) | None — deterministic, hermetic, no network | C | Cited-research, per-platform KPI, 30/60/90 key-set, funnel-closure and experiment sample-floor tests (32-file gate, 833 passed) | Social Operator + Cyryx owner | Strategy records and projections only; no publishing/scheduling, no live provider read, no analytics ingestion | Bind to the gated publish/analytics slices once provider access exists |
| Argos world-intelligence (proprietary) | `WORKING_AND_VERIFIED` | Accepted default-off `core/argos_v1.py` (`VE-ARGOS-V1-E6-001`, 2026-08-19, autonomous-session acceptance); `docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md:Argos` | Owner-gated live fetch via the accepted Phase 9 live-ingestion connector | C | Registered-source/rights-note, closed 8-category and 4-kind taxonomies, bounded scores, deterministic ranking tests (33-file gate, 868 passed) | Intelligence Operator + Cyryx owner | Registry and deterministic briefs only — original 100%-proprietary Cyryx work, no third-party World Monitor code; `is_actionable` structurally False; **live world-intelligence remains unproven** (no real fetch has run) | Run the owner-gated live fetch against registered sources, then conflicting-claim evaluation |
| Company Graph | `PARTIAL` | Accepted `core/phase7_company_graph_v1.py`; `VE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001` | Accepted approved-source and workspace contracts | C | Phase 7 aggregate acceptance reproduced 240 tests plus 80 subtests | Company Knowledge Operator | Exactly default-off, read-only and unwired; no live provider/source retrieval | Bind only through later accepted retrieval and live-projection gates |
| Founder Brief/portfolio command | `PARTIAL` | Accepted `core/phase7_founder_command_v1.py`; `VE-P7-FOUNDER-COMMAND-V1-E6-001` | Accepted Company Graph inputs | C | Cited daily/weekly, freshness, conflict and ranking tests in accepted Phase 7 | Executive Operator | Deterministic default-off projection; no scheduler, live source intake or UI wiring | Bind to accepted executive-office intake without widening authority |
| Email connector | `PARTIAL` | Accepted GET-only `core/phase8_microsoft_graph_read_v1.py` (`VE-P8-MICROSOFT-GRAPH-READ-V1-E6-001`); accepted exact-recipient draft/send `core/phase8_microsoft_graph_mail_v1.py` (`VE-P8-MICROSOFT-GRAPH-MAIL-V1-E6-001`) | Microsoft OAuth onboarding, `Mail.ReadWrite`+`Mail.Send` consent and a confirmed live send remain required for live use | H/C | Read: 24 focused; send: content-verified exact-recipient grant, two-step reconcilable send, uncertain-reconcile, durable-ledger one-shot tests | Capability Nexus + Cyryx owner | Read/search/local-draft + contract-only exact-recipient send (default-off); no live send E2E, reply/forward/delete/attachment | Prove live send E2E under `Mail.ReadWrite`+`Mail.Send` consent + confirmed run with a durable nonce ledger; then reply/thread successors |
| Calendar connector | `PARTIAL` | Accepted GET-only `core/phase8_microsoft_graph_read_v1.py` (`VE-P8-MICROSOFT-GRAPH-READ-V1-E6-001`); accepted availability + exact-grant create `core/phase8_microsoft_graph_calendar_v1.py` (`VE-P8-MICROSOFT-GRAPH-CALENDAR-V1-E6-001`) | Microsoft OAuth onboarding, `Calendars.ReadWrite` consent and a confirmed live run remain required for live mutation | H/C | Read/brief/paging/rotation tests; conflict/availability, exact-grant single-event create, reconciliation and uncertain-outcome tests | Capability Nexus + Cyryx owner | Read + local availability + one route-pinned single-event create (contract-only, default-off); no live mutation E2E, invite, update, cancel, recurrence or shared-calendar | Prove live mutation E2E under `Calendars.ReadWrite` consent + confirmed run; then invitation/update successors |
| Tasks/notifications connector | `PARTIAL` | Accepted `core/phase8_microsoft_graph_tasks_v1.py`; `VE-P8-MICROSOFT-GRAPH-TASKS-V1-E6-001` | Microsoft OAuth onboarding, `Tasks.ReadWrite` consent and a confirmed run remain required for live task create | H/C | Deterministic notification router (urgency/quiet-hours/workspace/device) and exact-grant To Do task create + reconciliation tests | Executive Operator + Cyryx owner | Contract-only: pure local notification routing + one route-pinned To Do task create (default-off); no live task-create E2E, update/delete/complete, list mutation or provider push | Prove live task-create E2E under `Tasks.ReadWrite` consent + confirmed run with a durable nonce ledger; then update/complete successors |
| DayOps live daily brief | `WORKING_WITH_LIMITATIONS` | `core/dayops_profile_v19.py`; `core/dayops_identity_provisioning_v19.py`; `core/dayops_graph_factory_v19.py`; `core/dayops_connection_v19.py`; `core/onyx_live_activation_v19.py`; `ui.py:DayOpsConnectionDialog`; `scripts/bootstrap_onyx_live_v19.pyw`; `docs/onyx/operations/ONYX_V19_DAYOPS_ACCEPTANCE_2026-07-31.md` | Cyryx Labs Microsoft Entra public-client application ID, owner device-code consent, native vault and live Graph/network access | C | 2026-07-31: 30 persistent-core passes; 72 connection/activation/UI/V18 regression passes; 10 package-hygiene passes; source V19 preflight and disconnected smoke passed with five callbacks and zero network/provider/prompts | Executive Operator/Onyx Core | Persistent identity-bound read-only onboarding and trusted GUI are source-verified. Refresh tokens remain in the native vault and process environment is not authority. A live Microsoft provider read cannot be claimed until the owner supplies/registers the public client ID and completes one-time device consent; packaged V19, signing, clean-machine and native macOS/Linux evidence are still pending. | Build/install V19, complete one-time Microsoft consent, then capture a redacted live calendar plus unread-mail read |
| Document/Drive office connector | `PARTIAL` | Accepted metadata-only read `core/phase8_microsoft_graph_drive_v1.py` (`VE-P8-MICROSOFT-GRAPH-DRIVE-V1-E6-001`) | Microsoft OAuth onboarding and `Files.Read` consent plus a confirmed live listing remain required for live use | H/C | Gating, scope denial, route pinning (incl. `/content` denial), bounded `MAX_PAGES`/`MAX_ITEMS` paging, cross-route nextLink denial, shape-drift denial, token caching/refetch/rotation tests | Capability Nexus + Cyryx owner | Contract-only route-pinned `Files.Read` metadata listing of drive root/children/item (default-off); no content download, SharePoint enumeration, mutation or live E2E | Prove live listing E2E under `Files.Read` consent + confirmed run; then content-download and SharePoint successors |
| Intelligence claim pipeline | `PARTIAL` | Accepted deterministic ingestion contract `core/phase9_intelligence_ingestion_v1.py` (`VE-P9-INTELLIGENCE-INGESTION-V1-E6-001`), transparent scorer `core/phase9_opportunity_scoring_v1.py` (`VE-P9-OPPORTUNITY-SCORING-V1-E6-001`) and route-pinned live-source connector `core/phase9_live_ingestion_v1.py` (`VE-P9-LIVE-INGESTION-V1-E6-001`); `actions/web_search.py`; current memory/evidence primitives | Owner-gated live network run (source registration, egress, consent) | C | Ingestion (temporal/dedup/claim-typing/source-health/corroboration), scoring (12-dimension transparent) and live-connector CONTRACT (route pin, redirect-disabled, registry-attributed health, grammar-validated origin/path) tests, default-off; the live network fetch itself is not yet exercised | Intelligence Operator + Cyryx owner | Contract-only ingestion + scoring + live-connector (default-off); the real live fetch is owner-gated/deferred; conflicting-claim detection absent and Argos (proprietary world-intelligence) not yet built; a score/item can never trigger an action | Run the owner-gated live fetch against registered sources under consent; then conflicting-claim eval and the Phase 9 exit |
| Argos world-intelligence (historical row) | `SUPERSEDED` | Superseded 2026-08-19 by the accepted Argos V1 registry row above (`VE-ARGOS-V1-E6-001`) | — | C | — | Intelligence Operator + Cyryx owner | This row recorded the pre-build state (`NOT_IMPLEMENTED`, no adapter). It is retained for history only and must not be read as the current state | Read the accepted Argos V1 row; live world-intelligence remains owner-gated |
| Social organic publishing/analytics | `BLOCKED_BY_ACCESS` | No official connector; `actions/send_message.py` only UI fallback | Meta/LinkedIn/TikTok/X app review and test accounts | H/C | No official connector receipts/E2E | Social Operator + Cyryx owner | Fallback cannot prove delivery or analytics | One provider, test account, read/draft before publish |
| Brand + social-account inventory | `WORKING_AND_VERIFIED` | Accepted default-off inventory contract `core/phase10_brand_passport_v1.py` (`VE-P10-BRAND-PASSPORT-V1-E6-001`) | None — deterministic, hermetic, no network | C | Brand-passport guards, strict `(platform,handle)`→one-account separation, entry-bind and default-off tests (24-file gate, 504 passed) | Social Operator + Cyryx owner | Inventory only; `can_publish` structurally `False`; no live provider connection or publishing | Add later gated Phase 10 slices (provider connector, research, content pipeline, publishing) each separately accepted |
| Editorial calendar + approval ledger | `WORKING_AND_VERIFIED` | Accepted default-off calendar contract `core/phase10_editorial_calendar_v1.py` (`VE-P10-EDITORIAL-CALENDAR-V1-E6-001`) | None — deterministic, hermetic, no network | C | Lifecycle/approval-gate/idempotency/injected-clock/entry-bind tests (25-file gate, 538 passed) | Social Operator + Cyryx owner | Plan + approve only; `published` not representable, no publish method; `is_ready_to_publish` is readiness only | Add the gated provider-connector + publish slices, each separately accepted |
| Provider account-status read (contract) | `WORKING_AND_VERIFIED` | Accepted default-off read-only connector `core/phase10_provider_connector_v1.py` (`VE-P10-PROVIDER-CONNECTOR-V1-E6-001`); post-acceptance module drift (2026-07-25→08-10, released in R15B) documented in `CORRECTION-P10-PROVIDER-CONNECTOR-POST-ACCEPTANCE-DRIFT` and re-bound by current successor `VE-P10-PROVIDER-CONNECTOR-CURRENT-V1-E6-001` | Owner-gated live fetch (OAuth/app-review + test account) | C | Route-pin/anti-spoof/origin-grammar/payload-bounds/entry-bind tests over injected transport (26-file gate, 570 passed at acceptance; 32 reproduced under the successor); no real network | Social Operator + Cyryx owner | Read-only status; no publish method; live fetch `BLOCKED_BY_ACCESS`, verified with a fake transport; accepted 07-25 bytes locally unrecoverable — current bytes are the released ones | Owner-gated live read against a test account under consent; then the gated publish slice |
| Content draft + provenance/policy gate | `WORKING_AND_VERIFIED` | Accepted default-off content-draft contract `core/phase10_content_draft_v1.py` (`VE-P10-CONTENT-DRAFT-V1-E6-001`) | None — deterministic, hermetic, no network | C | Provenance/claim-validation/accessibility/policy-review/entry-bind tests (27-file gate, 607 passed) | Social Operator + Cyryx owner | Draft + gate only; `published` unrepresentable, no publish/schedule method; `is_ready_for_calendar` is readiness only | Add the gated schedule/publish + analytics slices, each separately accepted |
| Community/inbox operations | `BLOCKED_BY_ACCESS` | No normalized provider inbox/moderation connector | Provider messaging scopes/webhooks | H/C | No identity/thread/moderation tests | Social Operator + Cyryx owner | Generic message automation lacks provider state | Build read-only inbox triage with exact account/workspace binding |
| Project Autopilot/Away Mode | `PARTIAL` | V15 live-wired audit/static mutation plus default-off executable sandbox and exact host-ledger successor: `core/phase11_project_autopilot_v1.py`, `core/phase11_executable_sandbox_v1.py`, `core/phase11_execution_ledger_v1.py`, `core/phase11_live_mission_v1.py`, `core/onyx_live_activation_v15.py` | Exact clean Git authority, trusted roots, official sandbox host, complete Docker/platform/image flags and exact enabled execution ledger | H/C | Sandbox, ledger, autopilot, reconciliation and V15 live tests; source-only process adapters, no real-Docker/package/E6 proof | Engineering Operator/Security | The public autopilot accepts only the exact official sandbox host and exact enabled ledger; its process adapter receives neither secret. Intent/reservation precede dispatch. `recovered_receipt` accepts only the exact ledger-authenticated canonical receipt for the original mission/execution/attempt; invalid or missing evidence remains `attempted_unknown`, cancel-before-launch does not dispatch, and no recovery retries. `proven_not_executed`, retry/takeover, commit/push/merge/deploy/install, owner-repository writes and coding-agent authority remain unavailable. No external monotonic anchor, real-Docker observation, rebuilt package or E6 is claimed. | Run exact-image real-Docker and installed-package gates, add external monotonic anchoring if required, then obtain independent E6 |
| Governed browser Away Mode V1 | `WORKING_WITH_LIMITATIONS` | `core/phase11_governed_away_v1.py`; live binding/kill/runner in `core/phase11_live_mission_v1.py`; V15 constructor integration; `main.py` mission API; `docs/onyx/PHASE11_GOVERNED_AWAY_V1.md` | Windows V15, Playwright Chromium, desktop session, exact configured workspace root and public HTTPS allowlist | H/C | 74 deterministic/adversarial contract tests plus one opt-in smoke skip, 16 MissionStore/live tests, 63 Phase 11/V15 regression tests plus 11 subtests and one platform skip, and one opt-in real headed `example.com` smoke; all focused gates use warnings-as-errors; no independent E6 or installed-package smoke | Local Actions/Security | One anonymous public read action only. A signed runtime deadline starts at approved lease/dispatch, binds immutable plan/execution/DNS pin and is capped at the 60-second worker lease. Informational Chromium probes have a five-second cache; dispatch always re-probes before intent. Resolver rules pin the validated public destination while context-wide routing rejects later DNS drift, service workers and popups; WebSockets are denied and QUIC/WebRTC/WebTransport suppressed. Query/fragment targets fail closed. Windows descriptor-bound storage protects authority records; profile identity is pinned across browser lifetime and then atomically quarantined by handle under the pinned parent, never path-deleted after authority release. MissionStore receives only hashes/counts/opaque refs. Pause and takeover are terminal; resume is refused. Shutdown blocks new runners, durably stops Away, joins MissionWorker through its authority observer, then closes handles before rollback. Transient binding/Away-root contention degrades unavailable through a closed reason enum exposed by V15; missing or invalid reasons fail preflight, and invalid ACL/namespace remains distinct. Global kill reports incomplete on binding/kill/stop failures. Late cancel/kill/flags/URL/deadline cannot commit. Native computer reports unavailable; authenticated accounts and all browser mutations are excluded. | Obtain independent review/E6 and rebuilt installed-host proof; then design a separate authenticated-account read slice and a verified window/DPI native driver before any broader authority |
| Codex CLI adapter | `BLOCKED_BY_ACCESS` | No normalized runtime adapter; license review documents gap | Installed/authenticated CLI and permitted account | H/C | Auth/cancel/receipt/worktree tests absent | External Agent Adapter + Cyryx owner | No current integration | Add disabled adapter, capability health and read-only probe |
| Claude Code external coding-agent V1 | `HEALTH_ONLY_FAIL_CLOSED` | `core/external_agent_adapter_v1.py`; Phase 11 refusal/cleanup route in `core/phase11_live_mission_v1.py`; V15 factory in `core/onyx_live_activation_v15.py`; model truth in `main.py`; `docs/onyx/operations/PHASE11_EXTERNAL_AGENT_ADAPTER_V1.md` | Host-installed official Claude Code CLI and exact allowlisted Program Files Git for non-billable health only | H/C | Exactly 31 warnings-as-errors adapter/Phase 11 tests plus 18 V15/onboarding tests; point-in-time non-billable host health probe passed | External Agent Adapter + Cyryx owner | Claude Code 2.1.220 exposes no authenticated execution-bound account receipt, so billable dispatch and external-agent mission creation fail closed. Executables are rehashed from held handles on every open; reparse ancestors are rejected; a suspended child image is queried and independently held before resume, then matched by volume/file ID and SHA-256. Terminal and orphan quarantine share one cap of eight, with an `always_confirm` bounded handle-safe cleanup tool. No coding request, commit, push, PR, deploy, installed-package operation, E6, macOS/Linux or clean-machine proof is claimed. | Keep dispatch unavailable until an official provider protocol supplies an authenticated receipt bound to the same execution and the suspended-image boundary receives independent review |
| Google Antigravity adapter | `BLOCKED_BY_ACCESS` | No runtime adapter | Supported SDK/CLI and account access | H/C | No contract tests | External Agent Adapter + Cyryx owner | Product/API availability and terms require revalidation | Keep disabled until official integration path is documented |

Phase 11 Stage A-E evidence update (2026-07-30): the `Project
Autopilot/Away Mode` row remains `PARTIAL`, default off and Windows only. The
the recorded Stage A-E proportional selection passed 2,181 tests with 6 skips and 92
subtests. It covers the centralized handle-relative namespace, signed
pre-population provenance, protected streamed bundle, typed handle patch
engine, trusted Live binding/artifact I/O, explicit Job HANDLE signatures,
capped/refcounted mission locks, non-evicting high-water caps, expanded reserved
device names and best-effort directory flush. It does not add E6,
installed-host proof, live executable test/build authority, confidentiality from
same-user/admin processes or a hardware-power-loss guarantee.
| Meta/Google paid-media reporting | `BLOCKED_BY_ACCESS` | No Marketing/Google Ads client | Developer token/OAuth/test account | C/H | Reporting/attribution contract tests absent | Paid Media Operator + Cyryx owner | No verified measurement inputs | Start read-only reporting and measurement audit |
| Paid-media mutation/spend control | `BLOCKED_BY_ACCESS` | No runtime connector or spend policy implementation | Approved ad account, billing and test/sandbox support | H | No paused-create, spend-bound or reconciliation E2E | Paid Media Operator + Cyryx owner | Real spend must never be a test fixture or implicit authority | Implement draft/create-paused only after hard spend gates |
| Flight search/comparison | `WORKING_WITH_LIMITATIONS` | `actions/flight_finder.py` browser/Gemini flow | Browser, network, Google Flights/model availability | C | Conditional action/regression coverage | Travel Operator | Non-exhaustive visible-result parsing; no licensed inventory/reprice | Add authorized inventory read adapter and source disclosure |
| Flight booking | `BLOCKED_BY_ACCESS` | No Amadeus/order/booking connector | Provider credentials, market/consolidator, traveler/payment flow | H/C | Reprice/payment/reconciliation/receipt E2E absent | Travel Operator + Cyryx owner | Purchase and uncertain-payment handling not implemented | Require exact final confirmation and provider reconciliation |
| Nighttime Knowledge Refinery | `NOT_IMPLEMENTED` | Target only in master plan Phase 14 | Scheduler, authorized sources, budgets and artifact store | C | Dedupe/poisoning/rights/promotion/restart tests absent | Knowledge Operator/Verifier | No candidate/promotion pipeline; no autonomous runtime self-change allowed | Start with approved local provider-free sources and candidate-only writes |
| Unified Command Center projections | `PARTIAL` | Current `ui.py`, dashboard and mission status; target `TARGET_ARCHITECTURE.md` section 4.8 | Stable control-plane records | C/H | Current UI tests only; no full projection parity/visual E2E | Onyx Experience | Mission/approval/evidence/cost/connector surfaces incomplete | Add read-only projections after sidecar contracts stabilize |
| Cost/quota/quality observability | `PARTIAL` | Current system monitor and mission budgets; scattered status/audit data | Provider usage/price/quota APIs | C/H | No unified cost/reconciliation quality suite | Margin Governor/Observability | No cross-model/connector economic ledger | Add typed usage events and hard policy budgets |
| Kill switch and incident response | `PARTIAL` | Current audit-unhealthy stop behavior and local cancellation; policy in `THREAT_MODEL.md` | Trusted UI/session and connector revoke mechanisms | H | Current cancellation/audit tests; no global connector/grant E2E | Security + Cyryx owner | No single control revokes grants and freezes all external mutations | Implement control-plane kill state with fail-closed service checks |
| Proprietary/public release | `BLOCKED_BY_LICENSE` | `docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md`; `packaging/onyx.spec`; release workflow | Ownership evidence, PySide6/Qt LGPL compliance, SBOM/notices/signing | H | No complete exact-artifact license and clean-machine evidence | Release Engineering/Legal + Cyryx owner | PySide6/Qt artifact compliance, durable source-rights evidence, `crypto-js`, SBOM and notices remain unresolved | Fail publication closed until every durable release gate passes |

## Phase 4 E1-E6 accepted default-off checkpoint

External acceptance `VE-P4-EXIT-R6-E6-001` anchors the frozen R6 top source
manifest. E6 is closed for default-off implementation handoff; all Phase 4
flags remain off and capability status remains unchanged.

| Capability | Before | Candidate after | Exact evidence | Limitation | Owner | Next action |
|---|---|---|---|---|---|---|
| M1a inert schema / canonical Windows activation | `BLOCKED_BY_PLATFORM` | `BLOCKED_BY_PLATFORM` | `VE-M1A-WINDOWS-001`; `VE-P4-EXIT-CANDIDATE-001` | Intended installed-user token/DACL gate remains unproven | Onyx Core/Security | Re-run canonical gate without weakening policy |
| Workspace registry/isolation | `PARTIAL` | `PARTIAL` | `VE-M1B-001`; `VE-P4-EXIT-R6-E6-001` | Owner backfill, dual-read and credential/browser isolation remain excluded | Onyx Core/Security | Begin only reviewed Phase 5 default-off implementation; prove shadow dual-read and zero-leak adapters before activation |
| Mission context sidecar/operational phases | `PARTIAL` | `PARTIAL` | `VE-P4-EXIT-R6-E6-001` | Isolated v4 fixture only; no startup/owner wiring | Mission Orchestrator | Continue default-off implementation with a separate production-integration and rollback gate |
| Evidence, claims and action ledgers | `PARTIAL` | `PARTIAL` | `VE-P4-EXIT-R6-E6-001` | Provider-free/default-off only; no external mutation or owner wiring | Verifier/Security | Phase 5 default-off implementation may begin; live authority remains separately gated |

R1 through R5 are historical/rejected exit candidates. Their positive results
remain historical evidence, but none may be cited as current Phase 4 exit
acceptance. R6 replaces them with fresh evidence over R12, a top-level source
manifest that binds its artifact manifest, and the external anchor recorded in
`VE-P4-EXIT-R6-E6-001`. The accepted transition changes no capability status:
the governed repositories remain `PARTIAL` and default-off. Phase 5
default-off implementation may begin, while live grants, connectors, owner
data, startup wiring and activation remain outside this acceptance.

## Phase 5.2 Approval Inbox accepted default-off checkpoint

External acceptance `VE-P52-APPROVAL-INBOX-V15-E6-001` anchors frozen V15
root `279052fbcaf3018f7fee6733e063e94c67e90e7ce62a2a2cdc7742b55470631f`.
The accepted scope is limited to the bounded calm-batch projection and
read-only review-selection handoff. V15 remains default-off, non-authoritative
and unwired: it cannot approve, deny, dispatch, grant authority or suppress the
trusted execution callback. The V15 artifact DAG deliberately excludes this
mutable matrix and `VERIFICATION_EVIDENCE.md`; its content-addressed snapshots
preserve the historical projection bytes instead.

Phase 5 remains incomplete. Exact low-risk enablement, the Phase 5 Runtime Core
integration checkpoint and the Phase 5 E1-E6 exit decision are pending. The
fixed 26-path live scan is not a repository-wide proof, full verification is
expensive, and a forced external interruption can orphan an approximately
479 MiB verifier sandbox. These are offline-evidence limitations, not live
Onyx runtime resource consumption.

## Capability Nexus current source-integrity successor

Current authority `VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001` is bound by
`docs/onyx/acceptance/VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001.manifest.json`.
It closes the catalog to exactly 32 implementation modules and 32 matching
regression suites, and authenticates all 32 predecessor `VE-ARTIFACTS`
manifests as immutable historical-only tombstones. The successor verifier does
not rebind embedded predecessor digests to live bytes and changes no runtime
semantics. The frozen V32 decision below remains history for its exact candidate,
not evidence for the current working tree.

## Phase 5.3 Capability Nexus historical default-off checkpoint

Historical acceptance `VE-P53-CAPABILITY-NEXUS-V32-E6-001` anchors frozen V32
root `86cc174fb212f51c56b59cb9043c8cb59e765307eea2c32a7a44857f6112bfa3`.
The accepted scope is limited to descriptor-only discovery/health/snapshots,
byte-preserving legacy shadow descriptors and the isolated local read-only
catalog adapter. The V32 artifact DAG deliberately excludes this mutable matrix
and `VERIFICATION_EVIDENCE.md`; content-addressed snapshots preserve the
historical projection bytes instead.

Phase 5 remains incomplete. Approval Inbox V15 is separately accepted only as
a default-off/read-only/non-authority handoff; exact low-risk enablement,
runtime integration and the Phase 5 E1-E6 exit decision are still pending. V32 adds no dispatch authority and no
startup, live-runtime, UI, dashboard, MCP, provider or external-mutation wiring.
Its path gate requires a non-concurrently-mutated authoritative tree because it
is a stable-state metadata precheck, not an atomic TOCTOU boundary. The 300s
deadline is an offline verifier limit and has no live Onyx CPU surface.

## Phase 5 Runtime Core V10 accepted default-off checkpoint

External acceptance `VE-P5-RUNTIME-V10-E6-001` anchors frozen candidate
manifest `1cc83a994194b3ecb87bf43a91db4219cf480d48da7821e7057eb4e068ca01cb`.
The accepted scope is limited to the isolated Runtime Core V10 implementation
and its fail-closed decision, health, projection and termination contracts.
The candidate remains default-off and unwired: no import or feature flag was
added to `main.py`, `ui.py`, `dashboard/`, startup or launchers.

Phase 5 remains incomplete. Runtime integration, exact low-risk enablement and
the Phase 5 E1-E6 exit decision are still pending. The prior integrity P3
external-root/process limitation is resolved only for the exact accepted
four-anchor root. The approximately 102 KiB/2,744-line core remains a P3
maintainability advisory and must be split only in a new reviewed version.

## Phase 6 E1-E5 exit candidate V1 (E6 pending)

This delta records the current Phase 6 implementation truth after the accepted
component gates and the point-in-time V13 live composition. E6 pending means
the aggregate Phase 6 checkpoint is not yet accepted. This candidate does not
unlock Phase 7, add a remote cross-route, grant external-agent authority, or
establish permanent provider availability.

| Capability | Before | Candidate after | Exact evidence | Limitation | Owner | Next action |
|---|---|---|---|---|---|---|
| Agentic Core and Phase 5 session integration | `PARTIAL` | `PARTIAL` | `VE-P6-AGENTIC-CORE-V6-E6-001`; `VE-P6-LIVE-INTEGRATION-V2-E6-001`; `VE-P6-LIVE-WIRING-V1-E6-001` | Accepted foundations are session-bound in V13, but the aggregate Phase 6 exit is not accepted | Mission Orchestrator/Security | Reproduce the aggregate closure and obtain independent E6 acceptance |
| Gemini Live compatibility | `WORKING_WITH_LIMITATIONS` | `WORKING_WITH_LIMITATIONS` | `VE-P6-GEMINI-LIVE-COMPAT-C003-E6-001`; `ONYX_V13_LIVE_PROMOTION_2026-07-23.md` | Compatibility acceptance used a fake client; V13 proves only point-in-time real voice/provider operation | Onyx Core/Model Router | Retain the existing live path and recheck availability/device readiness operationally |
| Local/text compatibility | `PARTIAL` | `PARTIAL` | `VE-P6-LOCAL-TEXT-COMPAT-V1-E6-001` | Ollama/OpenAI-compatible parity is accepted in isolation; no remote cross-route or silent fallback is authorized | Model Router | Keep local/private routing fail-closed until a separately reviewed router successor |
| Provider registry and privacy-hard planning | `PARTIAL` | `PARTIAL` | `VE-P6-PROVIDER-REGISTRY-V1-E6-001`; `VE-P6-UNIFIED-ROUTER-V1-C002-E6-001` | Registry/plan metadata is live-composed, but remote Gemini remains blocked by policy in Router V1 | Model Router/Security | Accept the Phase 6 aggregate before adding any provider or cross-route |
| Provider-free Research/Verifier Cells | `NOT_IMPLEMENTED` | `PARTIAL` | `VE-P6-RESEARCH-CELLS-V1-E6-001`; `VE-P6-LIVE-WIRING-V1-E6-001` | Distinct authenticated research/verifier roles exist and are session-bound; no provider-backed execution route is claimed | Mission Orchestrator/Verifier | Obtain aggregate E6, then expose only a governed, receipted command route |
| Local read-only MCP adapter | `NOT_IMPLEMENTED` | `PARTIAL` | `VE-P6-LOCAL-MCP-V1-E6-001`; Local MCP C002 dependency reacceptance; `VE-P6-UNIFIED-ROUTER-V1-C002-E6-001` | Protocol and read-only identity are accepted; V13 opens no MCP process and performs no MCP dispatch | Capability Nexus | Preserve read-only scope and add a separately observed local transport run after aggregate E6 |
| Disabled external-agent descriptor | `BLOCKED_BY_ACCESS` | `BLOCKED_BY_ACCESS` | `VE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001` | Descriptor is truthful and live-composed with `authority_granted=false`; no agent is installed, authenticated or dispatched | External Agent Adapter/Cyryx owner | Keep disabled until a permitted installed/authenticated test environment exists |
| Phase 6 live composition | `PARTIAL` | `PARTIAL` | `VE-P6-LIVE-WIRING-V1-E6-001`; frozen Live Wiring V2 candidate; `ONYX_V13_LIVE_PROMOTION_2026-07-23.md` | V13 composes the accepted foundations and metadata-only V2 components, but Live Wiring V2 and this aggregate exit still await independent E6 | Onyx Core/Security | Freeze the Phase 6 Exit Candidate V1 bundle, run proportional regressions and complete E6 |

## Phase 6 E6 accepted default-off implementation exit

External acceptance `VE-P6-EXIT-CANDIDATE-V1-E6-001` binds candidate manifest
`6c32277bcbf17130eb60103538de6b58966a43dcd6b30a12c2aaf1e2e4b6493d`,
artifact root
`ab8d1465c375a6ff183d844b89cae247ce5cf846e35de15b142683fe9be1390f`,
and 34 component/operational evidence roots. The independent selection passed
294 tests across 14 fresh Python processes with zero failures, errors, or
skips.

Phase 6 is accepted for the roadmap's default-off implementation handoff.
Phase 7 default-off implementation may begin. This decision adds no runtime
authority, provider, remote cross-route, MCP process, external-agent
installation, or live flag. Gemini availability remains operational and
point-in-time; the External-Agent descriptor remains `BLOCKED_BY_ACCESS`; the
full Onyx PRD remains incomplete.

## Phase 7 Workspace Memory V1 E1-E5 candidate (E6 pending)

The first Phase 7 slice adds a default-off `WorkspaceMemoryAdapterV1` over the
existing `MemoryStore` and accepted workspace sidecar. It resolves signed
workspace/principal/sensitivity/validity/freshness metadata before opening the
legacy database read-only and fetching only authorized IDs. E6 is pending, so
the slice is not accepted or live.

| Capability | Before | Candidate after | Exact evidence | Limitation | Owner | Next action |
|---|---|---|---|---|---|---|
| Workspace-scoped memory retrieval | `NOT_IMPLEMENTED` | `PARTIAL` | `core/phase7_workspace_memory_v1.py`; `tests/test_phase7_workspace_memory_v1.py`; accepted Phase 6 exit root | Default-off candidate only; approved existing MemoryStore records require signed sidecar metadata; no live startup/voice/UI wiring | Memory/Security | Freeze V1, reproduce zero-leak/read-only regressions, and obtain independent E6 |
| Layered institutional/decision/status memory | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` | Phase 7 V1 explicitly excludes new authoritative write layers | V1 is read-only retrieval only; candidate/promotion/supersession/contradiction writers remain absent | Memory/Company Knowledge Operator | Add typed sidecar layers only after V1 acceptance |
| Company Graph | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` | No graph candidate in this slice | Approved-source registry, entity/edge provenance, contradiction and freshness graph are not yet implemented | Company Knowledge Operator | Build the read-only graph over accepted workspace memory and approved sources |
| Founder Brief/portfolio command | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` | No Founder Brief candidate in this slice | No sourced portfolio projection exists yet | Executive Operator | Build after Company Graph and freshness/contradiction gates |

## Phase 7 Workspace Memory V1 accepted default-off checkpoint

External acceptance `VE-P7-WORKSPACE-MEMORY-V1-E6-001` binds candidate
manifest
`59ed88abd6967a73f3050d1215fed0c278b21b5c6e5335814abe8267576c9cd7`
and artifact root
`fafe2c2fb2c0d0f55f0ce6fc6824b71a93c42f3527565449986e90ba1fb09f95`.
The independent selection passed 77 tests and 73 subtests with zero failures
or errors; the only skip is the documented Windows absence of POSIX FIFO
creation.

Workspace-scoped pre-ranking memory retrieval is accepted as `PARTIAL`,
default-off and read-only. It remains unwired. Layered authoritative writes,
aliases, approved-source registry, Company Graph and Founder Brief remain
unimplemented; Phase 7 is not exited.

## Phase 7 Workspace Aliases V1 E1-E5 candidate (E6 pending)

The second ordered Phase 7 slice adds signed credential, browser-profile and
artifact aliases to the existing workspace sidecar. Each catalog instance is
sealed to one active non-legacy workspace and principal. E6 is pending, so the
slice remains default-off, unwired and non-authoritative outside its local
descriptor lifecycle.

| Capability | Before | Candidate after | Exact evidence | Limitation | Owner | Next action |
|---|---|---|---|---|---|---|
| Workspace credential aliases | `NOT_IMPLEMENTED` | `PARTIAL` | `core/phase7_workspace_aliases_v1.py`; focused and credential regressions | Stores only signed provider/account/scope and OS-vault locator identities; never resolves or stores a secret | Security/Capability Nexus | Freeze the candidate and obtain independent E6 |
| Workspace browser-profile aliases | `NOT_IMPLEMENTED` | `PARTIAL` | Logical locator and domain-policy tests in the candidate | No filesystem profile path, cookies, password store or browser launch; live browser binding remains later work | Browser Operator/Security | Bind only through a separately governed workspace-profile resolver |
| Workspace artifact aliases | `NOT_IMPLEMENTED` | `PARTIAL` | Exact `artifact_index` binding and artifact regressions | No artifact bytes are read; every returned alias reattests authoritative status and digest | Artifact Service/Security | Obtain E6, then allow approved-source records to reference aliases |
| Approved-source registry | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` | Explicitly excluded from this candidate | No source admission, rights, freshness or injection policy exists yet | Company Knowledge Operator | Implement next over accepted workspace memory and aliases |
| Company Graph | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` | Explicitly excluded from this candidate | No entity/edge/claim projection exists yet | Company Knowledge Operator | Build after approved-source acceptance |
| Founder Brief | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` | Explicitly excluded from this candidate | Requires sourced graph plus contradiction/freshness | Executive Operator | Build after graph gates |

## Phase 7 Workspace Aliases V1 accepted default-off checkpoint

External acceptance `VE-P7-WORKSPACE-ALIASES-V1-E6-001` binds candidate
manifest
`ec1938f4b1671187ed8384f104bb6082b0bd75d157cf4c8f12e259beb5612ca4`
and artifact root
`1ae29f0e8300b19737f61e795ea867f474d5dc7efd803a5a6bbaef4e74f2362e`.
The independent gate twice reproduced 160 tests and 113 subtests with zero
failures or errors; nine Windows skips are limited to documented POSIX-only
contracts.

Credential, browser-profile and artifact aliases are accepted as `PARTIAL`,
default-off workspace/principal locator metadata. The acceptance adds no
secret storage/resolution, browser launch, artifact byte read, runtime
authority or live wiring. Approved-source registry, Company Graph,
contradiction/freshness and Founder Brief remain unimplemented; Phase 7 is not
exited.

## Phase 7 Approved Sources + Company Graph V1 E1-E5 candidate (E6 pending)

The third and fourth ordered Phase 7 slices add signed source admission and a
read-only, source-grounded Company Graph. Both components remain exactly
default-off and unwired. E6 is pending, so this section records candidate
implementation evidence rather than acceptance or live capability.

| Capability | Before | Candidate after | Exact evidence | Limitation | Owner | Next action |
|---|---|---|---|---|---|---|
| Approved-source registry | `NOT_IMPLEMENTED` | `PARTIAL` | `core/phase7_approved_sources_v1.py`; focused and cumulative tests | Policy metadata only; HTTPS locators are never fetched and artifact bytes are never read | Company Knowledge Operator/Security | Freeze and obtain independent E6 |
| Source rights, quality and freshness | `NOT_IMPLEMENTED` | `PARTIAL` | Signed source records with eight scores, rights, sensitivity, validity and freshness | No automated retrieval/ranking loop or provider source ingestion | Intelligence Operator/Verifier | Add only through a later governed retrieval pipeline |
| Read-only Company Graph | `NOT_IMPLEMENTED` | `PARTIAL` | `core/phase7_company_graph_v1.py`; typed projection and adversarial tests | Caller supplies exact ledger-bound assertions; graph persists nothing and has no live wiring | Company Knowledge Operator | Freeze and obtain independent E6 |
| Declared contradictions and supersessions | `NOT_IMPLEMENTED` | `PARTIAL` | Hidden-reference denial and explicit relationship tests | Declared ledger relationships only; automatic contradiction discovery remains absent | Verifier | Implement freshness/contradiction analysis next |
| Verified completion status | `NOT_IMPLEMENTED` | `PARTIAL` | Supported authoritative verification + DoD + no-blocker gate | Project graph status only; never execution authority or proof of full PRD completion | Verifier/Security | Preserve fail-closed semantics in Founder Brief |
| Founder Brief | `NOT_IMPLEMENTED` | `NOT_IMPLEMENTED` | Explicitly excluded | Requires accepted graph plus contradiction/freshness analysis | Executive Operator | Implement after this E6 gate |

## Phase 7 Approved Sources + Company Graph V1 accepted checkpoint

External acceptance
`VE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001` binds candidate manifest
`fa5fea91caf6914e559cbc22420841b602eeace0153653dc57591fb0070f23f3`
and artifact root
`d9efc2186412abbf95a1cd03b901c5f797bcb7c50e6b3a6d256211dd2eeac1c3`.
The candidate and acceptance gates each reproduced 154 tests and 65 subtests
with zero failures or errors. Eight Windows skips are limited to documented
POSIX-only contracts.

Approved-source policy and the read-only Company Graph are accepted as
`PARTIAL`, exactly default-off and unwired. The acceptance adds no URL fetch,
artifact-content read, graph write, provider/network/process/browser call,
startup seam or runtime authority. Automatic contradiction discovery,
portfolio freshness alerts and Founder Brief remain unimplemented; Phase 7 is
not exited and the full Onyx PRD remains incomplete.

## Phase 7 Founder Command V1 E1-E5 candidate (E6 pending)

This ordered slice generates deterministic cited daily and weekly executive
projections over the accepted Company Graph. It remains exactly default-off,
read-only and unwired. E6 is pending.

| Capability | Before | Candidate after | Exact evidence | Limitation | Owner | Next action |
|---|---|---|---|---|---|---|
| Daily Founder Brief | `NOT_IMPLEMENTED` | `PARTIAL` | `core/phase7_founder_command_v1.py`; focused/cumulative tests | No scheduler, UI or live command wiring | Executive Operator | Freeze and obtain independent E6 |
| Weekly operating review | `NOT_IMPLEMENTED` | `PARTIAL` | Shared cited cadence and portfolio tests | No persisted longitudinal trend store | Executive Operator | Preserve as a read-only cadence |
| Portfolio/blocker/dependency/decision/risk views | `NOT_IMPLEMENTED` | `PARTIAL` | Typed claim queues and portfolio projection | Current supplied graph assertion set only | Executive Operator/Verifier | Bind later to governed intake |
| Freshness analysis | `NOT_IMPLEMENTED` | `PARTIAL` | Per-semantic current/aging/stale policy and tests | Does not autonomously refresh a source | Intelligence Operator | Add separately governed refresh intake |
| Structured contradiction detection | declared only | `PARTIAL` | Declared conflict preservation and incompatible-status tests | Same-subject structured states only | Verifier | Preserve conflicts and never overwrite silently |
| General NLP contradiction discovery | absent | absent | Explicitly excluded | Open-text semantic analysis is not implemented | Verifier | Build only with grounded evals in a later slice |
| Revenue opportunity queue | `NOT_IMPLEMENTED` | `PARTIAL` | Evidence-linked candidate and explicit-abstention tests | No revenue/customer/traction inference; intake remains later | Revenue Operator/Verifier | Add governed source-grounded intake |
| Recommended top three actions | `NOT_IMPLEMENTED` | `PARTIAL` | Impact/urgency/confidence/effort/downside ranking | Recommendation only; no execution authority | Executive Operator | Surface only after E6 and a separate UI/live gate |
| “What changed” delta | `NOT_IMPLEMENTED` | `PARTIAL` | Prior-brief authentication and exact delta tests | Requires an exact prior V1 brief | Executive Operator | Preserve brief digest in later scheduler |

## Phase 7 Founder Command V1 accepted checkpoint

External acceptance `VE-P7-FOUNDER-COMMAND-V1-E6-001` binds candidate
manifest
`b094e18b99342465e06cdc703b3a7db118ffe9fe3e3182171be61be06f63457e`
and artifact root
`d636a5192224a48a0ef09038d0cfc4e805b16798c1857d7735b9f27748e0e633`.
The candidate and acceptance gates each reproduced 168 tests and 65 subtests
with zero failures or errors. Eight Windows skips are documented POSIX-only
contracts.

Daily/weekly Founder Command projections, portfolio queues, semantic freshness,
structured status-conflict detection, evidence-linked revenue opportunities,
top-three recommendation ranking and prior-brief delta are accepted as
`PARTIAL`, exactly default-off, read-only and unwired. The acceptance adds no
persistence, source fetch, model, provider, network/process/browser, action,
scheduler, UI or live authority. General open-text/NLP contradiction
discovery remains absent. Phase 7 is not exited and the full Onyx PRD remains
incomplete.

## Phase 7 Layered Memory V1 E1-E5 candidate (E6 pending)

This ordered slice extends the accepted read-only Workspace Memory foundation
with a signed, typed lifecycle catalog for all seven PRD memory layers. It
remains exactly default-off and unwired. E6 is pending in the frozen candidate
record.

| Capability | Before | Candidate after | Exact evidence | Limitation | Owner | Next action |
|---|---|---|---|---|---|---|
| Seven typed memory layers | legacy semantic/episodic retrieval only | `PARTIAL` | `core/phase7_layered_memory_v1.py`; focused/cumulative tests | Explicit typed intake; no general NLP entity extraction | Memory/Company Knowledge Operator | Preserve candidate bytes and obtain E6 |
| Deduplication and entity resolution | `NOT_IMPLEMENTED` | `PARTIAL` | normalized content-addressed IDs and explicit relation tests | Competing live values must declare correction, supersession or contradiction | Memory/Verifier | Bind later to governed document intake |
| Correction/supersession/contradiction | graph declarations only | `PARTIAL` | atomic lifecycle and preserved-link tests | Memory relations are explicit, not inferred from open text | Memory/Verifier | Add grounded extraction only after ingestion gates |
| Freshness, validity and retention | workspace retrieval sidecar only | `PARTIAL` | pre-ranking filter and retention tests | No autonomous source refresh | Intelligence Operator/Memory | Connect later to approved-source refresh |
| Export, principal deletion and source deletion | `NOT_IMPLEMENTED` | `PARTIAL` | deterministic export and signed tombstone tests | Deletion retains non-content hashes for audit continuity | Security/Memory | Preserve privacy and audit policy |
| Poisoning defenses | untrusted marker | `PARTIAL` | injection-signal, secret-rejection and inert-authority tests | Signals do not claim general malicious-document classification | Security/Verifier | Extend in document-ingestion slice |
| Accepted Workspace Memory compatibility | accepted read-only adapter | unchanged | mixed-sidecar integration test and frozen predecessor hash | Successor is not wired to the legacy adapter | Memory/Security | Keep namespaces separate |
| Global vector index | absent | absent | explicit source/verifier invariant | No global post-filtered retrieval is allowed | Security | Retain hard prefilters |
| Live wiring | absent | absent | startup-surface scan | No startup, voice, UI or dashboard seam | Onyx Core | Wire only after Phase 7 aggregate exit |

## Phase 7 Layered Memory V1 accepted checkpoint

External acceptance `VE-P7-LAYERED-MEMORY-V1-E6-001` binds candidate manifest
`2818c6ffe66681436286d89f557c57cd23c35c29ee7f29d53d7eb2bf9d8ec95d`
and artifact root
`96218afa17936918aaed3bc4f225db3fee0eb117fa4e94f9439d93d1f6ed1020`.
The candidate and acceptance gates each reproduced 161 tests and 77 subtests
with zero failures or errors. One Windows skip is the documented POSIX-only
mode assertion.

Seven typed layers, workspace/principal isolation, normalized deduplication,
explicit entity resolution, correction/supersession/contradiction lifecycle,
freshness/validity, retention, scoped export, principal/source deletion and
poisoning defenses are accepted as `PARTIAL`, exactly default-off and unwired.
The accepted Workspace Memory implementation remains unchanged. The acceptance
adds no global vector index, network/process/provider/model/browser/action,
startup, UI or live authority. General NLP entity extraction and governed
multi-format document ingestion remain absent. Phase 7 is not exited and the
full Onyx PRD remains incomplete.

## Phase 7 Document Ingestion V1 accepted checkpoint

External acceptance `VE-P7-DOCUMENT-INGESTION-V1-E6-001` binds candidate
manifest
`20efa9f6125d881eab60e4edbd04d103196608cd26875634af06ee47793b8a03`
and artifact root
`8b7749f3228667eb15e66011129549b569caf9adbdd079a50368ae0967b8a513`.
The candidate and acceptance gates each reproduced 178 tests and 77 subtests
with zero failures or errors and one documented POSIX-only Windows skip.

PDF, DOCX, Markdown/text, spreadsheet, presentation, image/OCR and code
ingestion; granular citations; cited version comparison; deterministic
requirement/decision extraction; render/visual QA; malicious-container defense;
workspace isolation and source revocation are accepted as `PARTIAL`, exactly
default-off, read-only and unwired. Extracted memory records remain candidates
and are not persisted automatically. This acceptance adds no URL fetch,
network/process/provider/model/browser/action or live authority. Phase 7
aggregate exit remains pending and the full Onyx PRD remains incomplete.

## Phase 7 E6 accepted default-off implementation exit

External acceptance `VE-P7-EXIT-CANDIDATE-V1-E6-001` binds candidate manifest
`19cb98bb51a14617538aafb9c1f17cb52818e78991b51269ee3b0f126db505e4`,
artifact root
`0512b1af1ea38392ca62b37933404119c80b173a3d6e8e059d0e0f5418a7bfcb`
and 24 independently accepted component roots. The aggregate candidate and
acceptance gates each reproduced 240 tests and 80 subtests with zero failures
or errors. Eight Windows skips are documented POSIX-only contracts.

Phase 7 is accepted for default-off implementation completion. Phase 8 may
begin. This decision does not live-wire Phase 7 components, add runtime/action
authority or claim the full Onyx PRD complete.

## Phase 8 Microsoft Graph Read V1 accepted checkpoint

External acceptance `VE-P8-MICROSOFT-GRAPH-READ-V1-E6-001` binds candidate
manifest
`91a97a56729e396b84da60d30db5d33d71c8e315343d544792e7183d436dc261`
and artifact root
`abb152e611e1b58adc55b88207497d64188ad9485d2b6a32ada5f8c364528291`.
The candidate and acceptance gates each reproduced 264 tests and 80 subtests
with zero failures or errors. Eight skips are inherited accepted
platform-specific Phase 7 checks.

Microsoft Graph v1.0 calendar read, normalized daily briefing, mail metadata
search, body-scope-aware message read and local immutable event/email drafts
are accepted as `PARTIAL`, exactly default-off and unwired. The adapter is
workspace/principal/account/scope bound, enforces rotation/revocation and only
accepts provider paging on the exact Graph origin and route.

The accepted transport contract exposes GET only. It adds no OAuth onboarding,
live HTTP, provider-side draft, event creation/invitation/cancellation,
shared-calendar mutation, mail send/update/delete, task/notification or
Drive/OneDrive/Office authority. Phase 8 aggregate exit and the full Onyx PRD
remain incomplete.

## Phase 8 Microsoft Graph OAuth V1 accepted checkpoint

External acceptance `VE-P8-MICROSOFT-GRAPH-OAUTH-V1-E6-001` binds candidate
manifest
`81dbaba8991478737c7000519281d8c1924a3522aec40b62e3a635bcde3d2b65`
and artifact root
`9ae6f034f530a6e8353dfccbcf675760d2746684cf1a840da94adab326bf824d`.
The candidate gate reproduced 304 tests and 80 subtests with zero failures or
errors. Eight skips are inherited accepted platform-specific Phase 7 checks.

Delegated device authorization, exact read-only scopes, signed-in account
verification, native-vault refresh-token lifecycle/rotation and GET-only bearer
composition are accepted as `PARTIAL`, exactly default-off and unwired. Device
sessions are one-shot after token endpoint success, and refresh failure reports
disconnected state without destructively deleting the vault credential.

This acceptance does not provision an Entra application/client ID, consent or
test account and does not prove live identity/Graph E2E. It adds no provider
mutation, startup/voice/UI/dashboard wiring or Phase 8 aggregate exit. The
process-local access-token design cannot guarantee an in-place wipe of
immutable Python strings.

## Phase 8 Microsoft Graph Live Read E2E V1 accepted checkpoint

External acceptance `VE-P8-MICROSOFT-GRAPH-LIVE-READ-E2E-V1-E6-001` binds
candidate manifest
`63e2ff3a059aeb1c856ca73ad80ac523aac99aa33162fc200ce0fee47dcdc104`
and artifact root
`30bdd9e3bf1bde4effa1acb7147fcd714d763c6fcc017e6b23fe189fcfabef6b`.
The candidate gate reproduced 337 tests and 80 subtests with zero failures or
errors across fifteen fresh processes. Eight skips are inherited accepted
platform-specific Phase 7 checks. The first functional review returned three
P2 findings; all were fixed, covered by new adversarial tests and
independently re-confirmed closed before this decision.

Secret-free Microsoft Entra public-client onboarding with fail-closed
rejection of credential-shaped environment variables, exact `429 Retry-After`
honoring (including RFC 9110 zero-delay) with deterministic bounded backoff
and a typed retry bound, redacted transport observations, the six-probe live
E2E harness over the frozen OAuth V1 and Read V1 contracts, exact-type sealing
of the `live` probe mode to the real HTTPS transport, the hash-bound redacted
report with explicit `probes_missing`, and the operator evidence runner are
accepted as `PARTIAL`, exactly default-off and unwired.

This acceptance does not provision an Entra application/client ID, tenant
consent or test account: live identity/Graph E2E remains `BLOCKED_BY_ACCESS`
with the exact owner onboarding steps in
`docs/onyx/PHASE8_MICROSOFT_GRAPH_LIVE_ONBOARDING.md`. Provider failure and
real throttling behavior are contract-proven only, and live reports must list
unexecuted probes instead of claiming them. The acceptance adds no provider
mutation, task/notification/Drive/Office authority, startup/voice/UI/dashboard
wiring, Phase 8 aggregate exit or full Onyx PRD completion.

## Phase 8 first live read run and device-bootstrap corrective delta

Live evidence `VE-P8-GRAPH-LIVE-READ-RUN-001` (2026-07-23/24) upgrades the
truth of the Microsoft calendar/mail read connectors from contract-only to
point-in-time live-verified reads: an authorized Entra public-client
registration exists (`Onyx by Cyryx Labs`), tenant admin consent is granted
for the four delegated read scopes, and the accepted live-E2E runner passed
`sign_in_read`, `access_expiry_refresh` and `refresh_rotation` in `mode=live`
against the real provider using the owner account as interim test identity.
The connectors remain `WORKING_WITH_LIMITATIONS` at best for live reads and
stay default-off/unwired: revocation was not exercised live in this run,
provider failure and throttling remain contract-proven only, no dedicated
licensed test account exists yet, and no mutation, task, notification or
Drive/Office authority was added.

The run also discovered and recorded a frozen-predecessor defect (OAuth V1
device-verification host allowlist rejects the provider's current
`login.microsoft.com` host). The corrective versioned successor
`core/phase8_microsoft_graph_device_bootstrap_v2.py` (default-off
`ONYX_PHASE8_MS_GRAPH_DEVICE_BOOTSTRAP_V2`, eight passing focused tests,
ADR-0039) performs only the corrected device sign-in and native-vault priming;
all frozen bytes remain untouched and a future OAuth successor must absorb the
corrected allowlist.

## Phase 8 Microsoft Graph Calendar V1 accepted checkpoint

External acceptance `VE-P8-MICROSOFT-GRAPH-CALENDAR-V1-E6-001` binds candidate
manifest
`e28bf370f81ac991d4a384d02783aa809d6afc59a5036f75852679679a5962e4`
and artifact root
`4f0e1e3ae48a77f3c113a5ade1bb6e7e5f770bcbe9617ca8389edfce85029c3a`.
The candidate gate reproduced 363 tests and 80 subtests with zero failures or
errors across seventeen fresh processes. Eight skips are inherited accepted
platform-specific Phase 7 checks. The first functional review returned six P3
findings; the two high-value ones were fixed, covered by new adversarial tests
and independently re-confirmed closed before this decision.

The first Phase 8 provider mutation is accepted as `PARTIAL`, exactly
default-off and unwired: deterministic UTC conflict/availability computation
over the frozen read contract, and single-event creation gated by an
HMAC-signed, length-prefixed, expiring, one-shot grant bound to the exact draft
digest/workspace/principal/account, with write-scope acquisition, a typed
receipt, read-back reconciliation, honest unreconciled reporting,
reconcile-before-retry on uncertain outcomes and no auto-retry on 429. Attendee
drafts are denied at issuance and creation.

This acceptance does not prove live mutation E2E: it requires the Entra app to
carry delegated `Calendars.ReadWrite` consent and an explicitly confirmed run.
It adds no recurring events, update, delete, cancellation, shared-calendar,
invitation, mail send, task/notification or Drive/Office authority; no
startup/voice/UI/dashboard wiring; no Phase 8 aggregate exit and no full Onyx
PRD completion. The signing `integrity_key` must be scoped per
(workspace, principal), as recorded in ADR-0040.

## Phase 8 Microsoft Graph Mail V1 accepted checkpoint

External acceptance `VE-P8-MICROSOFT-GRAPH-MAIL-V1-E6-001` binds candidate
manifest
`98f9cc7c75cf496275ab326af352d3332cd8f604b702c8047f405df264034acf`
and artifact root
`73875e708fbd9684cddec51fb34cb327b958c7e851f5035f37cbce9540cf30f0`.
The candidate gate reproduced 381 tests and 80 subtests with zero failures or
errors across eighteen fresh processes. Eight skips are inherited accepted
platform-specific Phase 7 checks. The first functional review returned one P1
(cross-session grant replay → duplicate send) and one P2 (draft content not
verified); both were fixed, covered by new adversarial tests and independently
re-confirmed closed before this decision.

Mail draft/send is accepted as `PARTIAL`, exactly default-off and unwired: an
HMAC-signed, expiring, one-shot grant bound to the exact draft digest,
recipient/cc audience and account; a send path that recomputes the draft
content digest (no substituted subject/body/audience); write-scope acquisition;
a reconcilable two-step send capturing `internetMessageId` with Sent Items
reconciliation; and uncertain-outcome reconcile-before-resend with no send
auto-retry on 429. Reply, forward, delete and attachments are denied.

This acceptance does not prove live send E2E: it requires the Entra app to
carry delegated `Mail.ReadWrite` and `Mail.Send` consent and an explicitly
confirmed live send. Cross-session, cross-restart one-shot replay protection
requires the host to inject a durable, atomic nonce ledger (the in-memory
default protects only within one session; see ADR-0041). It adds no
reply/forward/delete/folder/shared-mailbox/attachment authority, no
startup/voice/UI/dashboard wiring, no Phase 8 aggregate exit and no full Onyx
PRD completion.

## Phase 8 Microsoft Graph Tasks V1 accepted checkpoint

External acceptance `VE-P8-MICROSOFT-GRAPH-TASKS-V1-E6-001` binds candidate
manifest
`44337ca6fdd348cd8ff7010d8ffeeb6fd6bc3167b4b80f0e3a08888b1bc859a8`
and artifact root
`984f32cf236bac4b9ef1c4ad0a63bcf9a1384c19a0fdc8feae5720d0334f6508`.
The candidate gate reproduced 403 tests and 80 subtests with zero failures or
errors across nineteen fresh processes. Eight skips are inherited accepted
platform-specific Phase 7 checks. All three independent reviews returned PASS
on the first pass.

Tasks and notifications are accepted as `PARTIAL`, exactly default-off and
unwired: a pure deterministic notification router (urgency, midnight-wrapping
quiet hours, workspace/device → deliver/defer/suppress) and a Microsoft To Do
task create gated by an HMAC one-shot content-and-list-bound grant consumed
through an injected nonce ledger before mutation, with write-scope acquisition,
a reconcilable create and read-back reconciliation, and uncertain-outcome
reconcile-before-retry with no auto-retry on 429.

This acceptance does not prove live task-create E2E: it requires the Entra app
to carry delegated `Tasks.ReadWrite` consent and an explicitly confirmed run,
and cross-session one-shot protection requires a durable injected nonce ledger.
It adds no task update/delete/complete, list mutation, provider push, reminder
transport, calendar/mail authority beyond accepted predecessors, no
startup/voice/UI/dashboard wiring, no Phase 8 aggregate exit and no full Onyx
PRD completion.

## Phase 8 Microsoft Graph OneDrive Read V1 accepted checkpoint

External acceptance `VE-P8-MICROSOFT-GRAPH-DRIVE-V1-E6-001` binds candidate
manifest
`3ad944de2b85de78e343f0cbee0556644218ec7d7039b93efe9daffe774758b5`
and artifact root
`c79ee2960fdf3c74f4ec33cb693cd328a79bfa5547a8e74d2033603f9f0a6c21`.
The candidate gate reproduced 421 tests and 80 subtests with zero failures or
errors across twenty fresh processes. Eight skips are inherited accepted
platform-specific Phase 7 checks. Integrity returned PASS on the first pass;
functional and quality returned PASS-WITH-CONCERNS whose every actionable
finding (folder+file facet conflict and missing-identity denial, dead constant
removal, and six added regression tests for the paging bounds, get-item
collection guard, token refetch/rotation and cross-route nextLink branches) was
remediated and re-verified. Final findings: 0 P0 / 0 P1 / 0 P2 / 1 P3 advisory.

OneDrive/Office document access advances from `BLOCKED_BY_ACCESS` to `PARTIAL`,
exactly default-off and unwired: delegated `Files.Read` token acquisition with
exact granted-scope validation and best-effort rotation, route-pinned GET
listing of the drive root, a folder's children and a single item's metadata,
bounded same-origin `@odata.nextLink` paging, and normalized `DriveItemV1`
records with strict provider shape-drift denial. The redirect-disabled,
origin-pinned client makes `/content` download and every mutation verb
structurally unreachable.

This acceptance does not prove live listing E2E: it requires the Entra app to
carry delegated `Files.Read` consent and an explicitly confirmed run. It is
metadata only — no content bytes, no content download, no SharePoint
document-library enumeration, no upload/rename/move/delete/share, no
startup/voice/UI/dashboard wiring, no Phase 8 aggregate exit and no full Onyx
PRD completion.

## Phase 8 connector-layer exit accepted checkpoint

External acceptance `VE-P8-EXIT-CANDIDATE-V1-E6-001` binds candidate manifest
`8b23754d1d0cbc6f5ec613a5b454ed66cb933cd007fb0c4524f8d92cd8bdfd46`
and artifact root
`114cba2de27b680848ed5bfe6ddba7e0033c6448d6f85d198689aa8cffc1485a`.
The aggregate verifier pins twenty-eight immutable accepted-component roots
(seven four-file acceptance tuples for OAuth, Read, Live Read E2E, Calendar,
Mail, Tasks and OneDrive Read V1), machine-enforces the requirement→evidence
mapping, and reproduced 421 tests plus 80 subtests with zero failures/errors
across twenty fresh processes. Integrity returned PASS first pass; functional and
quality returned PASS-WITH-CONCERNS whose every finding was remediated (the
aggregate was rescoped to the default-off connector contract layer with all
live-run assertions removed, the completion boolean scoped, the requirement
mapping and claim flags machine-enforced, and the device-bootstrap exclusion
explained). Final findings: 0 P0 / 0 P1 / 0 P2 / 0 P3.

Phase 8 is accepted for **connector-layer default-off implementation
completion**; Phase 9 may begin. This binds no live execution: live read,
calendar create, mail send, task create and drive listing each still require
delegated consent plus an explicitly confirmed run. It covers no PRD
daily-operations behaviours (inbox triage, deadlines/follow-ups, prep,
travel-aware scheduling, task/review cadence, meeting decision/action
reconciliation), live-wires no component, adds no action authority and does not
claim the full Onyx PRD complete.

## Operational Integration V14 / DayOps V1 local candidate

V14 is a versioned, reversible successor over the unchanged V13 activation.
It transactionally binds one read-only model-tool declaration, its permission
policy and controller. The existing host dispatcher owns the
`day_brief_read` branch after `authorize_model_tool`; V14 does not replace or
patch `_execute_tool`. The deferred canonical factory validates accepted
workspace and credential-alias bindings plus the actual native-vault refresh
token before OAuth restore or HTTP, then composes the accepted Phase 8 live
read transport and `MicrosoftGraphReadAdapterV1.daily_brief`. Missing
feature/configuration/binding/token state returns a bounded safe response with
zero HTTP calls. The result projection excludes provider IDs, links, account
identity and attendee addresses.

Focused DayOps/factory/V14 tests passed 19 tests. The proportional local
regression selection covering V13, DayOps/V14, Phase 6 Live Wiring and Phase 8
Graph Read/OAuth/Live Read passed 136 tests with one platform skip and one
pre-existing PySide disconnect warning. The canonical stable bootstrap selects
the versioned V14 bootstrap; its preflight installs and rolls back V14 while
proving canonical-factory configurability with zero provider/network calls.
V14 rollback removes its declaration, policy and controller binding, restores
the exact V13 environment and never replaces the host dispatcher.

This is not an E6 acceptance record and does not prove current Microsoft
availability, refresh-token validity, real-device audio behavior or a live
provider E2E. The capability remains `PARTIAL`; an explicitly authorized,
redacted live read and separate review are still pending.

## DayOps Planner V1 / Chief-of-Staff read-only candidate

`core/dayops_planner_v1.py` adds a deterministic, immutable projection over
the accepted `ExecutiveOfficeBriefV1` or the already-sanitized V1 DayOps
snapshot. Sanitized mappings are now accepted only when an exact canonical
SHA-256 binds every public event, message and coverage field. Provider IDs are
never projected: the live boundary emits domain-separated 64-hex `source_ref`
values, and only those opaque values may drive identity or deduplication.
Records without an accepted source reference remain distinct. It produces
bounded attention ordering with explicit reasons and full-digest opaque evidence
references, explicitly high-importance unread
metadata, timed-calendar overlaps, separate ongoing and next meetings, a
non-inverted 15-minute preparation window, structured timestamp mentions,
focus gaps, and explicit pagination/truncation/timezone/clock-skew disclosure.
Follow-up candidates and deadlines remain empty because the V1 provider shape
has neither explicit reply/follow-up metadata nor structured due dates. Provider strings remain
untrusted data: message bodies are not accepted by this contract, subjects are
not parsed as instructions or deadlines, and the result has no mutation,
permission, mission, provider, process, network or file authority.

`core/dayops_live_integration_v2.py` is an additive successor wrapper. The
planner is exact-value default-off and runs only with
`ONYX_DAYOPS_PLANNER_V1=true` (or the exact injected sealed gate). When off, or
when the V1 read does not complete, it returns the original V1 execution
object unchanged. V19 now constructs this wrapper around its accepted V1
integration, but the exact flag remains off by default and the off path returns
the original execution object unchanged. The accepted read-only brief now
carries its provider-content trust marker instead of the planner synthesizing it.

The current focused DayOps gate passes 47 tests, including the PySide6 UI in
the project virtual environment. The proportional DayOps, Phase 8 Graph Read /
Live Read and V19 activation regression passes 117 tests. Coverage includes a
real 25-hour fall-back day,
fold ordering, DST-gap rejection, all-day/ongoing/next-meeting behavior,
order-independent opaque-source merges, conservative id-less preservation,
canonical digest mutation rejection, exact Graph importance enums, explicit
UI truncation markers, future-clock/message exclusion, output truncation,
hostile provider fields, default-off identity preservation, catch-all redacted
planner failure, and V19 flag-on access. This is a local
`CANDIDATE`, not E6 or live-provider evidence. Microsoft Entra registration,
owner consent, an authorized current live read, complete pagination evidence,
and native package/live-account validation remain external acceptance requirements.

## Matrix governance

## Phase 5 historical-to-current successor transition

The immutable Phase 5 Exit manifests and their historical SHA-256 values remain
predecessor evidence; they are not rebound to the evolving working tree.  The
current closure is `PHASE5_CURRENT_SUCCESSOR_TRANSITION_V2`: it authenticates
the original retirement-record root, every one of its 18 historical bindings,
the current bytes that now occupy those paths, and all seven named successors.
Its independently framed current root therefore records the intentional
transition of the V19 activation, dashboard server, capability matrix,
packaging gates, and related current files without presenting those bytes as
the historical candidate.  Historical bytes are executable only when the
existing Git anchor reproduces their exact digest; unavailable tombstones stay
non-executable and delegate only to an authenticated named successor.

This is evidence maintenance, not a capability promotion or release pass.  It
changes no runtime flag, authority, provider, process, network, mission, or UI
wiring.  Future intentional changes to a bound current file require a new
versioned transition closure; editing an older historical digest remains
forbidden.

## Phase 11 host execution ledger local candidate

Phase 11 now has a default-off local candidate for host-owned execution
evidence. It uses canonical JSON, a domain-separated host subkey, HMAC-SHA256
chained immutable records, a signed tail checkpoint, and one fixed lock inside
the same descriptor/handle-bound trusted directory. Ledger, checkpoint and
lock reject links and multi-link files; updates flush file and directory. Every read
verifies the complete chain and its checkpoint; tampering, truncation, stale
suffix replay, binding drift, and invalid transition replay fail closed. The
optional executable-sandbox injection records intent immediately before a
dispatch reservation, verifies the completed sandbox receipt against its exact
mission/execution/image/argv/attempt binding, and stores the canonical receipt,
receipt digest, verdict, exit code and output/receipt HMACs. A fully verified
ledger ahead of its checkpoint repairs that crash window under lock. Every
reservation without a receipt remains `unknown`; attempt retry is refused
because V1 has no authenticated takeover/reapproval marker.

This remains a candidate, default-off capability. Focused local tests cover
round-trip, fake-receipt rejection, truncation/replay, cross-binding execution
replay, attempt gap/downgrade, crash-window repair, pre-write size limits,
process concurrency, divergent-lock refusal, link victims, disabled behavior,
and sandbox/live-V15 focused regressions. Live V15 wires the ledger only when
the executable boundary and host key exist; recovered-receipt reconciliation
accepts only the exact ledger-authenticated receipt and never infers
`proven_not_executed`. It does not
prove crash-safe recovery across every filesystem, protect against rollback of
both the ledger and its checkpoint by a host administrator, enable live
execution, or grant command, publication, deployment, or provider authority.

Row 112 successor clarification (2026-08-01): the ledger candidate is now
live-wired locally behind the complete executable boundary. The public
autopilot seam accepts only the exact official sandbox host, not a caller
factory, so its limited process adapter receives no signing key or ledger.
`recovered_receipt` accepts only the exact canonical receipt authenticated by
that ledger for the original mission/execution/attempt; missing or invalid
evidence stays `attempted_unknown` and never redispatches.
`proven_not_executed`, retry and takeover remain unavailable. No real-Docker
observation, rebuilt/installed package, external monotonic rollback anchor or
independent E6 is claimed.

1. The named owner is accountable for implementation evidence, not permission to self-authorize. Credentials, account enrollment, spending, publication, booking, licensing and high-risk operations remain Cyryx-owner decisions.
2. A capability changes status only with evidence proportionate to its scope: real auth when relevant, success/failure/cancel/retry/rate-limit behavior, security tests, observed final state and documented limitations. Every `WORKING_AND_VERIFIED` row must reference a current `VE-*` record in `VERIFICATION_EVIDENCE.md`.
3. `BLOCKED_BY_ACCESS` or `BLOCKED_BY_LICENSE` does not become working because a stub, browser fallback or design document exists.
4. Browser/UI fallback must remain separately labeled and cannot impersonate an official connector or provider receipt.
5. Every Phase 4+ implementation must update this matrix, retain the stable-core regression suite, add rollback evidence and avoid widening default authority.
