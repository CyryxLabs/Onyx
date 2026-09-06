# Onyx 1.1.9 third-party license review worklist

Status: **R10B TECHNICAL WORKLIST — LEGAL DECISION REQUIRED**  
Candidate: Windows x64 R10B / frozen V49 candidate  
Date: 2026-08-11

This document narrows the manual review required by
`LEGAL_RELEASE_APPROVAL_1.1.9.md`. It reports package metadata and shipped legal
files; it does not normalize ambiguous declarations, give legal advice or
approve distribution.

## Exact evidence boundary

- Bundle inventory SHA-256:
  `3cda30d4c3d91b41d41c31aec6ffcaf4ba1b2ab831f64decaed25cc0b2e72240`.
- Bundle root SHA-256:
  `d8ce24ddd991c114367707eb990caaf7e4119cd4650c99fed2ac8a56e8826635`.
- SPDX SBOM SHA-256:
  `b335a9a8b33f287bd9b8e91dba7d0ef20bfa8cf163701f2134bd8cb8ee799dd3`.
- Artifact-set root embedded in the SPDX inventory:
  `863890a09bd536e99b71ec487bd1c9e5920550f7964125a3a53d15c0ab212b2f`.
- Shipped runtime distributions: 116.
- Shipped bundle files: 7,451.
- Runtime-distribution legal-evidence files: 181.
- Distribution metadata is hash-bound by runtime-distribution root
  `62f72f4542015e69e160a255c0684ed0c3f9d65f2996075acdfd68fe64c82f25`.

The R10B inventory recognizes both `LICENSE` and `LICENCE` and includes the
hash-pinned primp graph notice plus supplemental evidence notices for odfpy,
WMI, PyGetWindow and win10toast. All 116 distributions therefore have at least
one recorded legal-evidence file and the syntactic missing-file count is zero.
That is packaging evidence, not a conclusion that the supplemental material
resolves the governing license or every redistribution obligation.

The SBOM deliberately retains `NOASSERTION` for legal license fields. Its
technical package list must not be rewritten as a legal conclusion solely from
wheel metadata.

## Triage result

| Review bucket | Count | Required decision |
|---|---:|---|
| Some package declaration present | 108 | Verify declaration against the shipped legal bytes and distribution obligations |
| `NOASSERTION` declaration | 8 | Identify the governing upstream license from authoritative material |
| At least one shipped legal-evidence file | 116 | Confirm the shipped file set is authoritative and complete for binary distribution |
| No shipped legal-evidence file | 0 | Syntactic packaging queue closed in V19; substantive decisions below remain |
| SPDX-valid simple or compound expression | 82 | Validate expression and obligations; do not auto-approve |
| Non-canonical label, prose, URL or ambiguous expression | 26 | Normalize only after reviewing authoritative license bytes |

The SPDX/non-canonical split above was recalculated from the exact R10B
`licenseDeclared` values using the SPDX license-expression symbol set. It is a
syntax classification only and is not a legal interpretation.

## `NOASSERTION` packages

| Package | Version | Shipped legal files |
|---|---:|---:|
| `colorama` | 0.4.6 | 1 |
| `importlib_metadata` | 8.7.0 | 1 |
| `itsdangerous` | 2.2.0 | 1 |
| `markdown-it-py` | 4.2.0 | 2 |
| `mdurl` | 0.1.2 | 1 |
| `odfpy` | 1.4.1 | 1 supplemental evidence notice |
| `pdfplumber` | 0.11.10 | 1 |
| `pycaw` | 20251023 | 1 |

## R10B tag-bound engineering reconciliation

The fail-closed decision packet
`docs/onyx/checkpoints/LEGAL_DECISION_PACKET_R10B_V1.json` (SHA-256
`ec123caaf2857f7298c67f2db47170e13e9b679e0d74030b05276040bf932106`)
binds the eight `NOASSERTION` rows to the exact R10B source, bundle, SBOM and
compliance receipt. Seven rows now have version-tag-bound upstream evidence
that matches the shipped legal bytes; `odfpy` remains substantively unresolved.

| Package | Engineering SPDX candidate | Exact comparison | Legal disposition |
|---|---|---|---|
| `colorama` 0.4.6 | `BSD-3-Clause` | Upstream tag bytes equal shipped bytes | `REQUIRED` |
| `importlib_metadata` 8.7.0 | `Apache-2.0` | Upstream tag bytes equal shipped bytes | `REQUIRED` |
| `itsdangerous` 2.2.0 | `BSD-3-Clause` | Upstream tag bytes equal shipped bytes | `REQUIRED` |
| `markdown-it-py` 4.2.0 | `MIT` | Both upstream tag files equal shipped bytes | `REQUIRED` |
| `mdurl` 0.1.2 | `MIT` | Upstream tag bytes equal shipped bytes | `REQUIRED` |
| `pdfplumber` 0.11.10 | `MIT` | Upstream tag bytes equal shipped bytes | `REQUIRED` |
| `pycaw` 20251023 | `MIT` | UTF-8 text equal after CRLF/LF normalization only | `REQUIRED` |
| `odfpy` 1.4.1 | None | Apache/GPL-family choice or combination unresolved | `REQUIRED` |

This is an engineering reconciliation only: the SBOM retains all eight
`NOASSERTION` declarations, `legally_approved` remains zero, and neither this
worklist nor the packet grants legal approval or public-release eligibility.

## Prior missing-file queue and R10B disposition

| Package | Version | R10B packaged evidence | Remaining decision |
|---|---:|---|---|
| `odfpy` | 1.4.1 | Supplemental evidence notice present | Resolve Apache/GPL choice or combination and required texts |
| `primp` | 1.3.1 | Native-crate graph notice present | Resolve the two package-local graph gaps and crate obligations |
| `PyGetWindow` | 0.0.9 | Supplemental evidence notice present | Bind the untagged upstream license to exact release 0.0.9 |
| `win10toast` | 0.9 | Supplemental evidence notice present | Resolve exact-release BSD/MIT conflict |
| `WMI` | 1.5.1 | Supplemental evidence notice present | Supply/approve complete version-bound MIT permission text |

`et_xmlfile` 2.0.0 actually ships `LICENCE.python` and `LICENCE.rst`;
`openpyxl` 3.1.5 ships `LICENCE.rst`. Their exact bundle hashes are now found
by the corrected detector, so neither belongs in the missing-file queue.

## Non-canonical declaration queue

The following metadata values require human normalization. Similar wording is
grouped for review efficiency; grouping is not a license conclusion.

| Metadata form | Packages |
|---|---|
| `MIT License`, MIT URL or embedded MIT prose | `beautifulsoup4`, `curl_cffi`, `hyperframe`, `mss`, `primp`, `WMI` |
| `Apache 2.0` or long Apache label | `distro`, `google-auth`, `opencv-python`, `tenacity` |
| Generic `BSD`, `BSD 3-clause` or embedded BSD prose | `pandas`, `pyasn1_modules`, `PyAutoGUI`, `PyGetWindow`, `PyMsgBox`, `pyperclip`, `pyreadline3`, `PyRect`, `pywinauto`, `qrcode`, `win10toast`, `xlrd` |
| PSF alias | `defusedxml`, `pywin32` |
| Multiple or unspecified license | `pypdfium2`, `python-dateutil`, `socksio` |

`pypdfium2` ships 19 legal files and explicitly mentions dependency licenses;
it must be reviewed as a multi-license payload rather than collapsed to one
identifier. `python-dateutil` says only `Dual License`, and `socksio` says
`UNKNOWN`; neither is sufficient for approval.

## Candidate primary-source findings

These findings reduce the technical research queue; they are not legal
approval and do not change the SBOM's `NOASSERTION` fields. Each immutable tag
or release source still needs to be reconciled to the exact bytes shipped in
the final rebuilt artifact.

| Package | Candidate finding | Primary source and captured evidence | Review disposition |
|---|---|---|---|
| `colorama` 0.4.6 | BSD 3-Clause text | [Upstream tag `0.4.6` license](https://github.com/tartley/colorama/blob/0.4.6/LICENSE.txt); raw UTF-8 SHA-256 `cac35c02686e5d04a5a7140bfb3b36e73aed496656e891102e428886d7930318` | Candidate `BSD-3-Clause`; confirm the shipped legal file is byte-equivalent or substantively complete |
| `pdfplumber` 0.11.10 | MIT text | [Upstream tag `v0.11.10` license](https://github.com/jsvine/pdfplumber/blob/v0.11.10/LICENSE.txt); raw UTF-8 SHA-256 `0d48994da4d1321e395b5e64a724ed4dec63fb96b88ac5b88fc014771e690821` | Candidate `MIT`; confirm the shipped legal file is byte-equivalent or substantively complete |
| `pycaw` 20251023 | MIT text | [Upstream tag `v20251023` license](https://github.com/AndreMiras/pycaw/blob/v20251023/LICENSE); raw UTF-8 SHA-256 `e58ee129029562365d1c38a7537fa271cb5f569f9d698965cfc0c1450efb01eb` | Candidate `MIT`; confirm the shipped legal file is byte-equivalent or substantively complete |
| `odfpy` 1.4.1 | Upstream release source says redistribution under the Apache license **and** GPL v2-or-later; PyPI also exposes multiple license classifiers | [Upstream tag `release-1.4.1` setup source](https://github.com/eea/odfpy/blob/release-1.4.1/setup.py); raw UTF-8 SHA-256 `6cdac33d204d9b0192916cfb740259345469d3fd2800644a7848bac27c087f28` | Remains unresolved: determine the governing choice/combination and ship the required authoritative texts before approval |
| `PyGetWindow` 0.0.9 | Exact PyPI sdist metadata declares generic `BSD`; current upstream repository contains BSD 3-Clause text | [Exact PyPI release](https://pypi.org/project/PyGetWindow/0.0.9/); sdist SHA-256 `17894355e7d2b305cd832d717708384017c1698a90ce24f6f7fbf0242dd0a688`; [current upstream license](https://github.com/asweigart/PyGetWindow/blob/master/LICENSE.txt) | Candidate `BSD-3-Clause`, but the repository has no version tag; bind the license bytes to the 0.0.9 release before shipping them |
| `win10toast` 0.9 | Exact wheel metadata says `License: BSD` but classifies MIT; current upstream repository contains MIT text | [Exact PyPI release](https://pypi.org/project/win10toast/0.9/); wheel SHA-256 `44e5afa1001de88a0ee533872231521fa67c7d144f39974089af242d9c4620a4`; [current upstream license](https://github.com/jithurjacob/Windows-10-Toast-Notifications/blob/master/LICENSE) | Remains unresolved because exact-release metadata conflicts and the repository has no release tag |
| `WMI` 1.5.1 | Exact sdist README identifies Tim Golden copyright 2003–2015 and the MIT license URL | [Exact PyPI release](https://pypi.org/project/WMI/1.5.1/); sdist SHA-256 `b6a6be5711b1b6c8d55bda7a8befd75c48c12b770b9d227d31c1737dbf0d40a6` | Candidate `MIT`; acquire and ship a complete authoritative permission text with the version-bound copyright before approval |
| `primp` 1.3.1 | Python metadata says MIT, but the exact native Rust source distribution contains multiple embedded MIT, Apache-2.0 and ISC license files for vendored/transitive components | [Exact PyPI release](https://pypi.org/project/primp/1.3.1/); sdist SHA-256 `b04a5941bf9c876d011c5defaf5a25be093d56e7270b8da52c9788b9df2a829a`; [upstream tag `v1.3.1`](https://github.com/deedy5/primp/tree/v1.3.1) | Do not collapse to the top-level `MIT License` label; generate and review a complete crate-level attribution/license inventory for the shipped native binary |

The R10B dependency set adds `markdown-it-py` 4.2.0 and `mdurl` 0.1.2 to the
existing `NOASSERTION` queue. The bundle carries two legal files for the former
(`4a2260d6...e484` and `792c48c5...d473`) and one for the latter
(`7c605df6...f955`). `importlib_metadata` and `itsdangerous` also carry exact
legal bytes. These files narrow review but do not authorize changing
`NOASSERTION` without an approved decision.

The tag refs were independently resolved from each upstream Git repository at
review time. A future upstream branch change therefore cannot substitute for
the exact version evidence recorded above.

`scripts/primp_license_bundle.py` is now wired into the release build. It
hash-pins the exact primp 1.3.1 sdist, safely rejects archive links/traversal,
resolves only the platform-filtered Cargo normal/build graph, copies discovered
crate legal files, records Cargo.lock checksums and emits deterministic
`OnyxPrimpNativeLicenseBundle.v1` evidence plus a notice in the packaged primp
metadata directory. Its subprocess boundary now decodes Cargo's JSON contract
as UTF-8 explicitly; the focused generator selection passes 5 tests.

A real Windows x64 graph run emitted 237 selected normal/build packages and 435
legal files. Inventory SHA-256 is
`8e0cdf6eff5575f9b001d147bb70b71c4986022ffa0d10bac78abaa6f78934fb`;
the legal-file root is
`84ac185a128f2cf5b46edb181660b2e05692c622186e212fc25d193143042fdf`.
Two rows have no package-local legal bytes: `alloc-stdlib==0.2.2` declares
`BSD-3-Clause`, while the `primp-python==1.3.1` workspace crate declares
`NOASSERTION` in Cargo metadata even though the exact Python distribution
metadata identifies MIT and a sibling `primp` crate carries `LICENSE-MIT`.
Those facts are evidence, not a conclusion; both rows require explicit legal
disposition before approval and must remain visible in the rebuilt bundle.

### Missing-file supplemental evidence generator

`scripts/missing_distribution_license_bundle.py` is now wired into the release
build for `odfpy` 1.4.1, `WMI` 1.5.1, `PyGetWindow` 0.0.9 and `win10toast`
0.9. It hash-pins each exact PyPI artifact, rejects archive traversal, and adds
the exact release evidence plus clearly labelled untagged repository
supplements where applicable. Every packaged notice states that this is
technical evidence, not legal approval.

A real network-bound run emitted `OnyxMissingDistributionLicenseBundle.v1`
inventory SHA-256
`4a24d29d0752ba39936e5d275dba3001e6cc10aefecbcf24e9ee3602141ff327`:
odfpy 3 files, WMI 2, PyGetWindow 4 and win10toast 3. The generator and combined
inventory/hygiene selections pass 4 and 22 tests respectively. R10B packages
this evidence and has a syntactic missing-file count of zero, but that result
does not close the odfpy dual-license choice, WMI incomplete permission text,
PyGetWindow untagged-version binding or win10toast BSD/MIT conflict.

## Closing requirements

1. Resolve every `NOASSERTION`, missing-file and non-canonical row against an
   authoritative upstream license or durable acquired-rights record.
2. Reconcile the approved results to `THIRD_PARTY_NOTICES.md` and every final
   platform artifact, including platform-specific dependencies not present in
   this Windows candidate.
3. Record any attribution, source-offer, relinking, redistribution or store
   obligation and verify the release package satisfies it.
4. Complete `LEGAL_RELEASE_APPROVAL_1.1.9.md` only after the final rebuilt
   artifacts and their new hashes are available.
