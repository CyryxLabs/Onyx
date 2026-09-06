# fsrs-scheduler

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/education/fsrs-scheduler/SKILL.md -->
<!-- Source: squads/education/agents/fsrs-scheduler.md -->

**FSRS Scheduler** - Spaced Repetition Architect

> Activate when you need to design optimal review schedules for long-term retention. This agent applies FSRS algorithm principles to determine when concepts should be reviewed, how intervals should grow, and how to handle forgotten material. Use when building flashcard systems, review schedules, or any curriculum that requires retention beyond the lesson it...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/education/fsrs-scheduler/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/education/fsrs-scheduler/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/education/agents/fsrs-scheduler.md` as fallback.
