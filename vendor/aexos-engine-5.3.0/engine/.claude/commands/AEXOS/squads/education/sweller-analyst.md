# sweller-analyst

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/education/sweller-analyst/SKILL.md -->
<!-- Source: squads/education/agents/sweller-analyst.md -->

**sweller-analyst** - Analyze and optimize cognitive load in instructional materials. Identify extraneous load sources. Maximize germane load. Apply the 15+ CLT instructional effe...

> Use this AEXOS agent when the task matches its responsibility.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/education/sweller-analyst/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/education/sweller-analyst/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/education/agents/sweller-analyst.md` as fallback.
