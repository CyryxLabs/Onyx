# Onyx integration readiness — 2026-09-05

Audit completed against installed **1.1.30**, version last checked at 01:47 EDT (05:47 UTC); authorized Docker follow-up completed at 01:51 EDT. The parent is handling 1.1.31; these results do not qualify that successor.

Source: `C:\MAAX_Assistant\Onyx-Remediation-Clean-20260823-151210`.
Installed executable: `C:\Users\ppetr\AppData\Local\Programs\Cyryx Labs\Onyx\Onyx.exe`.
Owner data: `C:\Users\ppetr\AppData\Local\Cyryx Labs\Onyx`.

## Findings and remaining actions

| Integration | Current evidence | Remaining action / limit |
|---|---|---|
| Installed product | Executable ProductVersion is 1.1.30 at initial and final checks. No Onyx process was returned by the initial `Get-Process Onyx` probe. | No desktop launch or full installed application session was tested. Recheck against 1.1.31 after the parent's release work. |
| Gemini Live | Credential status: `configured=true`, `source=vault`, Windows Credential Manager. One real benign text-to-audio turn succeeded in **7.048 seconds**, including connection and turn completion. | Provider responsiveness passed for this one request. Voice identity, acoustic quality, microphone-to-provider-to-speaker conversation, and application UI responsiveness remain untested. |
| Audio devices | Existing audio CLI received callback frames from 2 inputs and 4 outputs. Saved device selections are empty; Windows defaults are JOUNIVO microphone and AB13X speakers. Saved voice is Charon. | Speak/listen acceptance must use the intended physical endpoints. Silent output callbacks do not prove audible playback; input callbacks do not prove intelligibility. |
| Camera / remote devices | Windows PnP Camera/Image query returned no rows. Device pairing/mesh contract tests passed using isolated fixtures. | Connect/select the intended camera and test an actual frame if needed. Pair and exercise each intended remote device with explicit owner participation; no live camera, LAN device, pairing or remote delivery is certified here. |
| Docker sandbox | Docker client 29.7.2 exists. Initially Desktop/backend were absent. After the authorized supported CLI start, Desktop/backend processes appeared, but both `dockerDesktopLinuxEngine` and `docker_engine` pipes remained absent. Service start was refused; service remained Stopped. | Owner must inspect the Docker Desktop startup screen and resolve its startup blocker. An administrator may need to start the existing service if Desktop requires it. Once an engine responds, verify the exact local pipe and reviewed local digest-pinned image, then run the bounded sandbox test. No container execution is certified. |
| Plugin host | Existing source CLI status against the owner memory registry returned `execution_enabled=false`, empty plugins, `native-sandbox-attestation-required`, and untrusted execution blocked. Docker sandbox flag/image/host are absent from process and user environment. | After Docker is available, configure `ONYX_PLUGIN_DOCKER_SANDBOX_V1=true`, a verified `ONYX_PLUGIN_DOCKER_IMAGE_ID=sha256:<64 hex digits>`, and the responding local `ONYX_PLUGIN_DOCKER_HOST`. Install/approve only the intended plugin through the existing workflow. Flags alone are not execution evidence. |
| FFmpeg | Full FFmpeg 7.1.1 runs, but **Onyx's default resolver returns null**. The WinGet Links entry resolves outside its parent directory and fails the resolver's containment check. Explicit real-path override passed the installed resolver and decoded the local clip successfully. | Supply the real binary path through `ONYX_FFMPEG_PATH` in the environment used to launch Onyx, then recheck. No persistent environment setting was changed. |
| Microsoft Graph | Owner DayOps V19 profile contains all eight required public fields. Its native authentication key exists and profile MAC matches. The refresh token for its derived Graph vault slot exists. | First perform a bounded approved mail/calendar read using the existing binding, reporting only receipt/status/counts. Do not assume a new consent is needed merely because a previous report called Graph blocked. Token expiry/revocation, scopes, alias authority and provider access were not validated over the network here. |
| Google Workspace | Default source CLI returns disabled/not-opened. Both exact activation flags and all five public binding settings are absent from process and HKCU user environment; the existing `runtime/google-workspace-host` directory is empty. Installed activation source differs from the concurrently edited snapshot. | Supply the intended owner/workspace/account, OAuth desktop client ID and callback port; configure and connect via the existing Google CLI with owner consent in a separate authorized run. Validate the parent's successor before activation. Default CLI output alone is not a lookup of every possible account. |
| Social / video | Local caption generation and local video-preview CLI both succeeded. Existing clip is 2 s, H.264, 720×1280, 5,052 bytes; full decode exited 0. Production construction accepts an optional social adapter; no assignment of `_official_social_adapter_v1` was found in the scoped source search. Status implementation reports `oauth-adapter-required` when absent. | Local drafting/preview is usable. Publishing requires an implemented and wired official adapter for the chosen platform/account, its OAuth configuration and exact preview consent. An OAuth toggle alone cannot supply a missing adapter. No send, upload or publish occurred. |

## Gemini probe details

Used existing `core.readiness_probe._live_handshake`, with the owner config and existing credential resolver. Prompt: `Reply briefly: ready.` Config uses AUDIO responses and Charon, with no tools. No private content, microphone sampling, playback, audio file or session-token output was involved. One provider attempt, response timeout 8 seconds, overall async timeout 20 seconds.

Result: `ok=true`, `completed_nonempty_audio_turn`, model `models/gemini-2.5-flash-native-audio-preview-12-2025`, elapsed 7.048 seconds. This measures connection plus complete response, not first-token latency. The helper validates nonempty audio and `turn_complete`; it does not verify the spoken wording. SDK emitted a non-data-parts warning, but the turn completed.

Direct execution of the helper from installed `_internal` with external Python could not import `dashboard.security`; direct `-m scripts.onyx_audio_cli`, `onyx_google_workspace`, and `onyx_plugin_cli` also were unavailable there. These are external-Python import limitations and do not establish failure of the frozen executable, which has embedded modules. Safe alternative: run the existing source helper. Its SHA-256 matched the installed integrity-source copy. Also matched: credentials, live model, FFmpeg resolver, audio device selector, social publication and capability expansion service. These comparisons do not certify the entire frozen package. Google activation source did not match; no concurrent edits were reverted.

## Authorized Docker startup follow-up

After the user explicitly authorized starting the existing installation, read `docker desktop --help` and `docker desktop start --help`, then ran `docker desktop start --timeout 35`. Docker Desktop and `com.docker.backend` processes appeared. The start command and a separate `docker desktop status` remained pending beyond the advertised start timeout; both audit-owned CLI invocations were interrupted. Desktop/backend processes were left in place, not killed.

After reading local `Start-Service` help, `Start-Service -Name com.docker.service -ErrorAction Stop` returned: `Cannot open 'com.docker.service' service on computer '.'`. No UAC request, terms acceptance, installation, configuration or security change was performed. This proves the service could not be started by this session; it does not establish the reason the Desktop backend itself failed to become ready.

Final independent subprocess probes had six-second limits and returned immediately with exit 1, server null and missing-pipe errors for both `npipe:////./pipe/dockerDesktopLinuxEngine` and `npipe:////./pipe/docker_engine`. Without a responding daemon, local images cannot be verified and the real sandbox test cannot run. No image pull, container creation or private-file mount was attempted. Owner action is to inspect the current Desktop startup state and make its engine ready; do not change sandbox restrictions to work around an unavailable engine.

## Reproducible safe probes

Run source commands from the source directory. Set `PYTHONDONTWRITEBYTECODE=1`; for source audio/config probes set `ONYX_DATA_DIR` to the owner-data path above. Do not print the config or credential values.

```powershell
python -m core.credentials status
python scripts/onyx_audio_cli.py status
python scripts/onyx_google_workspace.py status --json
python scripts/onyx_plugin_cli.py --registry 'C:/Users/ppetr/AppData/Local/Cyryx Labs/Onyx/memory/capability_plugins_v1.json' --workspace audit-readonly status
docker version --format '{{json .}}'
docker --host npipe:////./pipe/docker_engine version --format '{{json .Server}}'
ffprobe -v error -show_entries format=duration,size:stream=codec_name,codec_type,width,height -of json evidence/live/onyx-social-video-certification.mp4
ffmpeg -v error -nostdin -i evidence/live/onyx-social-video-certification.mp4 -f null -
python scripts/onyx_social_cli.py generate --brief 'Explain why local preview precedes publication.' --brand 'Cyryx Labs' --platform linkedin --source-ref integration-audit-20260905
python scripts/onyx_social_cli.py video-preview --workspace-id audit-readonly --principal-id audit-readonly --account-id audit-synthetic --target instagram-feed --caption 'Local integration audit preview. Not published.' --controlled-root evidence/live --media-file evidence/live/onyx-social-video-certification.mp4 --provenance integration-audit-20260905
```

The plugin registry was absent/empty at this inspected location; `audit-readonly` is a probe label, not a verified owner workspace identity. The video preview creates only an in-memory asset lease; its generated consent string was not submitted.

FFmpeg workaround tested in a child process only:

```powershell
$env:ONYX_FFMPEG_PATH = 'C:/Users/ppetr/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-7.1.1-full_build/bin/ffmpeg.exe'
```

With that override, installed `core.ffmpeg_runtime_v1.ffmpeg_command()` resolved the full executable and its decode returned exit 0 with empty stderr. To use it operationally, the owner must pass it to the intended Onyx launch environment; this audit did not launch/restart Onyx. The stock PATH symlink remains unresolved by Onyx.

Graph's existing `provision_dayops_v14 status` was inspected but not executed: it calls `store.initialize()` and `WorkspaceRegistry.initialize()`, so it is not a strictly non-mutating path. The safe alternative used SQLite `mode=ro` for bounded schema inspection and native-vault reads for booleans only. Profile MAC and token-presence checks reused the existing canonical profile format and vault-locator derivation. No token refresh, consent or Graph provider request occurred.

For Google, a subsequent owner-authorized setup uses `scripts/onyx_google_workspace.py configure` then `connect`, with `--owner-id`, `--workspace-id`, `--account-id`, `--client-id`, `--callback-port`, and `--json`. Read-only configured status uses `status --enabled` with the same fields. Live application activation requires the exact pair `ONYX_GOOGLE_WORKSPACE_LIVE_V1=true` and `ONYX_GOOGLE_WORKSPACE_CONNECTOR_V1=true` plus matching `ONYX_GOOGLE_WORKSPACE_*` public bindings. This audit did not execute those setup/consent commands.

## Focused current tests

Python: `C:\Python313\python.exe`. `PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. All tests below used `--noconftest` and disabled the pytest cache provider.

Initial first-suite attempt without explicit basetemp: **15 passed, 52 setup errors**. A single-test diagnostic confirmed `PermissionError: [WinError 5]` scanning `%TEMP%\pytest-of-ppetr`. A fresh unused explicit basetemp fixed the setup issue without ACL changes.

Successful commands (absolute unique basetemps were checked absent before pytest):

```powershell
python -m pytest --noconftest -p no:cacheprovider -q --tb=short --basetemp 'C:/Users/ppetr/AppData/Local/Temp/onyx-integrations-20260905-0e033113fca645bb9a43664605d24e9a' tests/test_plugin_docker_sandbox_v1.py tests/test_social_video_asset_v1.py tests/test_social_publish_v1.py tests/test_social_content_strategy_v1.py tests/test_plugin_runtime_v1.py
# 67 passed in 5.94s

python -m pytest --noconftest -p no:cacheprovider -q --tb=short --basetemp 'C:/Users/ppetr/AppData/Local/Temp/onyx-integrations-extra-20260905-9bbc113a919c4baab2c88e0b87060744' tests/test_ffmpeg_runtime_v1.py tests/test_mark_lii_audio_parity_v1.py tests/test_google_workspace_connector_v1.py tests/test_phase8_microsoft_graph_device_bootstrap_v2.py tests/test_device_pairing_v1.py tests/test_device_mesh_v1.py
# 122 passed, 1 skipped in 4.00s
```

For repetition, generate new unused basetemps; pytest may remove an existing basetemp. The platform skip is Google's case-sensitive path-binding test on Windows. Total successful coverage: **189 passed, 1 skipped**. These fixtures exercise sandbox command constraints, authenticated plugin IPC, timeout cleanup, publication consent/idempotency/reconciliation, video binding, FFmpeg resolution, audio contracts, Google/Graph contracts and pairing/mesh boundaries. They do not perform live Docker, Graph, Google OAuth, social publication or remote-device operations.

`npm run lint` and `npm run typecheck` were attempted: both exit 1 / ENOENT because this Python snapshot has no root `package.json`. No npm gates, full regression or release qualification are claimed. Test temporary artifacts and npm diagnostic logs are outside the source tree; no cleanup of another worker's files was attempted.

## Scope, implementation log and self-review

- `git status --short` and `git log --oneline -5` report that this snapshot is not a Git repository. No commit/revert was performed; source provenance must not be inferred from a Git HEAD here.
- IDS search found `CAPABILITY_AUDIT_2026-09-04.md` and current CLI/tests. `squads/` and `components/` are absent in this snapshot. **REUSE** existing probes/tests; **ADAPT** the earlier evidence-bound audit format; **CREATE** only this specifically authorized dated report, because the previous report does not contain today's live response, MAC/token checks or FFmpeg resolution diagnosis.
- No edits to main/ui/core, releases, owner configuration or security settings. No send/upload/OAuth-consent operation. The subsequently authorized benign Gemini request contacted its provider. The separately authorized Docker startup launched existing Desktop/backend processes; its service-start attempt failed and its engine stayed unavailable.
- Self-review applied to evidence: checked three failure modes (PATH link mistaken for runtime readiness; stored tokens mistaken for live authorization; fixture/package files mistaken for installed execution). Checked three boundaries (daemon absent; stale/missing device selections; inaccessible shared pytest temporary root). Tested safe alternatives where applicable and retained the limits in the findings.
- Story implementation/code/build checklist items are not applicable to this read-only audit. Existing focused tests and this report are the deliverables; no story or release was marked certified. Separate checklist/log files were not written because only this document is authorized.
