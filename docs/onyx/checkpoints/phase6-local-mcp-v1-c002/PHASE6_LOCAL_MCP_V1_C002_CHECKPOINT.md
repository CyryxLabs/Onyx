# Phase 6 Local MCP V1 C002 dependency reacceptance

Status: **reaccepted against Activation V10 C003; isolated/default-off; not
live; not a Phase 6 exit**.

The Local MCP V1 implementation and its six candidate artifacts remain
byte-identical to candidate 001 and retain artifact root
`c0efe67f8e28fb6444456d535f482c5af783d20508fcb48a618dd3b3ce693f6f`.

Candidate 001 historically froze
`core/onyx_live_activation_v10.py` at
`608d38456cdd4ac1f4b2c7e1128fce9feec1725422f204370fed58b27db79cc8`.
That historical evidence is preserved. C002 supersedes only this dependency
anchor with the final Activation V10 candidate 003 source and its accepted E6
envelope:

- V10 source:
  `546842aeceb8fc5839d0782658ea4272d4bea999b786b96d38d7968c419a2ee7`;
- V10 C003 manifest:
  `b22459a5315370f179089cf67d501a687305c2147d2c68ef132575326d47e236`;
- V10 C003 artifact root:
  `5f1b32f01fe7a481f27062b90e5cbbf9816a7b6306547b7a0fe7ddf2a26a56c4`;
- V10 C003 E6 findings: P0/P1/P2/P3 all zero.

The other four frozen anchors are verified unchanged. The gate reproduces all
27 Local MCP focused tests. It performs no network/provider call, opens no MCP
process outside the deterministic test fixture, changes no live wiring and
does not activate Onyx.

Rollback is omission of this additive reacceptance root. Candidate 001 and its
historical E6 record are never rewritten.
