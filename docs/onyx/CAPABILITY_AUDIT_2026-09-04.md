# Onyx functional capability audit — 2026-09-04

Target successor: V95 / 1.1.30  
Visual boundary: no change to the desktop/mobile layout, humanoid, palette, or voice behavior.

## Executive verdict

`CONCERNS` — the closed source registry and frozen package contain all 42
non-visual Mark-LI parity capabilities, but that is not equivalent to every
capability being operational against a real device, owner account, or external
provider. Local deterministic paths are exercised below. OAuth, account,
device, LAN, and provider effects remain separate live gates and are never
inferred from source files.

The immediate installed startup failure is real and reproduced. The active
Desktop shortcut contains the literal two-character argument `""`. Installed
1.1.29 rejects that shape in V24; V95 accepts only that exact sole semantic
empty argument (plus the already-supported decoded empty string), keeps every
mixed/unknown argument fail-closed, and fixes both shortcut producers: Setup
deletes the stale application-owned link before recreating it without
parameters, while the runtime no longer converts its empty frozen argument into
literal quotes.

## Fresh evidence

| Gate | Result | Boundary |
|---|---|---|
| Source parity registry | PASS — 42 capabilities, 100% source-contract coverage, zero missing evidence files | Does not prove package, install, device, OAuth, account, or provider behavior |
| Source capability smoke | PASS — 17 governed ports refused unauthorized dispatch; kill latch passed | Negative/default-off proof for high-impact ports |
| Source positive local smoke | PASS — 9 dispatched receipts across clipboard, personalization, plugin list, social draft/status, and wellness/repetition | No provider dispatch or publication |
| Installed 1.1.29 frozen parity | PASS — 42 capabilities and all frozen runtime module origins authenticated | Reports package verification only, not installed/live certification |
| Installed 1.1.29 positive local smoke | PASS — 9 dispatched receipts; five local families | External publishing correctly reports `oauth-adapter-required` |
| Shortcut/bootstrap correction | PASS — 34 current bootstrap, shortcut, installer and HUD-authority tests | Successor installation/live launch still required |
| Capability evidence suite (27 files) | PASS — 489 passed, 1 platform/precondition skip, 293 subtests passed | Exact source snapshot; does not manufacture device/account/provider receipts |
| Extended capability ring (38 files) | PASS — 708 passed, 4 platform/precondition skips | AEXOS, governed learning, opportunities, Google/Graph, social/video, mobile humanoid, latency and current HUD authorities |
| Google Windows durable witness | PASS — 94 passed, 3 platform skips; long-path creation/validation/removal repaired | Owner OAuth is still absent |
| Google authenticated activation chain | PASS — 50 passed against successor provenance and exact local closure | Default-off until explicitly configured and consented |
| Audio inventory | PASS — 2 input devices and 4 output devices enumerated; selected voice `Charon` | Enumeration is not a physical speak/listen round trip |
| FFmpeg | PASS — 7.1.1 available | Social provider upload still requires OAuth/account proof |
| Docker native plugin sandbox | BLOCKED — Docker client 29.7.2 present; daemon unavailable | No fresh native-container execution can be certified in this run |
| Google Workspace | SOURCE/HOST PASS; LIVE BLOCKED — `enabled=false`, `configured=false`, `connected=false` | Owner OAuth consent/configuration required |
| Microsoft Graph | BLOCKED — live runners require explicit owner-operated flags and delegated consent | No live mail/calendar receipt in this run |
| Public Windows distribution | BLOCKED — artifact is not Authenticode signed | Local installation is a candidate, not a public signed release |

## Complete 42-capability inventory

Every identifier below has source and test evidence in
`core/capability_parity_v1.py` and is required in the frozen package. The live
classification is the additional evidence still needed beyond automated tests.

### Local or provider-free behavior

1. `system_control`
2. `autonomous_tasks`
3. `persistent_memory`
4. `hybrid_input`
5. `proactive_checkins`
6. `session_memory`
7. `dynamic_content_panel`
8. `file_processor`
9. `desktop_control`
10. `silent_language_memory`
11. `clipboard_intelligence`
12. `assistant_customization`
13. `calorie_tracker`
14. `owner_memory_control`
15. `bounded_undo`
16. `owner_confirmation`
17. `local_action_resolution`
18. `unicode_safe_diagnostics`

These can be certified by deterministic local tests plus the installed host.
Desktop-control effects still depend on the current Windows foreground state,
so broad GUI automation is not inferred from unit tests.

### Physical device, OS service, LAN, or installed-application dependent

19. `visual_awareness` — screen/camera permission and owner consent
20. `hardware_monitoring` — host sensors
21. `smart_reminders` — OS scheduler
22. `game_updater` — installed game client
23. `browser_control` — installed browser and authenticated profile
24. `youtube_control` — YouTube/site/browser behavior
25. `remote_dashboard` — TLS, LAN, firewall, and paired device
26. `auto_start` — OS startup registration
27. `repetition_counter` — physical camera calibration
28. `audio_device_selection` — physical audio device

### Provider, model, sandbox, or owner-account dependent

29. `plugin_system` — certified native sandbox; presently blocked by stopped Docker daemon
30. `real_time_voice` — Gemini Live plus microphone/output device
31. `affective_dialog` — supported Gemini Live preview behavior
32. `proactive_audio` — supported Gemini Live preview behavior
33. `unlimited_sessions` — Gemini Live continuity
34. `morning_briefing` — live news provider
35. `background_monitoring` — live web search
36. `weather_report` — weather provider
37. `multi_mode_web_search` — live web providers
38. `flight_finder` — flight provider
39. `code_helper` — configured model/toolchain
40. `send_message` — authorized messaging account
41. `video_upload` — official provider OAuth and test account
42. `live_voice_selection` — Gemini Live session rotation

## Additional Onyx capabilities outside the 42-item parity registry

| Area | Current state | Evidence/limitation |
|---|---|---|
| AEXOS engine | AVAILABLE/ATTESTED | Bundled 5.3.0 adapter and exact artifact digests pass status inspection |
| Governed continuous learning | IMPLEMENTED/HOST-WIRED | Observes bounded conversation signals through the personalization store; it is not autonomous model-weight training |
| Owner onboarding/personalization | IMPLEMENTED/HOST-WIRED | Positive local status receipt passed; real owner interview completion is account/profile state |
| Opportunity research/economics/monitor | IMPLEMENTED/AUTOMATED-TESTED-PENDING-FINAL-RUN | Live value and citations depend on web/provider access |
| Microsoft Graph mail/calendar/drive/tasks | IMPLEMENTED/DEFAULT-OFF | Requires explicit Entra application configuration, delegated scopes, device-code owner sign-in, and live receipts |
| Google Gmail/Calendar | IMPLEMENTED/SOURCE-HOST-TESTED/DEFAULT-OFF | 94 host tests and 50 authenticated activation tests pass; current owner status is not configured or connected |
| Social captions/previews/video binding | IMPLEMENTED/LOCAL-PASS | Publication and reconciliation need an official adapter, OAuth, and a controlled account |
| Network Guardian | NOT IMPLEMENTED AS A SEPARATE GOVERNED SUBSYSTEM | Threat-model and dashboard controls exist, but there is no certified autonomous intrusion-detection/firewall-blocking service; documentation must not claim otherwise |

## Release decision

V95 may be installed locally after source, package, and installer gates pass. It
must remain non-publishable until Authenticode/legal release gates are satisfied.
Operational certification for external capabilities requires separate owner-run
device/account/provider receipts. No test may silently create calendar events,
send messages, publish social content, alter firewall policy, or grant OAuth
consent.

## QA infrastructure note

The project-wide historical `tests/conftest.py` runs nested successor suites
during collection and can consume several minutes before a selected test begins.
Two directly selected predecessor tests (HUD V45 and packaged HUD V14) also
correctly reject the current `ui.py` because those frozen authorities predate
the non-visual shortcut fix. V46/V15 are the current authorities and pass while
binding the same visual runtime bytes. A separate stale release-preparation test
still requires literal version `1.1.10`; it is historical and is not evidence
against the current 1.1.30 candidate.
