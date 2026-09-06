# Phase 5 current successor transition V20

Status: current source authority; Windows rebuild and installed acceptance
required.

V20 preserves the exact V19 record and changes only the current SHA-256 binding
for `scripts/build_release.py`. Runtime authority does not change. The release
builder now treats platform-absent supplemental distribution metadata as absent
while continuing to reject wrong versions and duplicate metadata.

- V20 transition SHA-256:
  `8ea87bb7a12bd2343bc9d4bc381c627b27c9155a24aa1eb76f47466bea2773e6`
- V20 current root:
  `5465c8628191bc735e92738de42cbf94b5d1b064f593b6ee81b38d060f9f9d13`
- Exact V19 predecessor SHA-256:
  `8c1332c1e33ccfc392abddec4c7863b0bffb9290428c02d77e2c42bbbec87782`
- Policy: historical records are not rewritten; runtime authority changes are
  false.

Linux diagnostic evidence may prove this packaging correction. It does not
transfer V19 Windows installation, rotation or soak evidence to V20.
