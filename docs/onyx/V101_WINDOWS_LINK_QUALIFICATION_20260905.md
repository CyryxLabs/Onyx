# V101 — Windows physical-link qualification successor

Source-only candidate, not installed/live/public GO. Preserve humanoid, layout,
palette and voice. V96 / 1.1.31 remains installed.

V100 source authentication passed (687 paths), but its canonical nested suite
failed five physical-link test setup checks: Windows readlink returned an
extended `\\?\` path while the expected target used an ordinary drive path.
The assertion failed before the real rejection verifier, so those tests do
not certify link protection. Its other 116 nested tests passed.
The focused outer gate stopped at 85 passed / 3 propagated failures.
Evidence: C:/MAAX_Assistant/onyx-v100-old-blocker-qualification.xml.

Original V100 source was preserved before successor edits:
C:/MAAX_Assistant/onyx-v100-source-evidence-20260905.zip, 689 entries,
each compressed entry independently read and hash-checked.
Archive SHA256: d66118cd954a4968f344a57965146e1f156caa1807f212c807357438710a98e8.
Fixture SHA256: ec9302df2b6bece061e4f0a0c62e922539e82d78d05b0295d27d9386d2241161.
Source root SHA256: 518b785ff485ab32d28d115d76bbcf8b4c23a7bf5dcfc885818977617f333574.
No old fixture, verifier, or test body is rewritten.

V101 retains all previous physical tamper targets and tests a genuine linked
file/ancestor only after a valid current source baseline. Resolved destination
identity and samefile checks replace raw path spelling equality; the exact
typed target-specific rejection remains mandatory. Test preparation exercises
the link helper before sealing to catch platform spelling defects early.

Registry V3 inherits all 122 V2 nodes and adds 86 V100 post-source nodes,
208 exact routes. Old bindings are preserved, and fresh source/HUD/package
authentication still precedes the test cache. Historical fixture dependencies
are not run for replaced nodes; current autouse fixtures and exact node IDs
are retained. No wildcard, skip or collection exclusion is added.

Build and staged source admission now require V101. This record is written
before final qualification; post-seal results belong in new external evidence.
All operational, private recovery-backup, installation and provider gates in
V100_BLOCKER_SUCCESSOR_20260905.md remain open unless later evidenced.
