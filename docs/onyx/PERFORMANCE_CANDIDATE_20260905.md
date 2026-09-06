# Performance continuation — 2026-09-05

Status: implementation candidate, NOT installed or release-qualified.

Owner approved documentary normalization and continuation, preserving design/voice.
Pre-normalization story SHA256: 9414f4795f905f4c1e0bd55106128fd042b27f11019f2a5e1e790d0a1da2fc11.
Exact archive: C:/MAAX_Assistant/Onyx-Release-Backups/v96-story-before-performance-20260905.md.
Installed version remains 1.1.31. Release manifest and predecessor renderers were not edited.

## Implementation

- Adaptive pacer: maximum 60, downgrade tiers 30/24, reduced motion 12, inactive 0; sustained cheap frames required for recovery. Frequent state requests cannot bypass pacing.
- V6 renderer successor keeps geometry/materials/voice unchanged and exposes renderedFrames, measuredFps and targetFps separately. V7 compositor skips copies of already presented frames, retaining alpha and health checks.
- UI trace shows newest entries first; separate historyText retains 48 chronological entries. Onyx response log updates transcript. Actual owner History callback verified directly; previous installed mouse-click discrepancy not claimed fixed.
- No active QML selector was promoted. ui.py source changes require successor acceptance/closure binding before running or packaging the authenticated current source. Historical hashes were not rewritten to conceal this prerequisite.

## Tests

- Node pacer assertions PASS: cap, pacing, measurement, downgrade/recovery, reduced motion, inactivity.
- Qt projection plus existing text latency tests: 5 PASS using --noconftest and an explicit disposable basetemp. These are isolated component checks, not a replacement for repository gates.
- Chromium real render test PASS: alpha-zero corner, progressing distinct frames, inactive render stops. Longer sample: measured render rate 19.67 FPS, target 30, renderedFrames 256, presentedFrames 210, rejectedFrames 46 (includes initial formation). This is headless Chromium, not installed native performance or proof of 60 FPS.
- Ruff on new Python tests PASS.
- Initial pytest used an inaccessible default temporary directory (WinError 5); explicit workspace basetemp resolved it. Initial test property typo callbackError was corrected to actual lastCallbackError.
- Default conftest qualification was not completed successfully; one run had the temp error and another was interrupted. No full regression pass claimed.
- npm lint/typecheck/test attempted: ENOENT, no package.json in this source snapshot. Not PASS.

## Next gates and limits

1. Diagnose native rendering cost and compare candidate with baseline under the same load; measure audible response, not merely arrival of network audio.
2. Promote selected candidate through new source/package acceptance and authenticated closure, then qualify/build/install successor. No hot patch to installed binary.
3. Retest native History, Setup readiness, long conversation and camera physically.
4. Continue original capability gates: Google consent, official social/video adapters and live activation, approved plugin sandbox, operational squads and governed Guardian service remain incomplete/unverified as recorded in the original audit.

No new provider latency improvement, physical audio certification, operational parity, or guaranteed 60 FPS is claimed by this continuation.
