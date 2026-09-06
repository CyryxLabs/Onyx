# Onyx — governed AI assistant

Onyx is the original governed intelligence platform from Cyryx Labs. Its UI,
setup, diagnostics, memory, and operational behavior share one coherent identity.
Historical environment-variable names remain only as non-visible compatibility
surfaces so existing installations do not break.

Launch behavior and trust are explicit nonsecret settings in `config/api_keys.json`.
`startup_briefing_enabled` and `proactive_enabled` default to `false`, so launch
sends no unsolicited model prompt or tool request. Owner autonomy requires both
`"trust_profile":"autonomous"` and `"owner_autonomy_enabled":true`; malformed or
missing values mean OFF. `autonomous_workspace_roots` is the explicit list of
places where autonomous file mutation may occur. The UI logs `OWNER AUTONOMY
ON/OFF` at startup; changing the local JSON takes effect on restart.

Autonomy grants broad generic browser and computer input, so those controls can
compose external effects; the system cannot truthfully guarantee semantic
confirmation for every message or purchase performed through generic UI steps.
Direct messaging, deletion, payment/security/network, generated-code execution,
publishing, install, and shutdown tools remain confirmation-gated as defense in
depth. Source, policy, config, audit, memory, credential, certificate, keychain,
device, and operating-system paths remain protected independently of approval.
File deletion additionally fails closed when the platform Trash API cannot bind
the exact approved file identity; Onyx asks for a manual action instead of
claiming that a path-based delete is race-safe. Directory copy and cross-volume
move likewise fail closed when a bounded handle-based operation is unavailable.
Tool decisions and outcomes are recorded in a protected, local-owner SQLite
audit with an integrity chain. It stores structural argument types, never typed
text, file contents, memory values, or deterministic hashes of those values.
This is a local tamper-evidence boundary, not remote attestation; a machine
administrator can ultimately alter local software or storage.

## Governed missions

Onyx includes a local-first SQLite mission control plane. Missions move through
validated states (`draft`, `awaiting_approval`, `running`, `waiting`, `paused`,
`succeeded`, `failed`, or `cancelled`) and keep append-only events, step
checkpoints, bounded retries, deadlines, stable idempotency keys, and restart
recovery. Approval of a mission is never a blanket tool grant: each
consequential step is checked again by the trusted host permission broker.
Approval binds the ordered safe plan, arguments, and budgets to a canonical
SHA-256 digest. Waiting or restart-uncertain work is never replayed; `resolve`
requires an explicit `succeeded`, `retry`, or `failed` decision.

Paid-provider cost defaults to zero. A plan with a nonzero provider estimate is
rejected unless its explicit mission budget covers it. The mission-tool catalog
described in this section includes no email or calendar connector. DayOps is a
separate read-only Microsoft Graph surface and remains unavailable until its
account/access gates are provisioned. The built-in dry-run example uses only
local data-returning tools:

```powershell
python -m core.missions create "Plan my desk day" --plan '[{"tool":"local_note","args":{"text":"Review priorities"}},{"tool":"local_checklist","args":{"items":["triage local files","write plan"]}}]'
python -m core.missions list
```

Use the returned mission ID with `approve`, then `run`. CLI approval prints the
exact canonical plan and requires a TTY user to type `APPROVE <plan-digest>`;
non-interactive approval fails closed. Other commands are `show`, `pause`,
`resume`, `cancel`, `resolve`, and `events`. In the desktop assistant,
`mission_run` approves and queues the mission, then returns immediately with a
`running` state so the voice session remains responsive. The application-owned
worker exists only while Onyx is running. Runtime data is stored under the
platform-specific Onyx data directory and is excluded from version control.
Mission events are runtime-immutable and hash chained; reads verify integrity.
This detects corruption or casual modification, but cannot defend against a
malicious local account owner replacing the whole database. Execution is
currently limited to pure provider-free built-ins. Deadline handling uses a
bounded helper thread: late pure computation may finish in memory, but it cannot
commit a late mission result. Structured step results contain `status`, redacted
`data`, bounded `evidence`, deterministic `postconditions`, and `waiting_for`.
Missing or failed postconditions move the mission to `waiting`; they are never
treated as success or automatically replayed.

Provider-free daily workspace missions support bounded inventory, literal-only text search,
text reads, SHA-256 hashing, local runtime status, and readiness summaries.
Roots must be explicitly allowlisted with `ONYX_WORKSPACE_ROOTS`; parent escapes,
absolute child paths, links/reparse points, devices, binaries, oversized files,
and credential-shaped paths/content fail closed. Results carry local provenance.
Later steps may consume a whole prior safe value with an explicit
`{{step.0.result.field}}` reference; references are data, never prompts.

`python -m core.missions worker --once` atomically leases and executes one
already-approved local mission. `worker --poll 2` runs a foreground queue loop
with expiring single-owner leases and heartbeats; Ctrl+C stops it. `doctor` reports the safe
local capability scope and `example --root <allowed-root>` creates a daily audit
plan. The desktop app starts and stops the same lease-based worker with its own
lifecycle; no OS background service is installed. These missions provide no email,
calendar, browser, network, arbitrary shell, or autonomous file-write access.
See [`docs/MISSIONS.md`](docs/MISSIONS.md) for the exact runtime and result
contract.
### Onyx — the Cyryx Labs cross-platform personal AI assistant

A real-time voice AI that can hear, see, understand, and control your computer on supported Windows, macOS, and Linux configurations. Platform-specific actions still depend on the native tools listed below. The live conversation is processed by the configured Gemini cloud service; approved tools, durable memory, mission state, and audit records remain on the owner's device. Provider pricing and network availability still apply.

---

## ✨ Overview

Onyx is designed to feel immediate, natural, and operational. This build removes conversational friction: long thinking silences, double responses, slow interruption, and weak search result handling.

It's not just an assistant — it's an extension of your digital life.

---

## 🚀 Capabilities

### Core Features
| Feature | Description |
|---|---|
| 🎙️ Real-time Voice | Ultra-low latency conversation in any language via Gemini Live API |
| 🖥️ System Control | Launch apps, adjust volume/brightness, WiFi, shortcuts, power — all by voice |
| 🧩 Autonomous Tasks | High-level planning for complex multi-step goals via agent mode |
| 👁️ Visual Awareness | Real-time screen capture and webcam vision piped into your main Gemini session |
| 🧠 Persistent Memory | Deeply remembers projects, preferences, and personal context across sessions |
| ⌨️ Hybrid Input | Seamlessly switch between keyboard typing and voice commands |
| 🌅 Morning Briefing | Optional startup greeting/news/weather flow; disabled by default until the owner enables `startup_briefing_enabled` |
| 🔔 Proactive Check-ins | Optional silence-break suggestions; disabled by default until the owner enables `proactive_enabled` |
| 📊 Hardware Monitoring | Continuous CPU, RAM, GPU and temperature telemetry with localized voice alerts when thresholds are breached |
| 🌤️ Weather Report | Live weather data for your city, personalized from memory |
| 🗺️ Dynamic Content Panel | Scrollable display layer beneath the HUD that renders web results, news, and search data with timestamps |
| 🔍 Multi-Mode Web Search | `news` / `research` / `price` / `compare` / `search` — Gemini Grounded first, DDG fallback |
| ⏰ Smart Reminders | OS-native scheduled notifications (Windows Task Scheduler / macOS LaunchAgent / Linux systemd) |
| ✈️ Flight Finder | Live flight price and availability lookup |
| 🎮 Game Updater | Checks and triggers game updates on demand |
| 📂 File Processor | Read, summarize, and answer questions about local files |
| 💻 Code Helper | Inline code review, debugging, and generation |
| 🌐 Browser Control | Open URLs, navigate tabs, and interact with the browser by voice |
| 📨 Send Message | Compose and send messages through integrated messaging apps |
| 🎬 YouTube Control | Search, play, and control YouTube playback by voice |
| 🖱️ Desktop Control | Taskbar, window management, and desktop-level operations |
| 🧑‍💻 Silent Language Memory | Detects spoken language on first use and saves it silently — all future sessions and briefings adapt automatically |

---

## What is new in Onyx

### ✋ Instant Interrupt — ESC or Button
Press **Escape** or click the `INTERRUPT` button to cut Onyx off mid-sentence and return to listening. Audio is split into ~50 ms chunks (2400 bytes each), so the interrupt fires within one slice. The interrupt drains the audio queue, sets a flag, and clears the turn — listening resumes in under 100 ms.

### 👁️ Immediate Vision Acknowledgment
When you ask Onyx to look at your screen or camera, it acknowledges the request immediately while image capture runs. The actual analysis follows as a second response, avoiding awkward silence.

### 📰 Parallel News Search — First Result Wins
News queries now run **Gemini Grounded Search and DuckDuckGo news simultaneously** in two daemon threads. Whichever delivers a valid result first wins; the other is silently discarded. Previously, a Gemini 503 error would stall the search for several seconds before falling back to DDG. Now the fallback happens in parallel — total news fetch time drops to whichever backend is fastest at that moment.

### 🗞️ Real News Articles (Not Homepages)
DDG news search uses `ddgs.news()`, which returns actual article URLs, titles, snippets, and source names rather than homepages.

### 🌅 Two-Phase Startup Briefing — Runs Concurrently
The startup briefing now sends Phase 2 (news fetch) while Phase 1 audio (the greeting) is still playing. Previously, Phase 2 waited for Phase 1 to fully complete. The 1.5-second overlap means the news headline is ready by the time Onyx finishes saying "Good morning."

### 🔁 Smarter Reconnection — Exponential Backoff
Network timeouts now use exponential backoff: 3s → 6s → 12s → 60s (capped). Each retry shows a Turkish-language status message in the UI ("Bağlantı kurulamadı — Xs sonra tekrar deneniyor"). Previously, a dropped connection would loop tightly and show no useful information.

### 🛡️ Vision Cooldown & Echo Guard
Screen capture is guarded against echo loops. If Onyx speaks about the screen and the microphone picks up its own voice, duplicate calls are blocked with a 4-second cooldown and a `_vision_busy` flag. Both reset when a new session connects.

### 🌐 Language-Aware Address — Never Mixed
On first setup Onyx asks for the owner's name and persists it locally. It uses that name naturally and occasionally, with “sir” as a restrained fallback when no name is available.

### 🪟 Zero Terminal Windows
A subprocess monkey-patch at startup sets `CREATE_NO_WINDOW` on every child process launched by the app. No PowerShell, no CMD, no terminal flash — ever. Applies to all actions including reminders, system commands, and scheduler calls.

### 🔄 Session State Isolation
All transient vision and interrupt flags (`_pending_vision`, `_vision_busy`, `_vision_cam_active`, `_vision_close_pending`, `_interrupted`) are fully reset whenever a new Gemini session connects. Previously, state from a crashed session could carry over and leave Onyx in a broken state until restart.

---

## ⚡ Quick Start

### Installable application

The native build pipeline targets Windows x64, macOS 15+ Apple Silicon, Linux
x64, and Linux arm64. The current engineering candidate is **Onyx 1.2.0**.
It is source-only; packaging and installation are pending. The installed
predecessor is **Onyx 1.1.31 / V96**. The candidate remains
**unsigned-untrusted and not released**. Live-provider behavior is unverified
for this candidate. See
[`docs/onyx/CURRENT_CAPABILITY_STATUS_V2.md`](docs/onyx/CURRENT_CAPABILITY_STATUS_V2.md)
for the evidence-layer matrix. The unchanged
[`docs/onyx/CURRENT_RELEASE_STATUS.md`](docs/onyx/CURRENT_RELEASE_STATUS.md) is
the historical formal **1.1.9 R15B NO-GO**, not the current 1.2.0 authority.

The candidate does not advertise macOS Intel because the
security-fixed locked cryptography line has no Intel wheel and the formal
pipeline refuses an unreviewed native source build. No 1.2.0 package is
qualified for release. Once a future candidate closes its signing, native-host,
provider and release gates, use the **Release packages** GitHub Actions
workflow or build on each native platform with:

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
python scripts/build_release.py --version 1.2.0
```

The release includes the required Playwright Chromium browser and emits an
installer/package, SHA-256 checksums, and a machine-readable manifest. Detailed
installation, signing, runtime-data, and release instructions are in
[`docs/INSTALLATION.md`](docs/INSTALLATION.md).

### Source checkout

```bash
git clone <authorized-cyryx-onyx-repository-url> Onyx
cd Onyx
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python setup.py
python main.py
```

`setup.py` installs the Python dependency set and the Playwright Chromium
browser. It does not elevate privileges or install operating-system packages.
On Linux, review and run `python -m playwright install-deps chromium` yourself
if Chromium reports missing distribution libraries. The first launch asks for
a Gemini API key and stores it in the current user's native OS credential vault:
Windows Credential Manager, macOS Keychain, or Linux Secret Service. It never
falls back to plaintext storage.
`config/api_keys.json` contains non-secret settings only. Existing plaintext
`gemini_api_key`/`api_key` fields are migrated to the vault and atomically
removed after verified readback.

You can manage the credential without putting it in shell history:

```bash
python -m core.credentials status
python -m core.credentials set       # hidden getpass prompt; never accepts the key in argv
python -m core.credentials migrate
python -m core.credentials delete
```

For ephemeral automation, `GEMINI_API_KEY` is the highest-precedence explicit
override; `GOOGLE_API_KEY` is also supported. Environment overrides take
precedence over the OS vault and are never copied into the settings file.
Linux installations need a working Secret Service session and `secret-tool`;
Onyx fails clearly instead of falling back to plaintext storage.

### Local semantic and episodic memory

Onyx stores approved durable memory locally in `memory/onyx_memory.sqlite3`.
The versioned SQLite database records semantic facts and deliberately captured
episodes with provenance, timestamps, session/task identifiers, salience, and a
minimal content-free audit trail. It never sends memory to an embedding service:
retrieval uses SQLite FTS5 when the bundled SQLite supports it and a deterministic
sparse-token fallback otherwise. Ranking combines text relevance, salience, and
recency. Prompt context is character-bounded, cited, delimiter-sanitized, and
explicitly framed as untrusted reference data. These controls mitigate prompt
injection; they cannot guarantee every model will ignore adversarial text.

Saving model-suggested memory still requires the trusted host permission dialog.
Credential-shaped keys and values are rejected, raw conversations are not silently
archived, and the API-key vault is never ingested. Existing
`memory/long_term.json` data is imported once, verified by readback, and left in
place. Runtime database, WAL, and export files are ignored by Git.
On POSIX systems Onyx applies owner-only `0600` modes to database, sidecar, and
export files. On Windows, confidentiality also depends on the ACLs of the signed-in
user's profile/workspace; Onyx does not rewrite Windows ACLs. Forgetting uses
SQLite secure deletion and requests active-WAL truncation. If a concurrent reader
keeps the WAL busy, the item remains logically deleted but Onyx reports that
physical WAL cleanup is pending instead of claiming full cleanup. It cannot erase copies in
filesystem snapshots, backups, sync services, or prior exports. Delete those
copies through their owning service. Low-salience episodic history is bounded at
safe startup and can also be applied explicitly.

Memory can be inspected and controlled without starting the voice UI:

```bash
python -m memory.memory_manager list
python -m memory.memory_manager search "current project"
python -m memory.memory_manager remember editor "VS Code" --category preferences
python -m memory.memory_manager forget editor --category preferences
python -m memory.memory_manager export memory/exports/onyx-memory.json
python -m memory.memory_manager privacy off
python -m memory.memory_manager retention --max-episodes 2000 --min-salience 0.15
```

The Live API defaults to the Gemini 2.5 native-audio preview used by the
assistant's function-calling workflow. Set `ONYX_LIVE_MODEL` to override the
model identifier without changing source code.

Before starting Onyx, run the best-effort offline operational readiness check:

```bash
python -m core.readiness
python -m core.readiness --json
```

To explicitly test the real end-to-end voice path, close other microphone users,
speak the exact phrase **“Onyx readiness check”** after the audible tone, and run:

```powershell
python -m core.readiness --integrated-voice --timeout 30 --json
```

This opt-in probe captures microphone PCM only in memory, sends it directly to
Gemini Live, requires Gemini input transcription containing both “Onyx” and
“readiness,” returned audio plus turn completion, and plays a bounded reply
through the default speaker, and immediately discards all audio. It never saves
or logs microphone/model audio, transcript text, or the credential. Recognition
depends on Gemini transcription quality. The probe uses the same shared production
sample rates, 1,024-frame PCM chunks, MIME type, Charon voice, and transcription
settings. The production-parity probe keeps automatic VAD enabled, starts receiving
before capture, and sends each callback chunk while the microphone is live. Speak
promptly and leave at least two seconds of trailing silence during its six-second
capture window. It intentionally
omits the agent tools and full system prompt. Default readiness does not
access the microphone, speaker, camera, or Gemini API.

The default command does not intentionally contact Gemini, record audio/video,
speak, or perform OS-control actions. Its full-runtime import uses a best-effort
Python networking guard. This is a diagnostic guard, not security containment:
native libraries loaded through `ctypes` and child processes can bypass Python
monkey patches. Potentially blocking imports, device enumeration, and Chromium work
run in killable child processes. The command reports structured `PASS`, `WARN`,
`FAIL`, and `SKIP` results, never prints API-key values, and treats any required
result other than `PASS` as not ready. It makes and removes small transient test
files to verify runtime-directory permissions, enumerates audio devices, and
launches/closes headless Chromium.

JSON separates `install_ready`, `selected_probes_verified`, component facts, and
`operationally_verified`. Independent Live API, audio-device, and microphone
checks can establish `voice_prerequisites_verified`, but they are not an
integrated microphone-to-model-to-speaker test. Top-level `ready`,
`integrated_voice_loop_verified`, and `operationally_verified` remain false
unless the explicit `--integrated-voice` acceptance probe passes.
For a deterministic manual-VAD transport diagnostic, use
`python -m core.readiness --voice-transport --timeout 30 --json`. That command
uses explicit activity markers and can set only `voice_transport_verified`; it
never sets integrated or operational readiness.
Human output states this boundary as `COMPONENTS VERIFIED / INTEGRATED VOICE NOT
VERIFIED`. The default per-probe timeout is 30 seconds and can be overridden
with `--timeout`.
The readiness CLI exits zero only when the installation baseline passes. Without
opt-in probes, that baseline is the complete exit criterion and the report states
`INSTALL READY; OPERATION NOT VERIFIED`. With any opt-in probe, exit zero requires
both the installation baseline and every selected probe to pass. A successful
live-only, hardware-only, or camera-only acceptance run therefore verifies exactly
that selected scope without claiming full voice operation, but it can never mask a
failed required installation check.

Use explicit opt-in flags for real environment acceptance probes:

```bash
# Captures and discards 100 ms of ambient mic input.
python -m core.readiness --hardware

# Sends a tiny non-private text turn and requires both nonempty server audio and
# an explicit completed turn from Gemini Live.
python -m core.readiness --live-api

# Optional vision probe captures and discards one camera frame.
python -m core.readiness --camera

# Core voice-component verification with an explicit timeout and JSON output.
python -m core.readiness --hardware --live-api --timeout 15 --json
```

Camera verification is reported separately and is not required for core voice
operation. Any explicitly selected camera failure still fails the selected-probe
scope and leaves `camera_verified` false without erasing independently proven
voice-component facts. Hardware and live-service failures make selected readiness false and return a
nonzero exit without exposing credentials. Neither opt-in mode invokes speech
playback or mutating computer-control tools. Every timeout must be finite and
greater than zero; timed-out probe process trees are terminated and reaped.
All readiness children receive a minimal allowlisted environment. The Live API
key and resolved model are passed only in the gated parent-to-child stdin payload;
unrelated environment credentials and tokens are not inherited.

---

## 📋 Requirements

| Requirement | Details |
| --- | --- |
| **OS** | Windows 10/11, macOS, or Linux |
| **Python** | 3.11, 3.12, or 3.13 |
| **Microphone** | Required for voice interaction |
| **API Key** | Free Gemini API key in the native OS credential vault, or an explicit `GEMINI_API_KEY`/`GOOGLE_API_KEY` environment override |
| **FFmpeg** | External executable required for audio/video conversion, trimming, frame extraction, and transcription preprocessing |
| **OS integrations** | Some actions require platform tools such as `wmctrl`/`xdotool`, native schedulers, browser installations, camera drivers, or game launchers |

Approved Dev Agent projects are published with the operating system's native
atomic no-replace primitive on Windows, Linux, and macOS. Other operating
systems can still run the assistant, but Dev Agent publication fails closed
instead of claiming collision-safe support.

---

## 🗂️ Project Structure

```
Onyx/
├── main.py                  # Core loop — Gemini Live session, audio I/O, tool dispatch
├── ui.py                    # PySide6 HUD — waveform, log panel, interrupt button, camera feed
├── setup.py                 # Dependency and Playwright setup
├── actions/
│   ├── web_search.py        # Gemini + DDG parallel search (news, research, price, compare)
│   ├── screen_processor.py  # Screen capture & webcam vision via Gemini Live
│   ├── reminder.py          # OS-native scheduled notifications
│   ├── system_monitor.py    # CPU / RAM / GPU / temperature telemetry
│   ├── computer_settings.py # Volume, brightness, WiFi, power
│   ├── computer_control.py  # Keyboard shortcuts, mouse, window management
│   ├── open_app.py          # Application launcher
│   ├── browser_control.py   # Web browser control
│   ├── file_controller.py   # File system operations
│   ├── file_processor.py    # Document reading and summarization
│   ├── send_message.py      # Messaging integration
│   ├── weather_report.py    # Live weather data
│   ├── flight_finder.py     # Flight search
│   ├── youtube_video.py     # YouTube playback control
│   ├── game_updater.py      # Game update management
│   ├── code_helper.py       # Read-only code review + exact-file execution
│   ├── dev_agent.py         # Immutable-artifact project generator
│   ├── desktop.py           # Explicit desktop and wallpaper actions
│   └── proactive.py        # Proactive silence-break suggestions
├── memory/
│   ├── store.py             # Local SQLite semantic + episodic memory
│   └── memory_manager.py    # Compatibility API and privacy controls/CLI
├── core/
│   ├── credentials.py       # Native OS credential vault + legacy migration
│   └── prompt.txt           # Onyx personality and tool-routing rules
└── config/
    └── api_keys.json        # Non-secret local system configuration only
```

The remote dashboard generates a unique self-signed TLS certificate on first
use under `config/certs/`. The certificate and private key are local runtime
state and are never committed. A phone browser may ask you to accept that local
certificate once before microphone access is available.
Dashboard REST requests carry the access token only in the `Authorization`
header. File downloads use authenticated fetch/blob URLs, and browser
WebSockets use cryptographically random, 15-second, single-use tickets bound to
either command or phone-audio scope. Long-lived access tokens are never placed
in download or WebSocket URLs. Sensitive responses disable caching and referrer
forwarding.

Remote wallpaper URLs are intentionally disabled to prevent network request
forgery. Download an image through a trusted browser, then use the `wallpaper`
action with its local path. On every operating system, Onyx never elevates
itself, changes the active network profile, or modifies firewall rules. The
dashboard prints an optional, narrow per-port command for the user to review
and run manually when LAN access is blocked.

All 26 model-exposed tools are covered by a centralized dispatcher risk policy.
Only operations that are both non-mutating and demonstrably non-sensitive may
run without a prompt. All browser operations require trusted approval because
browser sessions can be authenticated and even navigation can trigger stateful
requests. File listing, reading, searching, metadata, processing, desktop paths,
installed-game status, local system status, clipboard/screen/user-memory access,
and source analysis are private reads and require the same approval as mutations.
Web searches and weather lookups also require trusted approval because their
query, comparison items, or city are disclosed to external services. An
immediate `close_camera` safety stop is deliberately prompt-free; closing a
browser, application, or the assistant itself remains confirmation-gated because
it can discard work or terminate broader activity.
The exact resolved file path is added before a file-processing approval is
requested. That approval covers only the input operation. AI transformations,
image OCR, and audio/video transcription are preview-only because their exact
output bytes do not exist at approval time; `save=true` is refused and the tool
returns the full proposed content and destination without writing it. Fully
deterministic conversions and direct source-text extraction retain their normal
save behavior. `code_helper.run` likewise materializes one existing absolute file,
its normalized argument list, and timeout before approval and dispatches those
same values without post-approval generation. Its `explain` and `screen_debug`
actions are read-only and still require approval for private source or screen
data. Legacy `auto`, `write`, `edit`, `build`, and `optimize` actions are disabled;
project generation routes to the immutable-artifact development agent. Natural-
language desktop tasks cannot generate or execute code after description-only
approval; callers must choose an explicit declared desktop action.
Consequential actions—including input injection, file mutation,
messaging, reminders, app launches, approved generated projects, wallpaper changes, and
shutdown—are also default-deny and require fresh confirmation in the trusted
local desktop UI. Blank and unknown actions fail before a dialog is shown. A
`confirmed` value supplied by the model or a remote tool call has no authority.
Computer settings require an explicit recognized action; no second model is
allowed to infer an action after approval.

The development agent supports exactly Python. It generates a complete immutable
preview, but any plan with a non-empty third-party dependency list is permanently
preview-only: Onyx does not show an executable approval, invoke a package
manager or subprocess, download packages, run install/build hooks, execute the
code, or publish the project. The preview displays the exact dependency list and
guidance for manual provenance and build-metadata review in a separately created
environment outside Onyx.

For an empty-dependency Python plan, a trusted host UI must return the immutable
digest for the exact displayed file contents and hashes, project path, empty
dependency list, and command. The complete payload is shown without truncation.
Model/tool arguments cannot approve an action. Approved source is written to a
private random snapshot and executed by the current Python interpreter with
isolated flags, a sanitized environment, an authenticated in-memory project
importer, and both static and runtime enforcement that imports are limited to the
Python standard library plus the exact approved project modules. Only an exit-zero
run followed by final exact-byte verification permits atomic no-replace publishing
to the still-absent destination. Pre-existing code and environments are never
reused, and failed generated code is not repaired without a new preview and
approval. npm, npx, package lifecycle, publish, and arbitrary runner commands are
rejected.
The former direct build/auto-repair/VS Code branch has been removed; there is no
secondary mutation path around the immutable approved-artifact executor.

The modules in `core/llm_client.py`, `core/stt.py`, and `core/tts.py` are
optional local/offline building blocks. The primary `main.py` runtime uses the
Gemini Live native-audio session.

## Verification

```bash
python -m core.readiness --json
python -m compileall -q .
python -m unittest discover -s tests -v
python -m pip check
python -m pip_audit -r requirements.txt
ruff check . --select F,E9
ruff check . --select S102,S310,S314,S602
python browser_tests/test_dashboard_audio_worklet.py
git -c core.whitespace=cr-at-eol diff --check
```

The same checks run in GitHub Actions on Python 3.11 and 3.13, including a
requirements vulnerability gate, a Chromium AudioWorklet/PCM integration test,
runtime/UI tests under Xvfb on Linux, and offline runtime/Chromium readiness on
Windows and macOS.

---

## 🔒 License & Commercial Rights

Copyright © 2026 **Cyryx Labs LLC**. All rights reserved.

This software is governed by the **Cyryx Labs LLC Software License Agreement**.
Commercial use, reproduction, sublicensing, SaaS hosting, or distribution by third parties without prior written authorization and payment of licensing fees to **Cyryx Labs LLC** is strictly prohibited.

See the [`LICENSE`](LICENSE) file for complete terms and legal details.

---

## 👤 Owner & Maintainer

Onyx is designed, engineered, and maintained by **Cyryx Labs LLC**.
