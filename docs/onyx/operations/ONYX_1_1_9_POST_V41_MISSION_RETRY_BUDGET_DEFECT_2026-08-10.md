# Onyx 1.1.9 post-V41 mission retry-budget defect

Status: **V41 RELEASE BLOCKER REPRODUCED; SOURCE CORRECTION TESTED**  
Date: 2026-08-10

## Installed V41 reproduction

The exact installed `core/missions.py` SHA-256 is
`7af0c456d14f3e8a3d6dcb49eca017521b386e5d6f519f9f8057abcab5111327`.
An isolated, provider-free diagnostic created a mission with `max_retries=0`,
consumed its only attempt into an unknown-outcome waiting state and requested
the explicit `retry` resolution. Installed V41 accepted the exhausted retry and
returned `running`; the next execution failed with
`Mission canonical step contract diverges`.

The candidate-bound receipt is:

`C:/MAAX_Assistant/Onyx-V41-Windows-Candidate-20260810/acceptance/installed-v41/mission-retry-budget-defect-v41/ONYX_1_1_9_V41_INSTALLED_RETRY_BUDGET_DEFECT.json`

Receipt SHA-256:
`4d42fca8744222305950edd9a512ace818e7ccdb883f92587a1dd2d094e0073c`.
The diagnostic used isolated state, no provider and no network effects.

## Source correction

`MissionStore.resolve(..., "retry")` now checks the durable attempt count
against `max_retries + 1` before changing either the step or mission state. An
exhausted request raises `BudgetExceeded("retry budget exhausted")` and the
mission remains in its valid waiting state, allowing an explicit succeeded or
failed outcome resolution.

- Corrected `core/missions.py` SHA-256:
  `0f0f4890769486a3aaaf5b3e875adaee8f15e0339103e1fb40a62ac77fde190f`.
- Regression test file SHA-256:
  `a7ffa0e87977a86a51c18d494e8c989578f60f81808022665dbf73efebe5632a`.
- Focused mission suite: **63 passed**.

## Release consequence

The source correction is newer than the frozen V41 source and installed bytes.
It cannot be claimed by V41. V41 remains useful for the already-running HUD and
resource soak, but it cannot become the final release candidate. After the soak
finishes, the corrected source must receive a new authenticated transition,
freeze, build, install and proportional mission/recovery regression. No V41
hash or receipt may be rebound to that successor.

