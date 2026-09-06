# react-eng

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/apex/react-eng/SKILL.md -->
<!-- Source: squads/apex/agents/react-eng.md -->

**Kent** - Design Engineer — React/Server Components

> Use when you need to: - Design React component architecture with proper composition patterns - Implement Server Components (RSC) and decide server vs client boundaries - Write tests that test user behavior, not implementation details - Categorize and manage state (server, UI, form, URL state) - Build custom hooks with correct abstraction levels - Implemen...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/apex/react-eng/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/apex/react-eng/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/apex/agents/react-eng.md` as fallback.
