# task-router

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/dispatch/task-router/SKILL.md -->
<!-- Source: squads/dispatch/agents/task-router.md -->

**Task Router** - Dynamic Task-to-Agent Router

> Use after wave-planner produces atomic tasks that need agent/model/enrichment assignment

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/dispatch/task-router/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/dispatch/task-router/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/dispatch/agents/task-router.md` as fallback.
