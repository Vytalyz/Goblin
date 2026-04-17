# Codex Capability Index

This catalog is the repo's source of truth for what the Codex-native operator may rely on.

| Capability | Source | Type | Stability | Windows | Critical Path | Sandbox | Approval | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Codex Automations | `https://developers.openai.com/codex/app/automations` | `automation` | `stable` | `supported` | `guarded` | `workspace_write` | `human_gate` | `synced` |
| Codex Config Reference | `https://developers.openai.com/codex/config-reference` | `config` | `stable` | `supported` | `allowed` | `not_applicable` | `not_applicable` | `synced` |
| Codex Hooks | `https://developers.openai.com/codex/hooks` | `hook` | `experimental` | `disabled` | `forbidden` | `workspace_write` | `not_applicable` | `synced` |
| Codex Overview | `https://developers.openai.com/codex` | `docs` | `stable` | `supported` | `allowed` | `not_applicable` | `not_applicable` | `synced` |
| Codex Rules | `https://developers.openai.com/codex/rules` | `rules` | `experimental` | `supported` | `guarded` | `workspace_write` | `rules_prompt` | `synced` |
| Codex Skills | `https://developers.openai.com/codex/skills` | `skill` | `stable` | `supported` | `allowed` | `workspace_write` | `rules_prompt` | `synced` |
| Codex Subagents | `https://developers.openai.com/codex/concepts/subagents` | `subagent` | `stable` | `supported` | `guarded` | `workspace_write` | `rules_prompt` | `synced` |
| Codex Windows Guidance | `https://developers.openai.com/codex/windows` | `docs` | `stable` | `supported` | `allowed` | `not_applicable` | `not_applicable` | `synced` |
| Codex Workflows | `https://developers.openai.com/codex/workflows` | `workflow` | `stable` | `supported` | `allowed` | `workspace_write` | `rules_prompt` | `synced` |
| Codex Worktrees | `https://developers.openai.com/codex/app/worktrees` | `automation` | `stable` | `supported` | `allowed` | `workspace_write` | `rules_prompt` | `synced` |
| Automation Specs | `automations` | `automation` | `repo_defined` | `supported` | `guarded` | `workspace_write` | `human_gate` | `synced` |
| Repo-local Codex Agents | `.codex/agents` | `agent` | `repo_defined` | `supported` | `allowed` | `workspace_write` | `rules_prompt` | `synced` |
| Repo-local Codex Assets | `.codex` | `config` | `repo_defined` | `supported` | `allowed` | `workspace_write` | `rules_prompt` | `synced` |
| Codex Skill Sources | `.codex/skills-src` | `skill` | `repo_defined` | `supported` | `allowed` | `workspace_write` | `rules_prompt` | `synced` |
| Repo Config Stack | `config` | `config` | `repo_defined` | `supported` | `allowed` | `workspace_write` | `rules_prompt` | `synced` |
| Python Control Plane | `src/agentic_forex` | `control_plane` | `repo_defined` | `supported` | `allowed` | `workspace_write` | `rules_prompt` | `synced` |
| Internal Workflow Roles | `agents/roles` | `workflow` | `repo_defined` | `supported` | `guarded` | `workspace_write` | `rules_prompt` | `synced` |
| Internal Workflow Skills | `skills` | `skill` | `repo_defined` | `supported` | `guarded` | `workspace_write` | `rules_prompt` | `synced` |
| Internal Workflow Definitions | `workflows` | `workflow` | `repo_defined` | `supported` | `guarded` | `workspace_write` | `rules_prompt` | `synced` |
| Runtime Skill Mirrors | `.agents/skills` | `skill` | `repo_defined` | `supported` | `allowed` | `workspace_write` | `rules_prompt` | `synced` |

## Notes

### Codex Automations
- Source: `https://developers.openai.com/codex/app/automations`
- Repo applicability: Background automation is allowed only through paused, manually validated worktree specs.
- Summary: Automations – Codex app | OpenAI Developers | Automations | @layer theme, base, components, utilities; Automations – Codex app | OpenAI Developers .cursor-blink:where(.astro-76h4scq2){display:inline-block;min-width:.65ch;padding:0 .05ch;animation:cli-cursor-blink 1.4s steps(2,start) infinite}:where(

### Codex Config Reference
- Source: `https://developers.openai.com/codex/config-reference`
- Repo applicability: Defines supported repo-local Codex config keys used by the operator layer.
- Summary: Configuration Reference – Codex | OpenAI Developers | Configuration Reference | @layer theme, base, components, utilities; Configuration Reference – Codex | OpenAI Developers .cursor-blink:where(.astro-76h4scq2){display:inline-block;min-width:.65ch;padding:0 .05ch;animation:cli-cursor-blink 1.4s steps(2,start) infinite

### Codex Hooks
- Source: `https://developers.openai.com/codex/hooks`
- Repo applicability: Hooks are telemetry-only and must stay out of the critical path on Windows.
- Summary: Hooks – Codex | OpenAI Developers | Hooks | @layer theme, base, components, utilities; Hooks – Codex | OpenAI Developers .cursor-blink:where(.astro-76h4scq2){display:inline-block;min-width:.65ch;padding:0 .05ch;animation:cli-cursor-blink 1.4s steps(2,start) infinite}:where(.astro-76h

### Codex Overview
- Source: `https://developers.openai.com/codex`
- Repo applicability: Defines the top-level Codex capability surface that the repo-local operator can rely on.
- Summary: Codex | OpenAI Developers | Codex | @layer theme, base, components, utilities; Codex | OpenAI Developers @layer components{._Layout_1iiup_1{position:relative;display:block;flex-shrink:0;transition-property:height,width}._Layout_1iiup_1[data-clip=true]{overflow:hidden}._Layout
- Notes: Primary entrypoint for official Codex capability discovery.

### Codex Rules
- Source: `https://developers.openai.com/codex/rules`
- Repo applicability: Repo-local command allowlisting controls how Codex can escalate outside the workspace sandbox.
- Summary: Rules – Codex | OpenAI Developers | Rules | @layer theme, base, components, utilities; Rules – Codex | OpenAI Developers .cursor-blink:where(.astro-76h4scq2){display:inline-block;min-width:.65ch;padding:0 .05ch;animation:cli-cursor-blink 1.4s steps(2,start) infinite}:where(.astro-76h

### Codex Skills
- Source: `https://developers.openai.com/codex/skills`
- Repo applicability: Repo-tracked skills are the reusable workflow layer for the Codex operator.
- Summary: Agent Skills – Codex | OpenAI Developers | Agent Skills | @layer theme, base, components, utilities; Agent Skills – Codex | OpenAI Developers .cursor-blink:where(.astro-76h4scq2){display:inline-block;min-width:.65ch;padding:0 .05ch;animation:cli-cursor-blink 1.4s steps(2,start) infinite}:where(.as

### Codex Subagents
- Source: `https://developers.openai.com/codex/concepts/subagents`
- Repo applicability: Supports shallow, explicit parallel exploration and review work for the Codex operator.
- Summary: Subagents – Codex | OpenAI Developers | Subagents | @layer theme, base, components, utilities; Subagents – Codex | OpenAI Developers .cursor-blink:where(.astro-76h4scq2){display:inline-block;min-width:.65ch;padding:0 .05ch;animation:cli-cursor-blink 1.4s steps(2,start) infinite}:where(.astro
- Notes: Subagents are explicit-only and must stay shallow in this repo.

### Codex Windows Guidance
- Source: `https://developers.openai.com/codex/windows`
- Repo applicability: Windows constraints govern hook usage and sandbox behavior in this repo.
- Summary: Windows – Codex | OpenAI Developers | Windows | @layer theme, base, components, utilities; Windows – Codex | OpenAI Developers .cursor-blink:where(.astro-76h4scq2){display:inline-block;min-width:.65ch;padding:0 .05ch;animation:cli-cursor-blink 1.4s steps(2,start) infinite}:where(.astro-7

### Codex Workflows
- Source: `https://developers.openai.com/codex/workflows`
- Repo applicability: Defines how Codex should structure multi-step work around the deterministic kernel.
- Summary: Workflows – Codex | OpenAI Developers | Workflows | @layer theme, base, components, utilities; Workflows – Codex | OpenAI Developers .cursor-blink:where(.astro-76h4scq2){display:inline-block;min-width:.65ch;padding:0 .05ch;animation:cli-cursor-blink 1.4s steps(2,start) infinite}:where(.astro

### Codex Worktrees
- Source: `https://developers.openai.com/codex/app/worktrees`
- Repo applicability: Worktrees are the default isolation model for parallel or unattended Codex work in this repo.
- Summary: Worktrees – Codex app | OpenAI Developers | Worktrees | @layer theme, base, components, utilities; Worktrees – Codex app | OpenAI Developers .cursor-blink:where(.astro-76h4scq2){display:inline-block;min-width:.65ch;padding:0 .05ch;animation:cli-cursor-blink 1.4s steps(2,start) infinite}:where(.a

### Automation Specs
- Source: `automations`
- Repo applicability: Paused automation specs define unattended work without mutating the repo by surprise.
- Summary: Directory surface with 6 files under automations.

### Repo-local Codex Agents
- Source: `.codex/agents`
- Repo applicability: Defines the custom agent roles that make Codex the planning authority.
- Summary: Directory surface with 8 files under .codex\agents.

### Repo-local Codex Assets
- Source: `.codex`
- Repo applicability: Holds repo-local Codex config, agents, skill sources, and rules.
- Summary: Directory surface with 19 files under .codex.

### Codex Skill Sources
- Source: `.codex/skills-src`
- Repo applicability: Source-of-truth skill definitions for repo-local operator workflows.
- Summary: Directory surface with 8 files under .codex\skills-src.

### Repo Config Stack
- Source: `config`
- Repo applicability: TOML policy/config files remain the deterministic kernel authority.
- Summary: Directory surface with 11 files under config.

### Python Control Plane
- Source: `src/agentic_forex`
- Repo applicability: Contains the deterministic research, governance, parity, and audit kernel.
- Summary: Directory surface with 176 files under src\agentic_forex.

### Internal Workflow Roles
- Source: `agents/roles`
- Repo applicability: Legacy internal strategist/critic role briefs remain migration inputs and bounded helpers.
- Summary: Directory surface with 9 files under agents\roles.

### Internal Workflow Skills
- Source: `skills`
- Repo applicability: Legacy workflow-engine skills remain preserved for migration and bounded helper use.
- Summary: Directory surface with 3 files under skills.

### Internal Workflow Definitions
- Source: `workflows`
- Repo applicability: Legacy workflow graphs remain helper paths, not the primary planner.
- Summary: Directory surface with 4 files under workflows.

### Runtime Skill Mirrors
- Source: `.agents/skills`
- Repo applicability: Runtime-discoverable skill mirrors installed for Codex repo scanning.
- Summary: Directory surface with 8 files under .agents\skills.
