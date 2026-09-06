# Onyx formal release contract

Status: controlling fail-closed publication policy.

This contract distinguishes a package that is useful for local diagnosis from
a public Cyryx Labs release. A successful build, smoke test, artifact upload or
SBOM generation is not by itself a formal release.

## Common gates

Every public release must satisfy all of the following in one merged,
artifact-bound evidence set:

- every platform manifest declares `release_class: formal`;
- `diagnostic_exceptions` is exactly empty;
- `release_trust` is present and names the exact platform policy;
- repository publication approval and legal/notices approval are independently
  and explicitly `true`;
- the required target matrix is complete, with no unexpected target manifest;
- every artifact byte, bundle inventory, build-input seal and platform
  `SHA256SUMS` record reconciles exactly;
- the final SPDX SBOM and its digest reconcile to every manifest artifact and
  archive member;
- product license and third-party notice files are present, substantive and
  contain no placeholder markers.
- exact native lifecycle receipts prove clean install, reinstall, upgrade,
  app-only uninstall, rollback and owner-data preservation for every required
  target;
- the exact Windows Setup and portable hashes have a terminal eight-hour soak
  receipt with all thresholds passing and zero application errors;
- the `onyx-final-evidence-review` and `onyx-public-release` GitHub environments
  have independent required reviewers with self-review prevented; the durable
  qualification approval is bound to the retained qualification run and its
  exact source build.

Local builds remain available. Without `--formal-release`, their manifest is
`untrusted-candidate` (or `diagnostic-incomplete` when a required diagnostic
format is deliberately omitted), never `formal`.

## Windows

Formal artifacts are exactly one per-user `Setup.exe`, one portable ZIP and one
Windows trust-evidence JSON file. Before either package is created, every EXE,
DLL and PYD in the bundle is Authenticode-signed. The finished Setup is signed
after compilation. Native Windows verification must establish:

- `signtool verify /pa /all /v` succeeds;
- `Get-AuthenticodeSignature` returns `Valid`;
- signer thumbprint and subject match the imported Cyryx Labs public-trust code
  signing certificate;
- an RFC 3161 timestamp certificate is present;
- evidence records are bound to exact hashes and cover every PE in the ZIP;
- each covered PE contains an Authenticode certificate table.

The certificate table and the build-produced JSON are diagnostic evidence only;
they cannot grant eligibility. A separate native Windows verification job
downloads the exact Windows artifact, reruns both native trust providers over
Setup and every PE member of the portable ZIP, and emits a receipt bound to the
manifest, Setup, portable archive, workflow run and commit. The publish job may
consume that receipt only from the exact retained build run and after recomputing
its SHA-256; a locally forged receipt or a non-Windows attestation fails closed.

A tag build fails before artifact upload if the Windows PFX secret, password,
trusted certificate, Cyryx Labs identity, Code Signing EKU or timestamp is
absent. A self-signed or merely present signature is not formal evidence.

## macOS

Formal macOS release requires the native supported host and exact DMG plus the
macOS release evidence, app/DMG notary submissions and notary logs. The gate
requires Developer ID signing, hardened runtime, Apple notarization accepted
for both app and DMG, stapling, `spctl` assessment and exact DMG hash binding.
Ad-hoc signing is always `untrusted-candidate`.

## Linux

Formal Linux artifacts are exactly DEB, TAR.GZ and AppImage for each target
architecture. Linux signing is not silently inferred. The current approved
policy is explicitly `unsigned-approved`: publication requires the independent
repository variable `ONYX_LINUX_UNSIGNED_RELEASE_APPROVED=true`, plus exact
platform checksums, the final artifact/member-bound SPDX SBOM and all common
gates. Without that explicit policy and approval, Linux output is an untrusted
candidate and cannot be published.

## Workflow authority

Tag builds force `--formal-release` on all matrix jobs. Windows and macOS secret
imports run before packaging; Linux policy approval is checked before build.
After every target and the independent Windows trust receipt exist, the build
assembles `SBOM.spdx.json` and its digest exactly once from the complete merged
artifact set and retains them as `onyx-formal-sbom`. Tags build and retain
artifacts but do not publish automatically.

`.github/workflows/release-qualification.yml` accepts one successful exact
build run and a published prior version. It executes lifecycle gates on
ephemeral native Windows x64, macOS arm64, Linux x64 and Linux arm64 runners,
plus the uninterrupted eight-hour Windows installed-host soak. Its protected
`onyx-final-evidence-review` job emits `onyx-final-qualification-evidence`,
including build/qualification provenance, four lifecycle receipts, the
terminal soak and the independent-review receipt.

Publication is a separate explicit `publish_qualified` dispatch. It downloads
the exact retained build artifacts and exact qualification artifact by run ID;
it never rebuilds release bytes or regenerates the SBOM. Qualification
provenance binds both aggregate SBOM files by SHA-256. Publication verifies both
workflow paths, conclusions, head SHAs, manifest/artifact hashes, the trusted
Windows receipt, merged SBOM,
legal approval, target matrix, lifecycle/soak evidence and protected review
before `gh release create` or upload. Missing runner evidence, a mismatched run,
an unprotected approval variable or any byte mismatch fails closed.
