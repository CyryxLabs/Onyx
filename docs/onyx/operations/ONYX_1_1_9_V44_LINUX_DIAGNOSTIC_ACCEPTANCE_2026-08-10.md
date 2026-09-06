# Onyx 1.1.9 V44 Linux diagnostic acceptance

Date: 2026-08-10  
Candidate: Onyx 1.1.9 V44 Linux x64 diagnostic  
Decision: **DIAGNOSTIC BUILD PASSED; FORMAL/NATIVE RELEASE REMAINS NO-GO**

## Frozen source

- Source manifest:
  `C:/MAAX_Assistant/Onyx-V44-Source-Candidate-20260810.SOURCE_FREEZE.json`
- Source manifest SHA-256:
  `aabba800431f8e3acdbcd0bc6e4ade81578a012b9b86c113c7f1ccb514e46b0a`
- Source root SHA-256:
  `257d5afaf8d364117d5c560dd439653eefc57348a0cf4cacf413249d83c44df3`
- Source inventory: 2,694 files, 141,166,540 bytes.
- The container-native runner rechecked the complete inventory and aggregate
  before executing the build.

## Accepted diagnostic artifacts

Evidence directory:
`C:/MAAX_Assistant/Onyx-V44-Linux-Candidate-R3-20260810`

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `Onyx-1.1.9-Linux-x64.AppImage` | 586,799,608 | `ac90efabbd87edab236ef558ff10798ed2b3c65977194fdec70b8c4e7f2a1488` |
| `Onyx-1.1.9-Linux-x64.deb` | 469,186,424 | `3be460fce713a0624a03d3670a901f47cbb17fc929d76e2eb2f364b3dbe81750` |
| `Onyx-1.1.9-Linux-x64.tar.gz` | 631,765,915 | `0daedb354a16c621fce87791e9a6ad6d21fb4a178cb587adc1f9b42db0a87ded` |

Supporting evidence:

- build exit code: `0`;
- build log SHA-256:
  `9c0dc5a18a14d88176b2d5dc43a3ee9cbcbde7b4f33bf1fdcbeece23139551b2`;
- release manifest SHA-256:
  `959a29b181aad1f2b21ea3af39179990059f37ef1a3a79b86d47bccb35d496f8`;
- `SHA256SUMS-Linux-x64.txt` SHA-256:
  `2ceb8463ed4c1343f0246c8f08d836a0496025ffdc3f9dad5ea9bd057d8598de`;
- bundle inventory SHA-256:
  `8c9e6793a7b56d635ae39a907b515387039815325aa7995bf32a18bccfc12036`;
- bundle root SHA-256:
  `ebca7efd8d2862b2e546a26d66ba2ff0402c9a230086a1c9bb634325d43ac6af`;
- build-input seal root SHA-256:
  `20e88c10c9458145648b45a35a1f5698718b7a9aaef615e53dda136c826add61`.

The copied artifacts, bundle inventory and build-input manifest were checked
against both the release manifest and `SHA256SUMS`; no size or digest mismatch
was found.

## Passed gates

- Release-workflow V44 verifier passed inside the build container.
- PyInstaller bundle completed.
- Packaged fallback preflight passed.
- Native baseline startup smoke passed without provider, network or process
  calls.
- Portable-current negative-boundary startup smoke passed fail-closed with one
  read-only trusted Secret Service probe and no provider/network calls.
- TAR permission manifest passed for 8,023 entries.
- DEB permission manifest passed for 8,041 entries.
- AppImage permission manifest passed for 8,032 entries.
- Host-native structure gate passed.
- Baseline entrypoint smoke passed for every completed Linux artifact.
- Portable-current negative-boundary entrypoint smoke passed for every
  completed Linux artifact.

## Why this is not formal Linux readiness

The release manifest deliberately records:

- `release_class: untrusted-candidate`;
- `signing_policy: unsigned-untrusted`;
- diagnostic exception `linux_formal_policy_not_requested`;
- normal activation profile `portable-v8-fallback-capability-limited`;
- `capability_limited: true`.

The build log also exposes unresolved production-quality work:

- 35 PyInstaller missing-library warnings, including PulseAudio, Xtst, GTK 3
  and XCB/XKB desktop dependencies; the TIFF plugin also expects
  `libtiff.so.5`;
- 15 QML null-property warnings during UI teardown;
- missing AppStream metadata and `appstreamcli`;
- desktop categories contain two main categories;
- no representative native Linux desktop proof for GUI, microphone, natural
  Gemini Live voice, keyring persistence, single-instance behavior, signals,
  install/upgrade/uninstall/rollback or long-session stability.

These observations are release blockers or successor inputs. They are not
waived by the successful container build.

## Infrastructure note

The first V44 run used a Windows bind mount. It passed the packaged startup
smokes but was superseded before packaging because P9 file operations over the
multi-gigabyte bundle made the complete DEB/TAR/AppImage sequence impractical.
Its diagnostic log is preserved under
`C:/MAAX_Assistant/Onyx-V44-Linux-Candidate-R2-20260810`. The accepted R3 run
used the same verified V44 inventory in container-native storage and copied
only terminal artifacts/evidence back to the host.
