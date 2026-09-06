# Onyx V98 / 1.2.0 — source remediation, not installed GO

Date: 2026-09-05. Owner request: resolve outstanding items in the consolidated
sprint. Status: **InProgress / NO-GO**. This record adds evidence; V96 and V97
manifests are preserved byte-for-byte. V97 was a source candidate, never installed.

## Concrete corrections

1. HUD48 and packaged HUD17 bind the existing conversation projection corrections:
   latest reply visible, full history retained, current selector reversible.
   All QML, humanoid web/pointcloud assets, palette and voice-preference bytes
   match their predecessors. This is not a humanoid redesign or an Orb change.
2. Advanced Operations24 authenticates the corrected UI, preserving Operations23.
   Existing registered historical routes in conftest now verify this exact
   successor; no hashes are substituted by this change. Additional tamper tests
   authenticate the successor itself. Historical suites remain separately open.
3. Capability callbacks no longer own the lock required by kill/revoke/status.
   A separate dispatch lock retains callback serialization. Active plugin
   execution receives a cancellation event; kill/close/disconnect latch it.
   Revoking one authenticated capability binding cancels only that execution.
4. Docker's cancellable path creates an inert hardened container before starting
   it, polls cancellation, reaps its client and removes that exact container.
   Cleanup/reap timeout or failed confirmation becomes `cleanup_unverified`,
   not a false claim that execution was terminated. No image was pulled and no
   real container was launched during these controlled tests.
   Protocol reference: https://docs.docker.com/reference/cli/docker/container/create/
5. Real host-to-plugin testing exposed a production incompatibility: the nucleus
   validated operation names as identity IDs, rejecting declared namespaces such
   as `execute.test.echo`. A bounded operation-specific grammar fixes this;
   identity validation, constructor-closed registry, scope and digest checks stay.
6. The approval inbox rejected the current broker's nonce-bearing envelope.
   It now accepts only the exact legacy envelope or exact current envelope,
   validates a supplied 32-hex nonce and includes it in the authenticated digest.
   Modified nonce/content and unknown fields fail before reaching the callback.
   Actual owner-approval-to-dispatch and kill-during-approval tests now pass.

The earlier audio drain/reconnection fix is included in this source candidate;
physical speech responsiveness remains unverified in the installed executable.

## Tests and review

- Final explicit functional/security/voice/feature ring: **1209 passed,
  3 skipped, 328 subtests passed, 78.73 seconds**. Ran with `--noconftest` to
  exercise the selected current test bodies directly, without historical
  projection hooks. This is deliberately NOT labelled the complete suite.
- JUnit: `C:/MAAX_Assistant/onyx-v98-functional-qualification-results.xml`.
- The three skips require native macOS Keychain, Linux Secret Service and POSIX
  dirfd behavior. Windows tests cannot certify those platforms.
- Security/governance/cancellation ring: 198 passed before the final combined run.
- Ruff passed for new successor modules/tests and changed runtime authority,
  cancellation and governance files.
- Runtime source staging passed, including packaged HUD17 and package hygiene.
- Independent read-only review found two issues in the initial cancellation
  patch (cleanup timeout classification and scoped revoke); both were fixed,
  regression-tested and re-reviewed with no further critical finding reported.
  This review is not CodeRabbit, native Docker proof or a security certification.

### Full-suite limit, not concealed

The first canonical suite stopped after **3 failed / 23 passed**, 155.59 seconds:
the historical operations route still authenticated stale `ui.py` bytes.
JUnit: `C:/MAAX_Assistant/onyx-v97-full-suite-results.xml`.
After the explicit successor update, a second canonical run still showed failures
and was interrupted for bounded diagnosis; it produced no conclusive final JUnit.
No full-suite PASS is claimed, and unknown remaining failures are not all assumed
to be historical. Current-release/historical-suite reconciliation remains a gate.

One stale assertion in `test_governance_nucleus_v1` expected a ledger append to
reject an authenticated cleanup marker. Existing recovery code (identical in the
installed predecessor) already recovers a committed, anchored append. The test
now checks that cleanup succeeds but the mutation kill remains effective both
live and after restart. No ledger recovery/security implementation was weakened.

## Release and owner data

- Source version: 1.2.0; successor source authority: V98, following V97/V96.
- Installed version remains **1.1.31 / V96**. Executable rechecked unchanged:
  `46a03deee0362bd7d0a5c5326e0fa4b78d0971a3ea16e849cae854fea620c758`.
- No new executable/installer has been built or installed by this continuation.
- Temporary runtime-source staging was regenerated. The prior installed app,
  release packages, rollback evidence, owner vault and credentials were retained.
- No calls, social publication, Telegram delivery, OAuth consent, microphone
  volume changes or firewall modifications occurred in this continuation.
- Authenticode/public distribution remains separate from source qualification.

## Outstanding work — still required for requested GO

- Complete suite reconciliation, build, package qualification, rollback/install,
  then physical voice tests on AB13X and JOUNIVO, interruption/reconnect/session
  endurance and measured response latency. Camera/hand/mobile also remain live gates.
- Plugin Docker daemon and approved pinned image; real isolation and cleanup proof.
- Phone Link execution and bidirectional call audio, durable outcomes, isolated
  receptionist/callback; Android and iPhone qualification with approved recipients.
  `phone_call_prepare` remains a preview, not a telephone call.
- Approved PDF-to-Telegram delivery with receipts/reconciliation; additional
  official social/video transports. These include missing CODE, not just OAuth.
- Owner OAuth/credentials and exact live targets for email/calendar/social tests.
- Second Brain provider-context consent remains off; indexing is local and wired,
  but no whole-vault cloud upload or silent activation was performed.
- Integrated employee tasks, specialist outputs, budgets, research/Argos and
  Guardian operational evidence from the consolidated GO matrix remain open.

The remaining story checkboxes stay open. A passing source ring is not 100%
behavioral parity, all-feature completion, installed operation or public GO.
