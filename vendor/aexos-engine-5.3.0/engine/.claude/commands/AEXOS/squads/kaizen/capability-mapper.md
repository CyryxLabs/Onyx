# capability-mapper

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/kaizen/capability-mapper/SKILL.md -->
<!-- Source: squads/kaizen/agents/capability-mapper.md -->

**Capability Mapper** - Competency Gap Analyst & Resource Strategist

> Use when you need strategic visibility over the agent ecosystem's capabilities: - Map all existing capabilities across squads, agents, tools, MCPs, and APIs - Detect competency gaps where domains have no specialist coverage - Determine where a capability sits on the evolution axis (build vs adopt) - Recommend which expert minds to clone next (recruit) - I...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/kaizen/capability-mapper/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/kaizen/capability-mapper/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/kaizen/agents/capability-mapper.md` as fallback.
