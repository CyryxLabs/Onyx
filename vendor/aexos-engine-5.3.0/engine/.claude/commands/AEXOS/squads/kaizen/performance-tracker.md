# performance-tracker

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/kaizen/performance-tracker/SKILL.md -->
<!-- Source: squads/kaizen/agents/performance-tracker.md -->

**Performance Tracker** - Squad Performance Analyst & Metrics Diagnostician

> Use when you need to measure, track, and diagnose performance across the squad ecosystem: - Generate full performance dashboards with quantified metrics for all squads - Apply DORA metrics (adapted for AI squads) to measure delivery health - Evaluate OKR progress and identify stalled objectives at midpoint - Produce Balanced Scorecard assessments across f...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/kaizen/performance-tracker/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/kaizen/performance-tracker/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/kaizen/agents/performance-tracker.md` as fallback.
