# Guardian and FFmpeg review fixes

Date: 2026-09-05. Bounded follow-up to the three reproduced review findings.
Parent story: `docs/stories/ONYX-AGENT-EMPLOYEE-TWO-SPRINTS-V1.story.md`.

## Changes

`core/network_guardian_v1.py` obtains the system directory from
`kernel32.GetSystemDirectoryW` with declared ctypes argument/result types. It
rejects failed/truncated results and relative, UNC or parent-traversal paths.
SystemRoot and PATH do not participate in executable selection. A native 64-bit
process uses the returned system directory directly. On 32-bit Windows processes,
`IsWow64Process` selects the native `Sysnative` alias only under WOW64; failure to
determine architecture rejects execution. Non-Windows application still fails
before dispatch. Native API absence also fails closed rather than guessing a path.

`core/ffmpeg_runtime_v1.py` checks directory ancestry with lstat before resolving
the containment root or candidate. Symlink directories and Windows reparse/junction
directories are rejected, including the WinGet package root and Links ancestors.
The narrowly allowed final WinGet executable symlink still works when its directory
chain and package root are regular and its target remains contained.

Each eligible executable is probed with `-hide_banner -encoders`, no shell or stdin,
and a three-second timeout. Both actual audio and video encoder entries must exist;
the encoder-list legend is excluded. Thus the restricted Playwright binary also
fails if copied/renamed, while normal FFmpeg is not excluded by filename. This is
an audio/video baseline, not a claim that every codec/media operation is certified.

The probe uses a 32-entry cache keyed by canonical path, device/inode, size,
mtime/ctime and a 60-second monotonic time bucket. Repeated calls reuse the result;
changed executables invalidate it and temporary failures are retried in a later
bucket. File identity is rechecked after probing. A configured rejected candidate
may still fall back to another eligible PATH candidate, preserving prior resolution
behavior. No provider, model or media rendering is invoked by the probe.

## Evidence

- Focused suite: **82 passed in 1.18 s**, no skips on this host.
- Existing readiness inventory regression: **1 passed**, 57 deselected, 0.19 s.
- Ruff on the four scoped Python files: passed.
- Native Windows API with `SystemRoot=.` returned the existing
  `C:\Windows\system32\netsh.exe`; pointer size was 8 bytes. No netsh command ran.
- Real installed WinGet FFmpeg 7.1.1 resolved successfully. Its second resolution
  reused the probe cache (one miss followed by one hit).
- Real installed Playwright `ffmpeg-1011/ffmpeg-win64.exe`, explicitly configured
  with PATH fallback disabled, returned unavailable.

Tests cover controlled ctypes API errors/architecture results; poisoned environment;
native API lookup; actual symlink escapes at package, Packages, Links and explicit
parents; Windows reparse attributes; allowed final WinGet links; encoder-less,
video-only and failed probes; renamed/full executables; timeout; identity changes
and cache expiry. Real-runtime tests use installed binaries when available, and
skip explicitly on hosts lacking those optional integration runtimes.

Reproduce (choose a new basetemp path):

```powershell
python -B -m pytest --noconftest -p no:cacheprovider --basetemp <unique-temp-path> tests/test_network_guardian_v1.py tests/test_ffmpeg_runtime_v1.py -q
python -B -m pytest --noconftest -p no:cacheprovider tests/test_readiness.py -k linux_optional_inventory -q
python -B -m ruff check --no-cache core/network_guardian_v1.py core/ffmpeg_runtime_v1.py tests/test_network_guardian_v1.py tests/test_ffmpeg_runtime_v1.py
```

The required npm lint/typecheck/test commands were attempted; each returned ENOENT
because this Python snapshot has no package.json. No full-suite/typecheck or release
pass is claimed. WOW64 behavior is tested through controlled API results, not a
32-bit live process. Firewall ownership and enforcement logic were not broadened;
all mutation tests use injected runners. No live firewall or account writes occurred.

## Scope and implementation log

IDS searched existing native-directory calls, runtime resolvers, reparse defenses,
and the corresponding tests before editing. The existing memory-store reparse
pattern informed the lightweight stat check without coupling the resolver to SQLite.

| File | Decision | Reason |
| --- | --- | --- |
| `core/network_guardian_v1.py` | ADAPT | Replace only executable lookup; preserve ownership and enforcement boundaries. |
| `core/ffmpeg_runtime_v1.py` | ADAPT | Harden existing containment and add cached capability baseline. |
| `tests/test_network_guardian_v1.py` | ADAPT | Reuse injected firewall runner; add controlled native API tests. |
| `tests/test_ffmpeg_runtime_v1.py` | ADAPT | Extend path fixtures with probe/cache and optional real-runtime tests. |
| This evidence document | CREATE | Separate implementation/evidence record; parent owns story and release closure. |

[AUTO-DECISION] Probe capabilities rather than blacklist filenames, preventing false
positives for general FFmpeg builds with names such as ffmpeg-win64.exe.

Self-critique 5.5 covered relocated trust roots, API failure accidentally dispatching
a relative executable, and stale cache/legend rows inventing capability. Cases cover
WOW64, probe timeout, unavailable runtimes, and mutation during probing. Self-critique
6.5 verified focused tests, real native/runtime observations, unchanged UI and no new
dependency. Full story DoD, Google closure and release regeneration remain with parent.

`ui.py` SHA-256 before and after was identical:
`F9348AC74AC805EFDDC66FAF34EAFA8E264C1F82F380361E29EE14E31B42A62A`.
No UI, HUD, QML, voice, Google closure, release or acceptance manifest was edited.
