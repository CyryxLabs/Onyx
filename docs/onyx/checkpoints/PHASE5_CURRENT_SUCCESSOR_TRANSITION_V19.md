# Phase 5 current successor transition V19

Status: **FROZEN SOURCE — CLEAN REBUILD AND INSTALLED ACCEPTANCE REQUIRED**  
Transition: `tests/fixtures/phase5_current_successor_transition_v19.json`  
Transition SHA-256: `8c1332c1e33ccfc392abddec4c7863b0bffb9290428c02d77e2c42bbbec87782`  
Domain root: `c0dc1de139e86a46a046aac5799edd6e990b3ce033d3fa9e75094574a18c1b38`

V19 preserves exact V18 and all earlier successors. The Phase 5 historical
delta is `main.py`: microphone capture now queues input only while a provider
session is active. The bound voice-continuity seam owns microphone and playback
for the process lifetime while Gemini transport sessions rotate independently.
No tool, mission, permission, memory, model, voice or execution authority is
changed.

A real Gemini Native Audio source execution survived `GoAway`, established a
second receive session, remained responsive and recorded one microphone plus
one playback start. The integrated 35-suite selection passed 252 tests; the
V12-to-V21 activation chain remains 136/136. Installed V18 failed at this same
boundary, so no V18 runtime result transfers to V19.
