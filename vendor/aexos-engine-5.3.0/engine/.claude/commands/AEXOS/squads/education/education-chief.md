# education-chief

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/education/education-chief/SKILL.md -->
<!-- Source: squads/education/agents/education-chief.md -->

**Education Chief** - Education Engineering Orchestrator

> Use when creating complete learning journeys for any domain. Orchestrates the full pipeline: Triage → Research → Diagnosis → Architecture → Design → Validation → Delivery.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/education/education-chief/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/education/education-chief/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/education/agents/education-chief.md` as fallback.
