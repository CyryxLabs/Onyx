# Onyx expansion — evidence and operation guide

Date: 2026-09-05. Status: **partial source implementation, not installed**.
Installed V96 / 1.1.31 and its predecessor evidence have not been replaced.

## Exact upstream baseline

Compared against https://github.com/lkm-dot/FatihMakes-Mark-XLVIII at
`d178f6b9ee43e4e3d7edcc78b7df3e10f372fec2`, not the earlier Mark-LI repository.
Read its README, repository tree and top-level action function declarations.
All 19 upstream action modules exist locally, and no upstream public top-level
function name in those modules was absent locally. This is **structural coverage
only**: class methods, semantics, failure recovery, performance and installed/live
effects are not proven by that comparison. No upstream code was imported in this change.

| Upstream action | Local counterpart | Remaining operational proof |
| --- | --- | --- |
| browser_control | actions/browser_control.py | Real browser operation/readback |
| code_helper | actions/code_helper.py | Model-backed artifact and validation |
| computer_control | actions/computer_control.py | Authorized native action/readback |
| computer_settings | actions/computer_settings.py | Exact dispatcher actions and installed effects |
| desktop | actions/desktop.py | Reversible file/desktop operation |
| dev_agent | actions/dev_agent.py | Real project generation, execution and repair |
| file_controller | actions/file_controller.py | Boundary tests plus installed operations |
| file_processor | actions/file_processor.py | Conversion/OCR/transcription per backend |
| flight_finder | actions/flight_finder.py | Current dates/prices/availability, no invented cheapest fare |
| game_updater | actions/game_updater.py | Actual installed game client |
| open_app | actions/open_app.py | Installed launch and process witness |
| proactive | actions/proactive.py | Class behavior, idle timing and interruption |
| reminder | actions/reminder.py | Real scheduler create/fire/cancel |
| screen_processor | actions/screen_processor.py | Screen/camera capture, acknowledgement and cooldown |
| send_message | actions/send_message.py | Authorized account, actual receipt |
| system_monitor | actions/system_monitor.py | Host sensor readings |
| weather_report | actions/weather_report.py | Current provider response |
| web_search | actions/web_search.py | Search/news/research/price/compare modes and source URLs |
| youtube_video | actions/youtube_video.py | Current browser/site behavior |

README behavior needing additional code-level and live comparison: Gemini voice
and interruption, automatic language, reconnection/backoff and context retention,
screen/webcam handling, persistent/session memory, text/voice interaction,
morning briefing, proactive check-ins, parallel news retrieval and transient-state
reset. README latency numbers are upstream claims, not Onyx benchmarks. Historical
42-capability tests in the September 4 audit do not certify this new baseline.

## Implemented in this change

### Obsidian Second Brain

`memory/obsidian_v1.py` reuses the existing local MemoryStore in a separate index.
No plugin installation, vault writes, automatic note execution or embeddings API.
Explicit refresh indexes UTF-8 Markdown in a selected vault, skips hidden/private
folders, credentials, symlinks/reparse points and notes containing
`onyx_exclude: true` or `onyx_context: false`. These exclusions are heuristics,
not a guarantee that arbitrary sensitive prose will be detected. Select a
curated vault suitable for AI use. Local index content is stored in SQLite;
it is not encrypted by this connector and inherits host-directory access controls.

Refresh is bounded to 1,000 accepted notes, 256 KiB per file and 16 MiB total;
larger collections require a subsequent batching implementation. Markdown is
chunked and indexed for lexical retrieval. Obsidian links/tags remain text;
backlink graph expansion, attachment ingestion, semantic embeddings, automatic
watching and owner-facing setup UI are not implemented here.

Changed/deleted/newly excluded notes are rejected at retrieval even before
refresh. Refresh removes obsolete indexed chunks. Retrieval never triggers a
full scan on demand. Citations identify note and character offset.

Run from the source directory, using an existing dedicated index directory:

```powershell
python -m memory.obsidian_v1 --vault "C:\path\to\approved-vault" --database "C:\path\to\private-index\onyx_obsidian.sqlite3" refresh
python -m memory.obsidian_v1 --vault "C:\path\to\approved-vault" --database "C:\path\to\private-index\onyx_obsidian.sqlite3" search "project delivery"
```

These paths are examples, not configured owner paths. For conversation retrieval,
the index must be at `memory_dir()/onyx_obsidian.sqlite3`; set the owner-controlled
`ONYX_OBSIDIAN_VAULT` to the selected absolute vault path and
`ONYX_OBSIDIAN_CONTEXT=1` only after approving that retrieved excerpts may be sent
to the configured AI provider. It uses the existing `memory_search` tool and
shares its character budget with personal memory. This is tool-driven retrieval,
not guaranteed automatic retrieval on every turn. It runs off the audio event
loop through the existing tracked action boundary.

No real owner vault has been indexed. Vault choice is pending.

### Business documents

`core/deals_v1.py` validates invoice/quote/proposal input, computes decimal totals,
escapes HTML and renders an actual PDF through the already-installed Playwright
Chromium. Network requests and page JavaScript are disabled during rendering.
Branding is Cyryx Labs / Onyx. This does not change the application layout.

Each kind has an independent UTC-year sequence in `onyx-deals.sqlite3`.
A request ID is bound to content. Repeats return the same verified artifact;
different content with the same ID is refused. Failed/reserved generations need
reconciliation and never report success. Files are created exclusively, without
overwriting existing documents. Generated does not mean delivered or paid.

```powershell
python -m core.deals_v1 approved-document.json --output-dir "C:\path\to\existing-output" --request-id "owner-chosen-unique-id"
```

Required JSON: kind (`invoice`, `quote`, `proposal`), currency (`USD`, `CAD`,
`EUR`, `GBP`, `BRL`), title, client, terms, and items containing description,
quantity and unit_price. Use exact decimal strings, e.g. `"1200.50"`.
An input total is ignored and recalculated. Taxes, payment instructions and
commercial terms are not inferred. Voice extraction, owner review in the app,
Telegram delivery and frozen-package qualification remain unfinished.

### Phone preparation — not dialing

`core/phone_brief_v1.py` produces a bounded, hashed booking/inquiry preview with
an exact E.164 target and constraints. It rejects unresolved placeholders,
credential-like content and extra vault/session fields. A deterministic curated
FAQ lookup never elevates a caller through a PIN and has no assistant tools.

```powershell
python -m core.phone_brief_v1 approved-call-brief.json
```

The CLI explicitly reports `preview_only` and `dialed: false`. Actual provider
dispatch, owner approval UI, cost reservation, durable uncertain-outcome
reconciliation, inbound telephony, IVR/hold handling and callback delivery are
**not implemented** by this preparation surface.

The official [Retell create-call API](https://docs.retellai.com/api-references/create-phone-call)
and [get-call API](https://docs.retellai.com/api-references/get-call) were inspected
for the next connector. A registered or ended call alone must not be labelled a
confirmed booking. No provider account, phone number, subscription or live call
was created. Provider cost and an owned number require owner configuration.

## PDF requirements mapped to the two sprints

- Booking/inquiry: exact constraints, honest AI disclosure, alternatives deferred,
  IVR/hold/voicemail, capped duration and costs, verified outcome — Sprint 2.
- Inbound receptionist: curated briefing only, guest isolation, callback receipt,
  stronger owner authentication than a spoken PIN — Sprint 2.
- Deals engine: structured extraction, deterministic totals, separate sequences,
  PDF, Telegram delivery receipts — Sprint 2; local generation implemented.
- Phone notifications/calendar receipts and quoted-price comparison batches —
  Sprint 2 integration; approved accounts/targets/budget required.
- Optional voice cloning is not activated: the owner required preserving voice.
  Promotional claims about extra paid-community code are not supplied source.

## Verification

- Focused expansion + memory + mission subprocess + conversation/latency tests:
  **61 passed, 15 subtests passed**, 29.33 s.
- Ruff on new modules/tests: passed after replacing a lambda assignment.
- Python compilation of main.py and changed/new modules: passed.
- PDF test used real Chromium, extracted PDF text and checked durable numbering;
  synthetic data only. Separate injected-renderer tests cover failure/sequence behavior.
- No full repository regression, native release acceptance, physical voice/camera,
  Obsidian owner-vault test, live call or Telegram delivery is claimed.
- Required `npm run lint`, `npm run typecheck`, `npm test` each returned ENOENT:
  this Python source snapshot has no package.json. They did not pass.
- Design: no humanoid, effects, voice or layout files changed in this expansion.
  The earlier response/history and adaptive-renderer candidate remains source-only.

## Continuation — owner vault, assistant dispatch and Phone Link

The earlier vault-selection and telephony-account statements above describe the
initial implementation, not the current owner decision. The owner selected a new
vault at `C:\Users\ppetr\Documents\Cyryx Labs\Onyx Vault`, with Personal
Information, Cyryx Labs, Learning and Skills sections. Personal Information and
Profile starter notes are excluded from retrieval. Exclusion is per note, not
inherited by every future note in a folder.

Added `memory/second_brain_config_v1.py`: persistent scoped vault/index settings,
explicit context opt-in, local refresh/search/status commands and atomic settings
replacement. Conversational retrieval now supports that configured database;
the legacy environment override and explicit context pause remain supported.
This is source implementation, not proof of activation in the installed release.

Added assistant-dispatched `business_document_generate` and `phone_call_prepare`
tools. Both require the existing exact owner-confirmation boundary, including
under autonomous mode. Document generation produces a local PDF; phone preparation
does not dial. Telegram delivery and autonomous phone audio remain unfinished.

The owner prefers the existing paired Phone Link instead of creating a paid
Retell account, and reports PC microphone/speaker calls already work. During
read-only native inspection, Phone Link became targetable after the owner opened
it. The Calls tab, contact search, dial pad and call history were visually
observed. The inspection API returned no accessibility tree. Initial capture
before activation was not reliable; after activating the specific Phone Link
window, its screenshot was verified. No call, text, pairing change, or audio
setting change was performed. Call-history personal data is not copied here.

This proves visible UI access only. It does not certify Onyx call initiation,
audio injection/capture, turn-taking, end-call recovery or booking verification.
The owner subsequently confirmed Android and explicitly requires support for both
Android and iPhone. A live call still needs an explicitly
approved recipient and purpose; no such target is inferred from recent calls.

### Dual-platform requirement (owner clarification)

Both Android and iPhone are required Phone Link calling targets. Microsoft documents
Bluetooth calling for both at
https://support.microsoft.com/en-us/windows/apps/phonelink/setting-up-calls-in-the-phone-link
and https://support.microsoft.com/en-us/windows/apps/make-and-receive-phone-calls-from-your-pc.
This provider capability is not proof of Onyx integration. Do not assume Android
app mirroring or other phone controls are available on iPhone.

| Qualification | Android | iPhone |
| --- | --- | --- |
| Paired owner device | Owner confirmed | Not available in this execution |
| Phone Link Calls UI | Visually inspected | Not tested |
| PC microphone/speaker calling | Owner reports working | Not tested |
| Onyx approved dialing and end-call control | Pending | Pending |
| Onyx bidirectional audio and interruption | Pending | Pending |
| Disconnect recovery without duplicate dialing | Pending | Pending |
| Verified call outcome and installed proof | Pending | Pending |

Qualify target confirmation, start/answer/end, bidirectional audio, interruption,
timeout, disconnect and uncertain-outcome recovery separately on each platform.
Never label iPhone tested based on Android results. Neither target uses Retell by
default. Existing carrier charges and AI processing costs are not guaranteed zero.
Phone Link must not be used for emergency calling.

Continuation regression: **48 passed, 10 subtests passed**, 5.08 seconds, covering
Second Brain configuration, Obsidian, business PDFs, phone briefs and tool wiring.
The two-sprint story remains InProgress; no full-suite or installed certification
is inferred from this focused result. No humanoid, layout or voice changes.

## Next acceptance gate

### Voice incident continuation

Input-level experiment: changed only the AB13X capture endpoint from 55.294% to
85%, then measured ten seconds locally (no saved/transmitted audio): peak 183 on
both channels, RMS 6.59, no clipped samples. Speech timing/conditions were not
independently verified, so this does not prove gain failure or improvement.
Restored the exact prior scalar 0.5529412031173706; no permanent gain calibration
is claimed. AB13X remains the selected Onyx input. Output and voice unchanged.
Ran `python scripts/verify_release_workflow_v96.py`: failed as expected on changed
`core/live_voice_continuity_v1.py`. Do not regenerate V96 to erase the drift;
successor release qualification is required before installation.

Further diagnosis: AB13X stereo capture (8 seconds, 16 kHz, DirectSound) measured
channel peaks 29/30 and RMS 0.95/0.95 on signed 16-bit samples. Both channels were
near silent; this does not establish a failed microphone without synchronized
owner speech. No audio retained or transmitted. Read-only Windows endpoint checks:
AB13X not muted, level 55.3%; JOUNIVO not muted, level 61.2%. No gain changes made.
Expanded voice/config/session/latency/device regression: **154 passed**, 9.34 s.
This remains source/test evidence; neither installed fix nor physical recovery is
certified. Owner synchronization was requested for the next microphone test.

Owner subsequently confirmed AB13X as the intended microphone, with JOUNIVO also
required. Both devices passed the existing callback-stream probe via DirectSound
(frames delivered; no recording retained). Created the installed user preference
`memory/audio_device_selection_v1.json` selecting `Microphone (AB13X USB Audio)`;
output remains system default and voice unchanged. The installed log subsequently
recorded `Mic stream open`, consistent with its automatic route refresh. This does
not prove intelligible speech or a provider reply. Focused device-selection and
stream-ownership regression: 16 passed in 3.73 seconds. JOUNIVO was probed but was
not made active; physical conversation quality for both still requires live testing.

Owner reports no reply to spoken input. Installed process was running resident,
without a targetable window; its log records minimization and successful initial
microphone opening, followed by normal Gemini GoAway/reconnections. These logs do
not measure current microphone signal. Read-only device enumeration reports the
Windows default input JOUNIVO JV801P and output AB13X USB Audio. Owner's intended
microphone remains to be confirmed. No recordings or device changes were made.

Found and corrected a source defect in `core/live_voice_continuity_v1.py`: transport
cleanup cleared the turn-drain event although persistent playback can still hold
the speaking gate. A rotation without turn_complete could therefore leave PC mic
input suppressed. Cleanup now signals drain completion; reconnect does not erase
that signal. Playback releases speaking only after its pending native writes drain.
This is a demonstrated code path, not a confirmed diagnosis of the owner session.

Focused rotation, continuity, playback ownership and latency regression: **44
passed**, 6.08 seconds. Added a playback execution test and a supervisor signal
contract check. Physical speech, active mute/gating state and installed correction
remain unverified. No installed file was patched and no voice/layout change made.

Complete Phone Link control/audio qualification and the remaining implementation
and integration tests listed in the story. Do not require a Retell subscription
for the selected Phone Link path. Separately approve provider-visible Second
Brain excerpts before enabling conversational context for owner content.
Do not install this unsealed source over V96: it needs successor release bindings,
full regression, packaged dependency checks and rollback qualification first.
