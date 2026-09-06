# Onyx 1.1.9 V20 Linux x64 diagnostic acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V20 container
> diagnostic evidence; it is not native Linux proof for the current candidate.
> See [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Status: diagnostic build and clean DEB installation passed; not formal native
Linux acceptance.

## Scope

An isolated 8,002-file source snapshot was overlaid only with the V20 release
builder correction, its regression tests and the pinned Linux validation image
definition. The run used Python 3.13.14, Debian Bookworm, Rust/Cargo 1.89.0 and
official appimagetool 1.9.1 SHA-256
`ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0`.

The validation image manifest-list SHA-256 was
`10c455515de1b341931b17fbe9833eaace43a81fac2539de2860fea977b242a0`;
its Rust base digest was
`948f9b08a66e7fe01b03a98ef1c7568292e07ec2e4fe90d88c07bb14563c84ff`.

## Results

- Selected Linux release suite: 66 passed, 2 skipped, 14 subtests passed.
- PyInstaller bundle and all three host artifacts built successfully.
- TAR permission manifest: 7,792 entries verified.
- DEB permission manifest: 7,810 entries verified.
- AppImage permission manifest: 7,801 entries verified.
- Baseline packaged startup smoke passed on every finished host-native
  entrypoint.
- Portable-current negative-boundary smoke passed limited/fail-closed at
  `pre_v10`, as declared by the artifact.
- `SHA256SUMS-Linux-x64.txt` validated every listed output.
- A separate Debian 12 clean image installed the DEB with package-manager
  dependencies, created an unprivileged user and passed native startup smoke.

## Exact outputs

- AppImage:
  `19ae2e6fd28d9f9a1a9e581fde954c559b3ccfba8892049f4a9312cfa6030ac9`
- DEB:
  `376389729a7cc676a933e5db0b5af4022ed4b35857dbb7025f2bef451b3152e2`
- TAR.GZ:
  `eaef3f9871f2ae8379f9a2d258453b22b77904ce6e2930a3318ed45d5a7a4f4b`
- Release manifest:
  `5f85055c3b281c2b741f63951e9262f3716bad88bbd6abe07e12d46e417c4539`
- Bundle inventory manifest:
  `2132bb60f930fe471937ccb68363fe1b9e4e2b08e7251e9399561cc9b5812b83`
- Bundle root:
  `783d60a1d7da6983946e6df8edd007674c28820b87419505735f763bb54c1e2c`
- First-party input-seal root:
  `a96646eec264162e4a455f8ecfea8af35e6044806d2f08620ac4abc76614f838`
- Build/test log:
  `16b7be1019d0c470b2d76e66ba8709014170df3f3172d2df53ca34b471b8e10c`

Evidence is retained under
`C:/MAAX_Assistant/Onyx-Linux-V19-Diagnostic-20260804/evidence-attempt6`.

## Non-transferable gaps

The release manifest correctly labels these artifacts `untrusted-candidate`.
The normal activation is the capability-limited V8 fallback and does not claim
V15-V19 parity. This container evidence does not prove a physical Linux
desktop, microphone, speaker, Secret Service session, systemd user-session
lifecycle, x64 reinstall/upgrade/rollback/uninstall, arm64 behavior, signing,
legal approval or independent review. It also does not qualify the V20 Windows
candidate.
