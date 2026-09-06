# klein

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/deep-research/klein/SKILL.md -->
<!-- Source: squads/deep-research/agents/klein.md -->

**Gary Klein** - Father of Naturalistic Decision Making - Expert Pattern Analyst & Sensemaking Specialist

> Use for interpreting ambiguous or contradictory research findings, pattern recognition across data sets, sensemaking from complex inputs, pre-mortem analysis of research plans, insight discovery, and any task requiring expert judgment about what the evidence MEANS

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/deep-research/klein/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/deep-research/klein/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/deep-research/agents/klein.md` as fallback.
