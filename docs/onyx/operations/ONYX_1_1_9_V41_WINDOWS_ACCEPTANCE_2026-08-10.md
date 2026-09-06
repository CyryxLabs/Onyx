# Onyx 1.1.9 V41 Windows acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** This remains exact V41 historical
> evidence. R10B is the current installed candidate; use
> `../CURRENT_RELEASE_STATUS.md` and
> `../DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md` for current truth.

Status: **INSTALLED DIAGNOSTIC ACCEPTANCE IN PROGRESS**  
Candidate: **Onyx 1.1.9 Windows x64 V41 / activation V24**  
Date: 2026-08-10

This record binds the current Windows evidence to the exact V41 source and
artifacts. It does not convert an unsigned diagnostic candidate into a formal
release and does not substitute Windows evidence for Linux or macOS evidence.

## Traceable source and artifacts

| Item | Exact evidence |
|---|---|
| Source freeze | `C:/MAAX_Assistant/Onyx-V41-Windows-Candidate-20260810`; 2,661 files; 139,821,052 bytes; root `12e86bab2a009c624e900db2bb9a3e981ca05fe098b5cdd7ee3a9e1ca3c5f7cb` |
| Source-freeze manifest | `C:/MAAX_Assistant/Onyx-V41-Windows-Candidate-20260810.SOURCE_FREEZE.json`; SHA-256 `0731de38d909d3826e0dc21d72424401997a6ed43a8c2ff8f964a327554174c4` |
| Git revision recorded by freeze | `355504cb86e97e368dc575f9968ecf4c0fabe994` |
| Phase 5 transition | V43 fixture SHA-256 `90decf307197888f9f4ee2ab54c5dd8105fbacaafcf0792048db6cecff264b27`; root `528496a97111468c7a12ca649ea3f92c130f351ffdfcbdf735a90da38ec3a2d9` |
| Release Workflow transition | V41 root `ec1040dd9ef0dfad012a9609b77835a2251819a11e2340529407b2e952d8f950` |
| Bundle inventory | SHA-256 `668769957e2d3955be920e69fe935cfbe0c9d6a852e24126a551625c641f1f1b`; 7,469 files; bundle root `ee874ed32a21df3705f44cd3a101899d337fead2c362592fbb3a510d982e7e4d` |
| Setup | SHA-256 `8ef1fb8197761cfe75055fb321920945aa33b391d1dfa5eb30e7121de3a20202` |
| Portable | SHA-256 `0cdcf87ad6c37d5ada9c32b4fe8c802d5589cea4471c687f2b1444babf13d86d` |
| Release manifest | SHA-256 `d1e15e237191303297ef18b5899e7b20b3e1535640e57d9b8b19e87d0e930adf` |
| SHA256SUMS | SHA-256 `89a9761c463563ec2796a50fb8fd56d63695a38f77512828e92082adeab0a546` |
| Installed executable | `%LOCALAPPDATA%/Programs/Cyryx Labs/Onyx/Onyx.exe`; SHA-256 `2373bd78c67f9b5dfc5e8101dc2945f29710365f3dbb6e94a2dc0dc39069def2` |

The Setup, portable archive and installed executable are not Authenticode
signed. They are diagnostic acceptance artifacts only.

## Completed Windows observations

- V39-to-V41 in-place installation returned exit code 0. The candidate-bound
  installation log is `acceptance/installed-v41/upgrade-v39-to-v41-install.log`
  with SHA-256
  `ae6090338550e3cf0166e89e4971ee8ef36ec6933d6f5433f8e8879ef8d380b0`.
- The installed inventory matched the V41 bundle; the uninstaller-owned files
  are the expected installer additions rather than unbound application bytes.
- The installed process started and remained responsive. Startup evidence is
  `ONYX_V41_INSTALLED_STARTUP.png`, SHA-256
  `22865c0f71d86e6ab41b44e6cd281501e6ccb5c56f465a3fa36bbca7138d1128`.
- The intended provider returned a visible response. Evidence is
  `ONYX_V41_TEXT_PROVIDER_RESPONSE.png`, SHA-256
  `232718626dfa9f3631fd16abe793f462b4a9779c1468b4fc666741d5abb3c853`.
- `Call me Sir` produced PREPARED and COMMITTED owner-profile journal events,
  and the HUD projected `Sir`. Evidence is
  `ONYX_V41_OWNER_NAME_SIR_COMMITTED.png`, SHA-256
  `1885aebdaca34489f3e245e4ee3ab875d401b445ab23af17485d1a7bcbac8acb`.
  This is a text-command persistence observation; physical microphone mutation
  and post-restart persistence remain open.
- Thirty-two repeated Windows UI Automation traversals after the provider
  response each returned the expected 25 descendants. No WER application error
  or Qt termination was observed. This closes the V39 detached-root regression
  for the observed V41 session, not the long-session gate.
- Runtime logs recorded the Qt event loop, microphone capture, playback and
  Gemini Native Audio connection/receive path. An owner-heard acoustic-quality
  confirmation and cancellation/offline behavior are still required.
- Installed mission acceptance imported the exact packaged `core/missions.py`
  (`7af0c456...1327`) and the embedded `memory.store` bytecode from `Onyx.exe`.
  Representative create/run/audit, pause/cancel and crash/recovery/explicit-
  retry flows passed with no blind replay. Receipt SHA-256:
  `e1ce42bd83cc503ba8b7f598b1bc718fd62eaf5fce1ced040360c3e7c18114a7`.
- A separate exhausted-budget diagnostic reproduced a V41 release blocker:
  `resolve("retry")` accepted a retry after the valid attempt budget was spent,
  and the next run failed with `Mission canonical step contract diverges`.
  Receipt SHA-256:
  `4d42fca8744222305950edd9a512ace818e7ccdb883f92587a1dd2d094e0073c`.
  The source correction is tested but is not present in V41.

## Active long-session gate

The installed process is intentionally left running while
`scripts/monitor_windows_long_session.py` collects the required 28,800 seconds.
The mutable receipt is:

`C:/MAAX_Assistant/Onyx-V41-Windows-Candidate-20260810/acceptance/installed-v41/ONYX_1_1_9_V41_WINDOWS_LONG_SESSION_RECEIPT.json`

It must remain `in_progress` until the full duration is observed. Only the final
receipt may close the gate. The monitor requires responsiveness, zero Windows
application errors, average whole-host CPU no greater than 1.5%, working set no
greater than 786,432,000 bytes, private memory no greater than 1,610,612,736
bytes and working-set growth no greater than 268,435,456 bytes.

## Open Windows acceptance

1. Complete the full-duration soak without closing or restarting Onyx.
2. After the soak, restart the exact installed bytes and prove `Sir` persists.
3. Repeat the owner-name mutation through the physical microphone.
4. Confirm natural Gemini speech acoustically, including cancellation and
   offline/error behavior with no system-voice success substitution.
5. Freeze, build and install a successor containing the exhausted-retry budget
   correction, then repeat proportional mission/recovery acceptance.
6. Execute resident upgrade, uninstall, rollback and data-retention decisions
   on disposable clean Windows hosts.
7. Sign the final Windows artifacts and produce native trust receipts.
