# Onyx — blocker remediation and qualification handoff

Date: 2026-09-05. Source candidate: **1.2.0 / V99 preparation**.
Installed predecessor: **1.1.31 / V96**, preserved. Overall decision: **NO-GO**.

This is the pre-seal engineering record, not an installation or live certificate.
Subsequent qualification results belong in a separate report. V98 and earlier
sealed evidence must not be rewritten to match these source changes.

## Corrections in this continuation

- Removed exponential duplicate historical-verifier traversal. Deduplication is
  limited to one outer verification transaction; no cached hashes or authority
  survive into the next verification. Exceptions are not converted into success.
- Successor test subprocesses now retain both success and failure per exact test
  selection, have a bounded timeout and reject recursive execution cycles.
  Recursive assertion excerpts are bounded to 12,000 characters plus an explicit
  omission marker, retaining the beginning and final summary. Failure status is
  unchanged; this prevents repeated nested reports from multiplying into megabytes.
- Recovered four authentic historical R11 files from the retained predecessor.
  Every recovered byte matches its previously pinned digest. These are isolated
  fixtures, not replacements for current runtime files or new historical hashes.
- Advanced Operations V23's obsolete positive claim has an explicit V24
  successor. Current V24 source is authenticated on every invocation, including
  when its test result was already cached. Actual byte-tampering regression and
  independent read-only replay confirmed rejection after a previous success.
- Added a closed source-test succession registry for 37 exact obsolete release,
  documentation and HUD claims. All 61 historical/current-test bindings remain
  authenticated. Current V99 source verification is mandatory before execution;
  while V99 is unsealed these routes intentionally cannot pass.
- Added two exact HUD36/package5 positive-test successor routes to HUD48/package17.
  Both original negative/staging tests and the existing canonical exclusion list
  remain unchanged. All 11 old/current bindings and all three current validators
  are checked before consulting the suite cache. No old visual design is restored.
- Current documentation now distinguishes source 1.2.0 from installed 1.1.31.
  Historical 1.1.10 and formal 1.1.9 evidence remains historical, not relabelled.
- Current visual tests use HUD48/package17, preserving the predecessor's visual
  hashes. The accessibility test still requires one final QML root and one host.
  The macOS policy test checks both actual signing-expression outcomes instead
  of depending on source-code line wrapping. No humanoid, layout, palette or voice
  asset was changed by this continuation.

## New usable source capability: business PDF delivery

`core/business_document_delivery_v1.py` connects existing generated invoice,
quote and proposal PDFs to the official Telegram document transport. It exposes
`preview`, `send`, `status` and `reconcile`; this is an owner CLI, not a newly
certified conversational tool in the installed application.

All commands require explicit owner, workspace, account, chat and operation ID.
The PDF comes from the generated-document ledger by request ID and is checked
against its recorded number and SHA-256. Local paths and linked files are checked,
and upload content is an immutable byte snapshot with a 10 MiB budget.

Example templates, run from the source directory (replace every placeholder):

```powershell
python -m core.business_document_delivery_v1 --help
python -m core.business_document_delivery_v1 preview --owner OWNER --workspace WORKSPACE --account ACCOUNT --chat CHAT --operation-id DELIVERY_ID --output-dir "C:\approved\documents" --request-id GENERATION_REQUEST_ID
python -m core.business_document_delivery_v1 send --owner OWNER --workspace WORKSPACE --account ACCOUNT --chat CHAT --operation-id DELIVERY_ID --output-dir "C:\approved\documents" --request-id GENERATION_REQUEST_ID --outbox "C:\approved\delivery\outbox.sqlite3" --enable-telegram
python -m core.business_document_delivery_v1 status --owner OWNER --workspace WORKSPACE --account ACCOUNT --chat CHAT --operation-id DELIVERY_ID --outbox "C:\approved\delivery\outbox.sqlite3"
```

Preview/status do not contact Telegram. Send requires an already configured
native-vault token and exact interactive terminal confirmation of the file's
request digest and destination. There is no token command-line argument or
`--yes`. Approval expires after 120 seconds and is revoked afterward. No account
or token was created in this execution.

The durable outbox deduplicates operations and preserves uncertain delivery as
reconciliation, without automatic resend. Reconciliation is an explicit owner
attestation after independently checking the destination, not a Telegram query.
An accepted provider response binds the receipt to the locally uploaded PDF;
Telegram does not return the PDF SHA-256 for independent remote-content proof.

## Evidence collected before sealing

| Check | Result and boundary |
| --- | --- |
| R11 recovery, Inbox11/12/13/15 and helpers | 349 passed; local regression |
| Advanced Operations succession and tampering | 9 passed; independent narrow replay also passed |
| CLI, Telegram documents/text, macOS policy and current accessibility | 162 passed; synthetic transport, offscreen HUD |
| Current runtime ring: regression, missions, learning, memory, documents, integration contracts, plugin cancellation, voice stream ownership and conversation projection | 613 passed, 3 skipped, 280 subtests; local/synthetic checks, not physical/provider certification |
| Active documentation/HUD/runner contracts | 19 passed; focused source tests |
| Closed source-succession registry | 6 passed; current source intentionally unsealed |
| Bounded successor-runner behavior | 14 passed; failure/cycle/timeout diagnostics retained |
| Final pre-seal HUD/source succession, runner, Operations and V2 status ring | 60 passed in 12.58 s; temporary tamper roots, no installation |
| Broad diagnostic run | 44,798 passed, 12 failed, 32 skipped; stopped at failure limit, not final qualification |
| Additional diagnostic remainder | 8 failures and 8 fixture errors; explicit file selection included already-superseded HUD suites normally excluded by canonical collection; not canonical evidence |
| Last diagnostic partition | 759 passed, 17 skipped, 138 subtests, 20 failures; all 20 contained the intentionally unsealed V99 rejection; not final qualification |
| npm lint/typecheck/test | Unavailable: this Python snapshot has no package.json; not passes |
| Ruff: actions, core, memory, scripts, tests, main.py and ui.py | Passed |

Diagnostic runs overlapped source corrections. They identify causes but cannot
certify the final snapshot. Focused totals overlap and must not be summed into
a unique total. Run fresh canonical regression and V99 tamper checks after seal.

## Remaining release and operational gates

1. Finish current source corrections, authenticate all successor bindings, seal
   V99 once, run canonical regression and package smoke tests.
2. Build and install the qualified successor with V96 rollback preserved. Neither
   source fixes nor a source manifest imply the running V96 executable changed.
3. Verify speech/response, interruption, reconnection and session duration using
   AB13X and JOUNIVO physically. Earlier playback-drain correction remains source
   only until installed. Device enumeration is not proof of a working conversation.
4. Complete real camera/hand calibration, rendering stability and mobile checks.
5. Supply owner OAuth consent and exact approved test targets for e-mail,
   calendar, social and Telegram. Implement missing social/video adapters and
   prove provider effects; transport simulations are not live receipts.
6. Qualify a real plugin in an approved running Docker sandbox. The last daemon
   check failed; no unknown containers or images were started.
7. Complete Phone Link call execution, bidirectional audio and recovery on both
   Android and iPhone. A paired Android UI and call briefs do not implement this.
8. Complete installed agent-task execution, memory/context consent, web/Argos,
   specialist squads and governed Guardian acceptance from the existing GO matrix.
9. Public formal distribution additionally needs signing credentials and its
   release procedure. A local unsigned candidate is a distinct, limited gate.

No call, publication, real message delivery, OAuth consent, firewall change or
new installation was performed while creating this pre-seal record. No 100%
operational parity, physical voice recovery or full GO is certified here.
