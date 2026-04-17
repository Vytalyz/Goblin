# Hook Contracts

This directory holds **provider-neutral hook definitions**. Provider-specific implementations live in their respective directories (`.claude/hooks/`, etc.).

## Contract Schema

Each hook is defined as a Markdown file with YAML frontmatter:

```yaml
---
name: <kebab-case identifier>
event: <pre-tool-use | post-tool-use | pre-commit | post-run | on-error | on-approval>
description: <one-line purpose>
timing:
  phase: <before | after | around>
  blocking: <true | false>
  timeout_ms: <milliseconds>
condition:
  tool_pattern: <glob or regex matching tool names>
  file_pattern: <glob matching affected files>
action:
  type: <script | cli-command | mcp-call | log-only>
  command: <command to execute>
on_failure: <skip | warn | block | escalate>
log_to: <traces/ path>
---
```

## Provider Support

| Event | Claude Code | OpenAI Codex | GitHub Copilot |
|-------|------------|--------------|----------------|
| `pre-tool-use` | `.claude/settings.local.json` | N/A | N/A |
| `post-tool-use` | `.claude/settings.local.json` | N/A | N/A |
| `pre-commit` | Git hooks | Git hooks | Git hooks + GitHub Actions |
| `on-error` | Hook error handler | N/A | N/A |

Hooks are the least portable component. Define contracts here; implement per-provider when supported.
