# Onyx current capability status V2

Updated: 2026-09-05.
Current candidate: **Onyx 1.2.0 Windows x64 engineering candidate**.
Installed predecessor: **Onyx 1.1.31 / V96**.
Trust: **unsigned-untrusted**. Public release: **NOT RELEASED**.
Candidate-bound physical/live operation: **UNVERIFIED**.

The source candidate is not the installed product. Source remediation is in
progress, including voice continuity, Second Brain, business documents,
Telegram PDF delivery, governance and cancellation. Remaining feature gaps
and owner/provider gates are tracked in `GO_SINGLE_SPRINT_20260905.md` and
`SECOND_BRAIN_PHONE_STATUS_20260905.md`. No 100% parity or operational GO is claimed.

| Candidate | implemented | source-wired | host-wired | tested | packaged | installed | provider-tested | signed | released |
|---|---|---|---|---|---|---|---|---|---|
| Onyx 1.2.0 Windows x64 | `PARTIAL` | `PARTIAL` | `PARTIAL` | `FOCUSED_PASS_FULL_PENDING` | `NO` | `NO` | `UNVERIFIED` | `NO_UNSIGNED_UNTRUSTED` | `NO` |

`CURRENT_CAPABILITY_STATUS_V1.md` preserves the dated 1.1.10 evidence; it is not
current product authority. `CURRENT_RELEASE_STATUS.md` remains the historical
formal **1.1.9 R15B NO-GO**. `POST_INSTALL_1_1_31_20260905.md` records installed
V96 evidence. Their results must not be relabelled as evidence for 1.2.0.

Build only after source qualification using
`python scripts/build_release.py --version 1.2.0`. Preserve the V96 rollback
artifacts and owner data. Packaging must run its own native smoke and integrity
checks; a source manifest or a passing simulated provider test is insufficient.
