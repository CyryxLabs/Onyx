# rosenshine-teacher

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/education/rosenshine-teacher/SKILL.md -->
<!-- Source: squads/education/agents/rosenshine-teacher.md -->

**Rosenshine Teacher** - Master of Effective Instruction

> Activate when designing or auditing individual lessons. This agent ensures every lesson follows the 10 Principles of Instruction — the most research-backed set of teaching practices. Use when lessons feel disorganized, when learners struggle despite good content, or when you need to convert expert knowledge into effective instruction.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/education/rosenshine-teacher/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/education/rosenshine-teacher/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/education/agents/rosenshine-teacher.md` as fallback.
