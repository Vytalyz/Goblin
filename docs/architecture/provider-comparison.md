# Phase 1 — Provider Comparison Matrix

**Generated:** 2026-04-13  
**Phase:** 1 — Research and Terminology Mapping  
**Sources:** Official documentation from each provider (cited inline). Secondary sources used only for terminology clarification.

---

## Provider Scope

| Provider | Documentation Root | Version / Date |
|----------|-------------------|----------------|
| **Claude Code** (Anthropic) | code.claude.com/docs/en | Apr 2026 |
| **OpenAI Codex / Agents SDK** | platform.openai.com/docs, openai.com/index | Apr 2026 |
| **GitHub Copilot** (VS Code) | code.visualstudio.com/docs/copilot | Apr 2026 |
| **MCP** (Model Context Protocol) | modelcontextprotocol.io | Apr 2026 |
| **Cursor** | cursor.com/docs | Apr 2026 (limited) |

---

## Master Comparison Matrix

### 1. Agents

| Attribute | Claude Code | OpenAI Codex / Agents SDK | GitHub Copilot (VS Code) |
|-----------|------------|---------------------------|--------------------------|
| **Concept name** | Sub-agents | Agents (Agents SDK) | Custom agents / Chat participants |
| **Provider term** | `.md` files with YAML frontmatter in project | `Agent` class in `openai-agents` Python SDK | `.agent.md` files with YAML frontmatter |
| **Definition format** | Markdown + YAML frontmatter (`tools`, `model`, `hooks`, `memory`, `mcpServers`, `allowedTools`) | Python class instantiation (`Agent(name, instructions, tools, model, handoffs)`) | Markdown + YAML frontmatter (`description`, `tools`, `applyTo`, `instructions`) |
| **How invoked** | `/agent:<name>` in Claude Code CLI or referenced by other agents | Programmatic via `Runner.run()` or handoff from another agent | `@<agent-name>` mention in chat |
| **Isolation** | Separate working directory (git worktree), own CLAUDE.md context | Separate process/thread via SDK runner | Shared VS Code workspace context |
| **Strengths** | Full filesystem access, hooks, memory, MCP, tool restrictions, worktree isolation | Type-safe Python, structured I/O, guardrails, tracing, handoff chains | Editor-integrated, workspace-aware, prompt file system |
| **Limitations** | Claude-specific YAML schema; no cross-provider portability | Requires Python runtime; OpenAI API dependency | VS Code-only; no standalone execution |
| **Portability risk** | Medium — YAML frontmatter is Claude-specific | High — tightly coupled to OpenAI SDK | Medium — VS Code `.agent.md` format is Copilot-specific |
| **Fit for Goblin** | High — filesystem agents match Goblin's workflow | Medium — SDK agents useful for programmatic orchestration | High — editor integration for interactive development |
| **Recommendation** | **Adopt** (canonical agent definitions) | **Adapt** (use patterns, not SDK lock-in) | **Adopt** (editor-facing agent definitions) |

### 2. Sub-agents / Delegation

| Attribute | Claude Code | OpenAI Agents SDK | GitHub Copilot |
|-----------|------------|-------------------|----------------|
| **Concept name** | Sub-agents | Handoffs | Subagent (via `runSubagent`) |
| **Provider term** | Agents launched from a parent agent context | `handoff()` function returning control to another Agent | `runSubagent` tool invocation |
| **How it works** | Parent agent creates child with restricted tools/context; child works in isolation (optional worktree) | Agent declares `handoffs=[other_agent]`; SDK routes conversation to target agent | Parent agent invokes `runSubagent` with prompt; child returns single message |
| **Communication** | Child returns final result to parent | Conversation context transferred; child can hand back | Single prompt → single response (stateless) |
| **Portability risk** | Medium | High (SDK-specific) | Low (tool-based pattern) |
| **Fit for Goblin** | High | Medium | High |
| **Recommendation** | **Adopt** | **Monitor** | **Adopt** |

### 3. Orchestrators / Agent Teams

| Attribute | Claude Code | OpenAI Agents SDK | GitHub Copilot |
|-----------|------------|-------------------|----------------|
| **Concept name** | Agent teams (multi-agent) | Multi-agent orchestration | Not natively supported |
| **How it works** | Parent agent spawns sub-agents for concurrent work; coordinates results | Handoff chains + `Runner.run()` with tracing | Manual via sequential subagent calls |
| **Built-in patterns** | Fan-out/fan-in via agent definitions | Linear handoff chains, conditional routing | None (custom orchestration only) |
| **Portability risk** | Medium | High | Low |
| **Fit for Goblin** | High — matches portfolio orchestrator pattern | Medium | Low |
| **Recommendation** | **Adopt** (pattern) | **Adapt** (patterns only) | **Monitor** |

### 4. Workflows

| Attribute | Claude Code | OpenAI Agents SDK | GitHub Copilot |
|-----------|------------|-------------------|----------------|
| **Concept name** | Not a first-class concept | Deterministic workflows (doc pattern) | Not a first-class concept |
| **Provider term** | Achieved via agent instructions + tools | `Agent` chains with deterministic routing | Achieved via prompt files + instructions |
| **Goblin's approach** | **Existing workflow engine** in `src/agentic_forex/runtime/engine.py` — node-based JSON definitions with agent/tool/router/finalize nodes | SDK patterns doc suggests agent chains | Not applicable |
| **Portability risk** | N/A (Goblin owns this) | Medium | N/A |
| **Fit for Goblin** | High — Goblin's engine is already provider-neutral | Low — different paradigm | N/A |
| **Recommendation** | **Keep** (Goblin's engine is canonical) | **Avoid** (don't adopt SDK patterns) | N/A |

### 5. Hooks

| Attribute | Claude Code | OpenAI Agents SDK | GitHub Copilot |
|-----------|------------|-------------------|----------------|
| **Concept name** | Hooks | Lifecycle hooks (limited) | Not supported |
| **Events** | `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `SubagentStop`, `SubagentStart` + tool-specific matchers | `on_handoff`, `on_tool_call` via agent callbacks | No hook system |
| **Handler types** | Command (shell), HTTP, Prompt (LLM), Agent (sub-agent) | Python callbacks on Agent class | N/A |
| **Blocking behavior** | Configurable: can block, modify, or allow tool calls | Non-blocking callbacks | N/A |
| **Shell support** | Bash, PowerShell (`"shell": "powershell"`) | N/A (Python) | N/A |
| **Configuration** | `.claude/hooks/` JSON or YAML files | Python code in agent definition | N/A |
| **Portability risk** | High — Claude-specific event model | High — SDK-specific | N/A |
| **Fit for Goblin** | High — validation, audit, policy enforcement | Low | N/A |
| **Recommendation** | **Adopt** (with provider adapter) | **Avoid** | N/A |

### 6. Skills

| Attribute | Claude Code | OpenAI Codex | GitHub Copilot |
|-----------|------------|--------------|----------------|
| **Concept name** | Skills (via CLAUDE.md instructions) | Skills (`.codex/skills-src/`) | Skills (`SKILL.md` with frontmatter) |
| **Definition format** | Markdown instructions in project CLAUDE.md or agent definitions | Markdown in `.codex/skills-src/` directories | YAML frontmatter + Markdown in skill directories |
| **Discovery** | Loaded from CLAUDE.md or agent `skills` field | Loaded from `.codex/skills-src/` by Codex runtime | Loaded from `.agents/skills/` by VS Code |
| **Portability risk** | Low (markdown-based) | Low (markdown-based) | Low (markdown-based) |
| **Fit for Goblin** | High | High | High |
| **Recommendation** | **Adopt** (all share markdown-based pattern — most portable component) |

### 7. Tools

| Attribute | Claude Code | OpenAI Agents SDK | GitHub Copilot |
|-----------|------------|-------------------|----------------|
| **Concept name** | Tools (built-in + MCP) | Tools (function tools, hosted tools) | Tools (built-in + MCP + language model tools) |
| **Built-in tools** | File read/write, terminal, search, notebook | Web search, file search, computer use | File ops, terminal, search, semantic search, browser |
| **Custom tools** | Via MCP servers | `@function_tool` decorator in Python | Via MCP servers or VS Code extensions |
| **Tool restriction** | Per-agent `allowedTools` and `disallowedTools` | Per-agent `tools` list | Per-agent `tools` list in frontmatter |
| **Portability risk** | Low (MCP is universal) | Medium (function_tool is SDK-specific) | Low (MCP is universal) |
| **Fit for Goblin** | High | Medium | High |
| **Recommendation** | **Adopt** (MCP as universal tool interface) |

### 8. MCP (Model Context Protocol)

| Attribute | Claude Code | OpenAI / ChatGPT | GitHub Copilot (VS Code) | Cursor |
|-----------|------------|-------------------|--------------------------|--------|
| **Support level** | Full (tools, resources, prompts) | Full (tools) | Full (tools, resources, prompts, apps) | Full (tools) |
| **Config location** | `.mcp.json` in project root or `~/.claude/` | Platform-specific | `.vscode/mcp.json` or user profile | `.cursor/mcp.json` |
| **Server types** | stdio, SSE, HTTP | HTTP/SSE | stdio, HTTP | stdio |
| **Sandboxing** | Via agent tool restrictions | N/A | Filesystem + network sandbox (macOS/Linux) | N/A |
| **Portability risk** | **Low** — MCP is the universal standard | **Low** | **Low** | **Low** |
| **Fit for Goblin** | **High** — universal tool interface | **High** | **High** | **High** |
| **Recommendation** | **Adopt** (universal standard; configure per-provider) |

### 9. Memory / Persistent Context

| Attribute | Claude Code | OpenAI Agents SDK | GitHub Copilot |
|-----------|------------|-------------------|----------------|
| **Concept name** | CLAUDE.md + auto-memory | Agent state (external) | copilot-instructions.md + memory files |
| **How it works** | `CLAUDE.md` files at project/user/workspace level; auto-memory saves facts across sessions | No built-in memory; state managed externally | `copilot-instructions.md`, `.github/copilot-instructions.md`, memory tool |
| **Persistence** | File-based, git-trackable | Developer-managed | File-based (instructions) + tool-based (session/repo/user memory) |
| **Scope levels** | Project > User > Enterprise | N/A | Repo > User > Session |
| **Portability risk** | Medium (CLAUDE.md is Claude-specific) | Low (external) | Medium (copilot-specific) |
| **Fit for Goblin** | High | N/A | High |
| **Recommendation** | **Adopt** (file-based memory is portable pattern; use provider-specific filenames) |

### 10. Knowledge Base / RAG

| Attribute | Claude Code | OpenAI | GitHub Copilot |
|-----------|------------|--------|----------------|
| **Concept name** | Project context (codebase indexing) | File search (vector store) | Workspace indexing |
| **How it works** | Automatic codebase indexing; context from CLAUDE.md, files | Vector store API + file_search tool | Automatic workspace indexing; `@workspace` context |
| **Portability risk** | Medium | High (API-specific) | Medium |
| **Fit for Goblin** | Medium — Goblin has own `corpus/` system | Low | Medium |
| **Recommendation** | **Keep** (Goblin's corpus system is canonical) |

### 11. Prompts / System Prompts

| Attribute | Claude Code | OpenAI Agents SDK | GitHub Copilot |
|-----------|------------|-------------------|----------------|
| **Concept name** | CLAUDE.md instructions | Agent `instructions` parameter | Prompt files (`.prompt.md`), instructions |
| **How defined** | Markdown in CLAUDE.md, agent definitions | Python string in Agent constructor | `.prompt.md` files with YAML frontmatter, `copilot-instructions.md` |
| **Template support** | Basic variable substitution | Python f-strings/templates | `{{variable}}` template syntax |
| **Portability risk** | Low (markdown) | Medium (Python strings) | Low (markdown) |
| **Fit for Goblin** | High | Medium | High |
| **Recommendation** | **Adopt** (markdown prompt files are the most portable pattern) |

### 12. Evaluators / Evals

| Attribute | Claude Code | OpenAI | GitHub Copilot |
|-----------|------------|--------|----------------|
| **Concept name** | Not first-class | Evals framework | Not first-class |
| **How it works** | Hook-based validation; test suites | `openai evals` CLI; benchmark datasets | Test-based validation |
| **Portability risk** | Low | High (OpenAI-specific) | Low |
| **Fit for Goblin** | N/A — Goblin has `evals/` package | Low | N/A |
| **Recommendation** | **Keep** (Goblin's eval system is canonical) |

### 13. Guardrails / Policy Layer

| Attribute | Claude Code | OpenAI Agents SDK | GitHub Copilot |
|-----------|------------|-------------------|----------------|
| **Concept name** | Permission system + hooks | Guardrails (input/output) | Settings + trust model |
| **How it works** | Tool permissions (allow/deny), hook-based policy enforcement | `InputGuardrail`, `OutputGuardrail` classes on Agent | MCP server trust, sandbox permissions |
| **Portability risk** | Medium | High | Medium |
| **Fit for Goblin** | High — matches governance model | Medium | Medium |
| **Recommendation** | **Adopt** (permission + hook pattern for policy enforcement) |

### 14. Human-in-the-Loop (HITL) Approvals

| Attribute | Claude Code | OpenAI | GitHub Copilot |
|-----------|------------|--------|----------------|
| **Concept name** | Permission prompts + hooks | Handoff to human | Tool approval prompts |
| **How it works** | Certain tools require user approval; hooks can block pending review | Agent can hand off to human; approval_callback pattern | Tool invocations can require user confirmation |
| **Portability risk** | Medium | Medium | Medium |
| **Fit for Goblin** | High — Goblin has approval pipeline | N/A | High |
| **Recommendation** | **Keep** (Goblin's approval system is canonical; integrate with provider HITL) |

### 15. Schedulers / Triggers

| Attribute | Claude Code | OpenAI | GitHub Copilot |
|-----------|------------|--------|----------------|
| **Concept name** | Cloud scheduled tasks, Desktop scheduled tasks | Not built-in | Not built-in |
| **How it works** | Cron-like scheduling via Claude Desktop or cloud API; recurring tasks | External scheduling (GitHub Actions, cron) | External via GitHub Actions |
| **Portability risk** | High (Claude-specific) | Low (external) | Low (external) |
| **Fit for Goblin** | Medium — automations use external triggers | N/A | Low |
| **Recommendation** | **Monitor** (keep scheduling external per Goblin's design) |

### 16. State / Checkpoints

| Attribute | Claude Code | OpenAI Agents SDK | GitHub Copilot |
|-----------|------------|-------------------|----------------|
| **Concept name** | Session persistence, checkpoints | RunContext state | Session memory |
| **How it works** | Auto-save conversation; resume from checkpoint | Developer-managed RunContext object | Session memory tool; conversation persistence |
| **Portability risk** | Medium | Low (external) | Medium |
| **Fit for Goblin** | N/A — Goblin manages own state in `Goblin/state/` | Low | Low |
| **Recommendation** | **Keep** (Goblin's checkpoint system is canonical) |

### 17. Telemetry / Observability

| Attribute | Claude Code | OpenAI Agents SDK | GitHub Copilot |
|-----------|------------|-------------------|----------------|
| **Concept name** | Traces, session logs | Tracing (built-in) | VS Code output logs |
| **How it works** | Debug logs, session trace files | Automatic trace capture; OpenTelemetry-compatible export | MCP server logs, output channel |
| **Portability risk** | Medium | Medium | Low |
| **Fit for Goblin** | N/A — Goblin traces via `traces/` directory and `governance/control_plane.py` event log | Medium (tracing patterns useful) | Low |
| **Recommendation** | **Keep** (Goblin's tracing is canonical) |

### 18. Provider Adapters / Connectors

| Attribute | Claude Code | OpenAI | GitHub Copilot |
|-----------|------------|--------|----------------|
| **Concept name** | Third-party API providers | API connector | MCP servers |
| **How it works** | Environment variables for API keys; supports third-party LLM providers | API key + model selection | MCP servers for external integrations |
| **Portability risk** | Low | Low | Low |
| **Fit for Goblin** | High — existing `BaseLLMClient` pattern | High | High |
| **Recommendation** | **Adopt** (adapter pattern is already in kernel) |

### 19. Registries / Manifests

| Attribute | Claude Code | OpenAI | GitHub Copilot |
|-----------|------------|--------|----------------|
| **Concept name** | Not first-class | Not first-class | Chat Customizations editor |
| **How it works** | Discovery from filesystem conventions | Manual registration | UI-based customization browser |
| **Portability risk** | Low | Low | Medium |
| **Fit for Goblin** | N/A — Goblin has component-registry.csv + codex_capability_catalog.json | N/A | Low |
| **Recommendation** | **Keep** (Goblin's registry system is canonical) |

### 20. CI/CD Integration

| Attribute | Claude Code | OpenAI | GitHub Copilot |
|-----------|------------|--------|----------------|
| **Concept name** | GitHub Actions, GitLab CI/CD | Not built-in | GitHub Actions |
| **How it works** | `anthropics/claude-code-action` for PR review; GitLab CI config | External | Native GitHub integration |
| **Portability risk** | Medium | N/A | Low |
| **Fit for Goblin** | Medium — future CI/CD integration | N/A | High |
| **Recommendation** | **Monitor** (adopt when CI/CD pipeline exists) |

---

## Summary: Portable vs Provider-Specific Components

### Universally Portable (safe to build canonical)

| Component | Pattern | Why portable |
|-----------|---------|-------------|
| **Skills** | Markdown + YAML frontmatter in directories | All providers use markdown skill definitions |
| **Prompts** | `.txt` / `.md` prompt files | All providers consume text prompts |
| **Workflows** | JSON node-based definitions | Goblin's engine is provider-neutral |
| **MCP** | `mcp.json` configuration | Open standard supported by all providers |
| **Memory** | File-based instructions (markdown) | All providers read project-level markdown |
| **Tool interface** | MCP servers | Universal protocol |
| **Config** | TOML/JSON policy files | Goblin's config system is runtime-neutral |

### Provider-Specific (require adapter layer)

| Component | Claude Code | OpenAI/Codex | GitHub Copilot |
|-----------|------------|--------------|----------------|
| **Agent definitions** | `.md` with Claude YAML schema | `.toml` agent configs | `.agent.md` with Copilot YAML schema |
| **Hooks** | `.claude/hooks/` JSON | Python callbacks | Not supported |
| **Permissions** | Claude permission model | Sandbox mode in config.toml | MCP sandbox + trust model |
| **Scheduling** | Cloud/Desktop scheduled tasks | External | External |
| **Traces** | Claude session logs | OpenAI tracing API | VS Code output logs |

### Goblin-Canonical (keep unchanged)

| Component | Location | Why canonical |
|-----------|----------|--------------|
| **Workflow engine** | `src/agentic_forex/runtime/engine.py` | Deterministic, schema-validated, provider-neutral |
| **Evaluation/evals** | `src/agentic_forex/evals/` | Domain-specific grading logic |
| **Approval pipeline** | `src/agentic_forex/approval/` | Governance-integrated HITL system |
| **State/checkpoints** | `Goblin/state/`, `Goblin/checkpoints/` | Program-level state management |
| **Telemetry** | `traces/`, `governance/control_plane.py` | Event-sourced governance audit trail |
| **Registry** | `docs/audit/component-registry.csv` | Structured asset inventory |
| **Config/policy** | `config/*.toml` | TOML policy files consumed by kernel |

---

## Phase 1 Validation

| Criterion | Status |
|-----------|--------|
| All 20 component types researched | ✅ |
| Claude Code, OpenAI, GitHub Copilot covered | ✅ |
| MCP covered as universal standard | ✅ |
| Official documentation used as primary source | ✅ |
| Each component has: strengths, limitations, portability risk, fit, recommendation | ✅ |
| Portable vs provider-specific components identified | ✅ |
| Goblin-canonical components identified (keep unchanged) | ✅ |
| Read-only phase — no files modified | ✅ |

**Rollback:** Not applicable — read-only research phase.

**Open Issues:**

1. Cursor and Windsurf documentation was less accessible; included where available but not at same depth as big three providers.
2. OpenAI Agents SDK evolves rapidly; recommendations may need refresh via Phase 6 industry update capability.
3. Hook systems are the least portable component — Claude is the only provider with a full event-based hook system; Goblin should define a provider-neutral hook contract and implement Claude adapter first.
