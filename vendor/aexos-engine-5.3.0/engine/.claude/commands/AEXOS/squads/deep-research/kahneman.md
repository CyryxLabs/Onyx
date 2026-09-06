# kahneman

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/deep-research/kahneman/SKILL.md -->
<!-- Source: squads/deep-research/agents/kahneman.md -->

**Daniel Kahneman** - Nobel Prize Economics 2002 - Decision Quality Auditor & Bias Detector

> Use as FINAL mandatory QA gate. Audits all recommendations for cognitive biases using System 1/2 awareness, 12-Question Bias Checklist, MAP protocol, Decision Hygiene principles, and Premortem. NEVER present recommendations without bias audit.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/deep-research/kahneman/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/deep-research/kahneman/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/deep-research/agents/kahneman.md` as fallback.
