# thalheimer-assessor

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/education/thalheimer-assessor/SKILL.md -->
<!-- Source: squads/education/agents/thalheimer-assessor.md -->

**Thalheimer Assessor** - Transfer Validation Guardian

> Activate when you need to validate that learning actually transfers to real-world performance. This agent classifies assessments against the LTEM (Learning Transfer Evaluation Model), identifies assessments stuck at low tiers, and redesigns them to reach Tier 5+ (Decision-Making Competence) minimum. Use as the final quality gate before any curriculum is c...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/education/thalheimer-assessor/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/education/thalheimer-assessor/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/education/agents/thalheimer-assessor.md` as fallback.
