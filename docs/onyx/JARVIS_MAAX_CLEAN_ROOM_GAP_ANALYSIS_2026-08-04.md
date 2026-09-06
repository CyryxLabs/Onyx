# jarvis_MAAX → Onyx clean-room gap analysis — 2026-08-04

Status: **IMPLEMENTATION AND RELEASE INPUT — NOT A THIRD-PARTY CODE IMPORT**

## Independent correction — 2026-08-05

The repository domains were captured, but not every useful behavior is
implemented or live.  An independent source-to-runtime review rejected the
earlier broad reading of phrases such as "already present" where Onyx has only
an architectural foundation or a narrower governed substitute.

The remaining real product gaps are concrete background text provider clients,
an executable remote sidecar receiver/RPC, a deep visual workflow surface and
safe node catalog, governed site editing/preview/Git, Telegram, richer
goal/accountability and agent-roster UX, and native macOS/Linux accessibility
backends.  Microsoft Graph is operationally preferred for this owner's current
DayOps path; Gmail/Google Calendar remains an optional connector gap rather
than a claimed equivalent.

The reference's continuous screen/OCR, clipboard/process polling, arbitrary
shell/code/browser JavaScript, token-bearing URLs, WhatsApp and Signal stubs
remain deliberately excluded.  Exclusion is not an implementation gap when it
protects the accepted Onyx CPU, privacy, authority or license boundary.

At this correction point, pairing, official Discord messaging, site recipes,
portable accessibility and content lifecycle have source contracts and focused
tests but are not evidence of V24 live behavior.  They require a separately
reviewed additive activation, packaging closure and installed acceptance.

Subsequent source work on 2026-08-05 closed, at source-candidate level only,
the concrete network text-provider clients, bounded Device Mesh receiver,
Telegram outbox, Goal/Agent Operations projection and event-only analytics.
Each passed a separate independent acceptance after adversarial corrections.
They remain excluded from operational-completion claims until a successor
activation supplies exact current-owner account/key resolvers, packaging and
SBOM closure, clean build and exact-installed/real-provider or real-device
acceptance.  The visual workflow/site/native-host rows remain active work.

## Reference frozen

- Repository: `petruff/jarvis_MAAX.git`
- Exact reviewed commit: `564c97b2cf8ad29983b3ad40411441dbc9e22af3`
- Local read-only reference checkout: `C:/MAAX_Assistant/.reference/jarvis_MAAX`
- Scope reviewed: 491 tracked files, README/architecture guides, TypeScript
  services, Go sidecar contracts, UI surfaces and tests.
- License boundary: the reference uses Jarvis Source Available License 2.0,
  based on RSALv2, with third-party/service-use restrictions. No source,
  branding, notice text, package or license was copied into Onyx. Only public
  behavior concepts were compared, and every implementation below is original
  Python/QML following Onyx authorities.

The reference does not provide a clean Windows-native baseline: its frozen Bun
install rejects the native Windows daemon path, while the Windows test run
recorded 417 passes, 5 failures and 2 errors. Several advertised integrations
are documented placeholders or stubs. A README statement is therefore not
treated as operational evidence.

## Capability result

| Reference behavior | Onyx result | Decision/evidence boundary |
|---|---|---|
| Always-on conversational daemon | Already present, stronger voice contract | Gemini Native Audio + Charon, microphone/playback single ownership and fail-closed prohibition of system TTS remain unchanged |
| Tool execution and desktop work | Already present | Existing Onyx actions, browser, files, developer actions, MissionStore and Phase 6 remain the only execution path |
| Durable memory and knowledge | Already present | Local MemoryStore, workspace memory, seven-layer memory and Company Graph already exceed the reference's flat extractor; durable writes remain explicit/approved rather than silently extracting every conversation |
| Goals and proactive operation | Already present | Operational goals, evidence-based reconciliation, daily rhythm, proactive mode and Project Autopilot are retained |
| Multi-agent research and verification | Already present | Phase 6 plans, provider-free Research Cell, Independent Verifier, unified command router and governed external-agent boundary remain authoritative |
| Visual/event workflow graphs | **Implemented in this successor** | Original clean-room `WorkflowGraphStoreV1`, voice tool actions and HUD projection; event trigger arms the existing Governed Automation runtime and Phase 6; completion requires verified receipts |
| Continuous context graph | **Implemented in this successor** | Original metadata-only durable application↔project graph fed by accepted native events; owner/workspace isolation, hash-chained observations, zero timers/workers/polling |
| Screen OCR every 5–10 seconds | Deliberately not ported | Conflicts with the owner's CPU requirement and Onyx privacy boundary. The architecture uses native metadata events; screen/camera inspection remains explicit and owner-invoked |
| Struggle detection | Partially represented safely | High context-switching, overdue goals, paused goals, calendar/mail/connectivity attention are event-derived; content-based screen inference remains excluded until an explicit low-cost permissioned capture exists |
| Sidecar/device mesh | Foundation already present | Enrollment, OS-vault credentials, signed/replay-resistant requests, inbound verification, central authority and pinned TLS 1.3 outbound transport exist. Real second-device provisioning and receiver acceptance require the actual target device |
| Remote phone interface | Already present | Authenticated TLS dashboard, persistent device pairing, commands, audio relay, uploads and WebSocket tickets already exist and replace the reference's generic web sidecar for the phone use case |
| Multi-provider model routing | Already present with a stricter voice boundary | Provider registry, health/fallback route planning and Ollama/OpenAI-compatible local text seam exist. They may support background text work but never replace or silently fall back from Gemini Native Audio voice |
| Wake word | Not applicable to the current live topology | Onyx already owns a continuously connected microphone with Gemini automatic VAD. A second OpenWakeWord microphone consumer would duplicate audio ownership, add CPU and risk the accepted natural-voice path |
| Sites/publishing | Already present with governed execution | Site project metadata, build/preview/publish bindings and Project Autopilot exist; external publication remains receipt- and authority-bound |
| Email/calendar/inbox workflows | Implemented foundation; live access is external | Microsoft Graph OAuth/mail/calendar/tasks/drive readers and DayOps exist. Live completion depends on owner account consent and provider credentials |
| WhatsApp/Discord/Signal channels | No stub imported | The reference documents incomplete/stub paths. Onyx will add only official authenticated connectors with recipient scope and provider receipts |
| macOS/Linux host control | Packaged contracts exist; native proof remains external | Release scripts, launchd/systemd definitions and Linux diagnostic packaging exist. Native GUI/audio/accessibility/signing evidence requires native hosts and credentials |
| Plugin ecosystem | Already represented by governed capability discovery | Capability Nexus, MCP contracts and explicit adapters avoid importing untrusted runtime plugins directly |

## New workflow architecture

The workflow graph is intentionally not a second automation engine. A graph
contains one trigger, optional metadata conditions, one Phase 6 plan and one
verified output. Binding creates a disabled rule in the existing automation
store. Activation arms that rule; pause/cancel disarms it. A matching native
event enters the existing event queue and executes the exact approved Phase 6
mission. Reconciliation can mark the graph complete only after MissionStore and
AgenticStateStore agree on succeeded state, authority snapshot, verified
receipts and required postconditions.

The graph schema cannot represent shell, HTTP, subprocesses, provider calls,
credentials or arbitrary code. It has bounded nodes/edges/config, deterministic
topological order, cycle/disconnection rejection and a hash-chained lifecycle.

## New context architecture

The context graph persists only allowlisted identifiers such as application and
project IDs after the awareness policy has admitted an event. It derives an
`application active_in project` relationship, keeps current context across
restart and exposes bounded counts to the cinematic HUD. It does not store
screen pixels, clipboard, message bodies, transcripts, cookies, tokens or raw
process data. Idle CPU work is exactly zero.

## Remaining external gates, not missing source implementation

1. Real Microsoft account consent and live read-only Graph receipts.
2. Real second-device pairing/receiver test if a distributed sidecar is wanted.
3. Windows code-signing identity and clean-host lifecycle acceptance.
4. Apple Silicon build, audio/GUI/accessibility acceptance, Developer ID,
   notarization and Gatekeeper.
5. Native Linux x64/arm64 GUI/audio/autostart acceptance.
6. Owner acoustic confirmation of Charon and physical voice/name persistence.
7. Legal/third-party notices approval and independent final evidence review.

These gates cannot be truthfully manufactured from this Windows workstation.
They do not authorize replacement of the voice, Phase 6, permission broker,
memory authority or UI shell.

## Additive successor update — V23/V30 source, 2026-08-04

The comparison above now produced the following original Onyx additions. None
copies reference source, assets, names or notices:

- `core/owner_context_profile_v1.py`: durable owner/day-to-day context with
  bounded prompt projection and secret rejection.
- `core/operational_event_bridge_v1.py`: metadata-only calendar, mail,
  connectivity and mission events into the existing automation/awareness
  authorities, with no polling or captured message content.
- `core/device_pairing_v1.py`: one-time, expiring, attempt-limited pairing
  ceremony. Only a salted code hash is persisted; it issues no credential and
  grants no execution authority.
- `core/official_messaging_v1.py`: default-off Discord official API outbox with
  fixed account/channel scope, OS-vault credential reference, durable
  reservation before one provider call, mention suppression, idempotency nonce
  and exact provider receipt binding. Unknown outcomes enter reconciliation;
  there is no blind retry.
- `dashboard/server.py`: neutral `/pair` QR target. Credentials and one-time
  codes no longer appear in QR URLs, and the legacy `/auto-login?key=...` route
  is retired with HTTP 410.
- `packaging/windows/onyx.iss`: optional, unchecked, current-user Windows login
  start with automatic uninstall cleanup and no service/admin privilege.
- `core/site_recipe_catalog_v1.py`: three deterministic Cyryx site recipes
  that return a bounded, hash-bound Phase 6 file plan without writing files,
  starting processes, running package managers or accessing a network.
- `core/portable_accessibility_actions_v1.py`: exact-target macOS/Linux
  accessibility contract for focus, invoke, set-value and type-text. It has no
  shell, coordinates, arbitrary selector, script, retry or polling; a native
  adapter must return an exact postcondition receipt after central authority.
- `core/content_lifecycle_projection_v1.py`: owner/workspace-scoped scheduled,
  reserved, publishing, published, failed, reconciliation and cancelled
  projection. It retains only content digests and metadata, reserves before an
  external provider effect, and accepts completion only from an exactly bound
  provider receipt. It performs no provider or network call itself.

The six final clean-room additions above passed 28 focused source tests. They
must be bound into the successor release transition and rebuilt before they are
described as installed behavior.

The aligned Windows V30 package passed exact installed acceptance over 9,766
files and 11 packaged smokes, with a reconciled 112-distribution SBOM. The site
recipe, portable accessibility and content-lifecycle additions postdate that
artifact and therefore require the V31 successor rebuild. Discord still
requires an owner-supplied bot credential and approved channel IDs; physical
device-mesh enrollment still requires a real second device. macOS/Linux native
accessibility remains a host-specific acceptance gate, not an inferred result.
