# Phase 2b — Component Contracts

**Generated:** 2026-04-13  
**Phase:** 2 — Target Architecture  
**Inputs:** Phase 0 inventory, Phase 1 provider comparison, existing Pydantic/TOML/YAML contracts

---

## Purpose

Define the canonical contract schema for every agentic component type in the Goblin system. These contracts are provider-neutral — provider adapters translate them into provider-specific formats.

---

## 1. Agent Contract

Canonical location: `.agents/agents/<agent-name>.md`  
Format: Markdown with YAML frontmatter

### Schema

```yaml
---
# ─── Identity ───
name: <kebab-case identifier>
description: <one-line purpose>
owner: <human or team responsible>
version: <semver or date>

# ─── Scope ───
mission: <what this agent is responsible for>
scope:
  - <enumerated domain boundaries>
anti-scope:
  - <what this agent must NOT do>

# ─── Triggers ───
triggers:
  - type: <manual | schedule | event | workflow-step>
    source: <what initiates this agent>
    condition: <optional guard expression>

# ─── I/O ───
inputs:
  - name: <input name>
    type: <string | path | json | artifact-ref>
    required: <true | false>
    description: <what this input is>
outputs:
  - name: <output name>
    type: <string | path | json | artifact-ref>
    description: <what this output is>

# ─── Tools & Capabilities ───
tools:
  - <CLI command, MCP server, or skill name>
skills:
  - <skill names this agent may invoke>
mcp_servers:
  - <MCP server names this agent requires>

# ─── Permissions ───
permissions:
  sandbox: <read-only | workspace-write | full-access>
  file_write: <list of glob patterns or "none">
  network: <allowed | denied | scoped>
  approval_required: <true | false>

# ─── Memory & State ───
memory:
  reads_from:
    - <state file, checkpoint, or artifact path>
  writes_to:
    - <state file, checkpoint, or artifact path>

# ─── Reasoning ───
model_hint: <model family preference — not binding>
reasoning_effort: <low | medium | high>

# ─── Escalation ───
escalation:
  on_failure: <retry-once | escalate-to-human | escalate-to-agent>
  escalation_target: <agent name or "human">
  max_retries: <integer>

# ─── Observability ───
observability:
  trace_to: <traces/ directory or trace system>
  log_level: <info | debug | warning>
  artifacts: <list of expected output artifact paths>

# ─── Governance ───
governance:
  parity_class: <benchmark | mutable | practice-only>
  provenance_required: <true | false>
  approval_gate: <none | human | automated>
---

# <Agent Name>

<Extended mission description, strategy, and behavioral notes in Markdown body.>

## Workflow

<Step-by-step operational procedure.>

## Rules

<Hard constraints this agent must obey.>

## Failure Modes

<Known failure scenarios and expected behavior.>
```

### Provider Adaptation

| Field | Claude Code | OpenAI Codex | GitHub Copilot |
|-------|------------|--------------|----------------|
| `name` | agent YAML `name` | TOML `name` | `.agent.md` header |
| `description` | agent YAML `description` | TOML `description` | `.agent.md` description |
| `tools` | `allowed_tools` | CLI allowlist in rules | tool restrictions in YAML |
| `permissions.sandbox` | Claude permissions model | TOML `sandbox_mode` | N/A (inherits VS Code) |
| `model_hint` | `model` field | TOML `model` | N/A (user-selected) |
| `reasoning_effort` | N/A | TOML `model_reasoning_effort` | N/A |
| `mission` + Rules | `developer_instructions` | TOML `developer_instructions` | Body of `.agent.md` |

---

## 2. Skill Contract

Canonical location: `.agents/skills/<skill-name>/SKILL.md`  
Format: Markdown with YAML frontmatter (existing format — extended)

### Schema

```yaml
---
# ─── Identity ───
name: <kebab-case identifier>
description: <one-line purpose — used by all providers for skill matching>
version: <semver or date>

# ─── Interface ───
inputs:
  - name: <input name>
    type: <string | path | json>
    required: <true | false>
outputs:
  - name: <output name>
    type: <string | path | json | artifact-ref>

# ─── Dependencies ───
requires:
  cli_commands:
    - <python -m agentic_forex ...>
  mcp_servers:
    - <MCP server name>
  config_files:
    - <config path>

# ─── Auth & Permissions ───
permissions:
  sandbox: <read-only | workspace-write>
  network: <allowed | denied>
  secrets:
    - <secret name this skill needs>

# ─── Compatibility ───
providers:
  - claude-code
  - openai-codex
  - github-copilot
  - mcp

# ─── Fallback ───
fallback:
  on_missing_dependency: <skip | warn | error>
  degraded_mode: <description of limited operation>
---

# <Skill Name>

<Purpose and when to use.>

## Workflow

<Numbered steps.>

## Rules

<Hard constraints.>
```

### Migration from Existing Format

Current skills already use `name` + `description` in YAML frontmatter. The extended contract adds: `version`, `inputs`, `outputs`, `requires`, `permissions`, `providers`, `fallback`. Existing skills remain valid — new fields are optional and additive.

---

## 3. Workflow Contract

Canonical location: `workflows/<workflow-name>.json`  
Format: JSON (existing format — formalized)

### Schema

```json
{
  "$schema": "goblin-workflow-v1",
  "name": "<workflow-name>",
  "version": "<semver or date>",
  "description": "<one-line purpose>",
  "trigger": {
    "type": "<manual | schedule | event | cli-command>",
    "source": "<trigger source>"
  },
  "input_schema": "<Pydantic model name or inline JSON Schema>",
  "output_schema": "<Pydantic model name or inline JSON Schema>",
  "nodes": [
    {
      "id": "<node-id>",
      "role": "<agent name>",
      "type": "<generate | review | branch | approve>",
      "prompt_template": "<prompts/<file>.txt>",
      "input_schema": "<schema name>",
      "output_schema": "<schema name>",
      "next": "<node-id | conditional>",
      "on_failure": "<retry | skip | abort>",
      "max_retries": 1,
      "approval_required": false
    }
  ],
  "success_criteria": "<description of workflow success>",
  "rollback": {
    "strategy": "<none | revert-artifacts | revert-state>",
    "checkpoint_before": true
  }
}
```

### Governance Fields (extension)

| Field | Purpose |
|-------|---------|
| `trigger` | Replaces implicit CLI invocation |
| `on_failure` per node | Enables retry/skip/abort without workflow-level failure |
| `rollback` | Defines undo behavior on partial completion |
| `approval_required` per node | Maps to human approval gates |

---

## 4. Hook Contract

Canonical location: `.agents/hooks/<hook-name>.md`  
Format: Markdown with YAML frontmatter (provider-neutral definition)  
Implementations: `.claude/hooks/`, `.codex/hooks/` (future), `.github/hooks/` (future)

### Schema

```yaml
---
# ─── Identity ───
name: <kebab-case identifier>
event: <pre-tool-use | post-tool-use | pre-commit | post-run | on-error | on-approval>
description: <one-line purpose>

# ─── Timing ───
timing:
  phase: <before | after | around>
  blocking: <true | false>
  timeout_ms: <milliseconds>

# ─── Condition ───
condition:
  tool_pattern: <glob or regex matching tool names>
  file_pattern: <glob matching affected files>
  expression: <optional boolean expression>

# ─── Action ───
action:
  type: <script | cli-command | mcp-call | log-only>
  command: <command to execute>
  args:
    - <arg1>

# ─── Failure ───
on_failure: <skip | warn | block | escalate>

# ─── Observability ───
log_to: <traces/ path>
---

# <Hook Name>

<Extended description and rationale.>
```

### Provider Implementation Map

| Event | Claude Code | OpenAI Codex | GitHub Copilot |
|-------|------------|--------------|----------------|
| `pre-tool-use` | `.claude/settings.local.json` hooks | N/A (no hook system) | N/A |
| `post-tool-use` | `.claude/settings.local.json` hooks | N/A | N/A |
| `pre-commit` | Git hooks + `.claude/` | Git hooks | Git hooks + GitHub Actions |
| `on-error` | Hook error handler | N/A | N/A |
| `on-approval` | Custom via skill | Custom via workflow | Custom via workflow |

**Note:** Hooks are the least portable component. The canonical contract enables future provider support while Claude Code is the only current implementor.

---

## 5. MCP Server Contract

Canonical location: `.vscode/mcp.json` (for VS Code/Copilot); adaptable to other providers  
Format: JSON (MCP standard)

### Schema Per Server

```json
{
  "servers": {
    "<server-name>": {
      "type": "<stdio | sse | streamable-http>",
      "command": "<executable>",
      "args": ["<arg1>", "<arg2>"],
      "env": {
        "<VAR>": "<value or ${input:prompt}>"
      },
      "description": "<what this server provides>",
      "tools": ["<tool-name-1>", "<tool-name-2>"],
      "resources": ["<resource-uri-pattern>"],
      "prompts": ["<prompt-name>"]
    }
  }
}
```

### MCP Compatibility Matrix

| Provider | Config File | Supported Transports |
|----------|------------|---------------------|
| VS Code / Copilot | `.vscode/mcp.json` | stdio, sse, streamable-http |
| Claude Code | `.mcp.json` (root) | stdio, sse, streamable-http |
| Claude Desktop | `claude_desktop_config.json` | stdio, sse |
| OpenAI Agents SDK | Python `MCPServerStdio()` / `MCPServerSse()` | stdio, sse, streamable-http |
| Cursor | `.cursor/mcp.json` | stdio, sse |

---

## 6. Prompt Template Contract

Canonical location: `prompts/<prompt-name>_system.txt`, `prompts/<prompt-name>_user.txt`  
Format: Plain text with `{placeholder}` substitution

### Schema (implicit — no metadata file)

| Convention | Rule |
|-----------|------|
| Naming | `<domain>_system.txt` / `<domain>_user.txt` pairs |
| Placeholders | `{variable_name}` — resolved by workflow engine |
| No provider logic | Templates must not contain provider-specific instructions |
| Reuse | Multiple workflow nodes may reference the same template |

---

## 7. Config / Policy Contract

Canonical location: `config/<policy-name>.toml`  
Format: TOML

### Existing Contracts (unchanged)

| File | Pydantic Model | Purpose |
|------|---------------|---------|
| `default.toml` | `GoblinConfig` | Master runtime config |
| `autonomy_policy.toml` | `AutonomyPolicy` | Autonomy boundaries |
| `data_contract.toml` | `DataContract` | Data schema expectations |
| `eval_gates.toml` | `EvalGates` | Evaluation pass/fail thresholds |
| `mt5_env.toml` | `MT5EnvConfig` | MT5 practice environment |
| `portfolio_policy.toml` | `PortfolioPolicy` | Slot assignment rules |
| `program_policy.toml` | `ProgramPolicy` | Program loop behavior |
| `risk_policy.toml` | `RiskPolicy` | Risk limits |

### Governance Extension

All config files must be:
- Validated by `validate-operator-contract --strict` before deployment
- Versioned in Git (no gitignored configs)
- Referenced by `OperatorContractReport` for audit

---

## 8. Component Registry Contract

Canonical location: `.agents/registry.json`  
Format: JSON

### Schema

```json
{
  "$schema": "goblin-registry-v1",
  "generated_utc": "<ISO timestamp>",
  "components": [
    {
      "name": "<component name>",
      "type": "<agent | skill | hook | workflow | prompt | mcp-server | config>",
      "canonical_path": "<path relative to repo root>",
      "provider_adapters": {
        "claude": "<path or null>",
        "codex": "<path or null>",
        "copilot": "<path or null>"
      },
      "version": "<version string>",
      "status": "<active | deprecated | planned>",
      "governance": {
        "parity_class": "<benchmark | mutable | practice-only | none>",
        "approval_gate": "<none | human | automated>"
      }
    }
  ]
}
```

### Maintenance

- Registry is regenerated by `goblin registry-sync` CLI command (planned)
- Manual edits are allowed but must be validated against filesystem
- CI should verify registry completeness on every PR

---

## Summary: Contract Adoption Priority

| Priority | Contract | Effort | Impact |
|----------|----------|--------|--------|
| 1 | Agent Contract | Medium | Unifies 3 formats (TOML + MD brief + ad-hoc) into one |
| 2 | Component Registry | Low | Provides machine-readable discovery for all providers |
| 3 | Skill Contract (extension) | Low | Backward-compatible additions to existing YAML frontmatter |
| 4 | Hook Contract | Low | Currently no hooks exist — greenfield |
| 5 | MCP Server Contract | Low | Standard format — just needs `.vscode/mcp.json` created |
| 6 | Workflow Contract (governance ext.) | Medium | Adds trigger/rollback/approval to existing JSON |
| 7 | Config validation | Already exists | `validate-operator-contract` CLI already enforces this |
