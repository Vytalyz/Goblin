# Decision Log — Goblin Architecture Migration

**Generated:** 2026-04-13  
**Phase:** 5 — Operational Resilience  
**Purpose:** Record architectural decisions made during the migration planning and execution

---

## Format

Each decision uses a lightweight ADR (Architecture Decision Record) format:

- **ID:** Sequential `DEC-NNNN`
- **Date:** When decided
- **Status:** `proposed` → `accepted` → `superseded` | `rejected`
- **Context:** Why this decision was needed
- **Decision:** What was decided
- **Consequences:** What follows from this decision

---

## Decisions

### DEC-0001 — Keep `src/agentic_forex/` as kernel namespace

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** The Goblin identity migration could rename the kernel package to `src/goblin/` for consistency. However, AGENTS.md explicitly prohibits this: "Keep `src/agentic_forex` as the deterministic kernel until a later explicit migration."  
**Decision:** Keep `src/agentic_forex/` as the kernel namespace. Use `src/goblin/` only as a bridge alias (sys.modules aliasing).  
**Consequences:** Import paths remain `from agentic_forex.X import Y` or equivalently `from goblin.X import Y`. No import-breaking changes. The bridge must be maintained until explicit migration.

---

### DEC-0002 — Canonical agent definitions in Markdown, not TOML

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** Agents exist in 3 formats: Codex TOML (8), role briefs Markdown (9), neither (0 canonical). Need one canonical format all providers can consume.  
**Decision:** Use Markdown + YAML frontmatter (`.agents/agents/*.md`) as the canonical format. Codex TOMLs become thin adapters that reference the canonical definition.  
**Consequences:** 
- Claude Code, Copilot, and MCP all natively consume Markdown with YAML frontmatter
- Codex cannot directly consume Markdown — keeps its TOML adapter with `canonical_ref` field
- Human-readable by default
- Structured metadata in YAML, behavioral instructions in body

---

### DEC-0003 — Provider adapter pattern (dotfile directories)

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** Different AI providers require different configuration formats (`.claude/`, `.codex/`, `.vscode/`). Need to avoid duplicating canonical definitions across providers.  
**Decision:** Each provider gets its own dotfile directory for provider-specific wiring only. No business logic or canonical definitions in provider directories. Provider adapters reference canonical definitions in `.agents/`.  
**Consequences:**
- Adding a new provider = adding a new dotfile directory with adapters
- Removing a provider = deleting its dotfile directory (no canonical content lost)
- Provider-specific features (Claude hooks, Codex model selection) stay in provider dirs

---

### DEC-0004 — Delete `.codex/skills-src/` (8 exact duplicates)

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** `.codex/skills-src/` contains 8 directories that are byte-identical copies of `.agents/skills/`. Codex already reads from `.agents/skills/`.  
**Decision:** Delete `.codex/skills-src/` entirely.  
**Consequences:** One less duplication vector. Codex skill resolution must be verified post-deletion (Batch 1 validation).

---

### DEC-0005 — OANDA remains default data source (configurable, not removed)

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** AGENTS.md states "OANDA is the canonical research data source." The kernel hardcodes OANDA as the default `data_source` in `contracts.py`.  
**Decision:** Keep OANDA as the default. Make it configurable (not hardcoded) so alternative sources can be added without kernel changes.  
**Consequences:** No behavioral change for existing users. New data sources can be added via config without modifying kernel code.

---

### DEC-0006 — Credential target rename to `goblin-*` with backward-compat aliases

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** `config/default.toml` uses `agentic-forex-practice` and `agentic-forex-live` as credential target names. The identity migration wants `goblin-*` targets.  
**Decision:** Add `goblin-practice` and `goblin-live` as primary targets. Keep `agentic-forex-*` as deprecated aliases that resolve to the same credentials.  
**Consequences:** No breaking change. New setups use `goblin-*`. Old setups continue working. Deprecation warning can be added later.

---

### DEC-0007 — Hooks: contract-first, implementation-later

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** Zero hooks exist today. Claude Code is the only provider with a full hook system, and it's disabled on Windows. Codex and Copilot lack hook support.  
**Decision:** Define the hook contract schema (`.agents/hooks/README.md`) now. Defer actual implementations until a provider supports them on the active platform.  
**Consequences:** Hook contract is available for planning. No broken implementations. Claude hooks can be added when Windows support improves.

---

### DEC-0008 — MCP as universal tool interface

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** Phase 1 research confirmed MCP (Model Context Protocol) is supported by Claude Code, VS Code Copilot, Cursor, OpenAI Agents SDK, and Claude Desktop. It's the only universal standard for tool integration.  
**Decision:** Adopt MCP as the standard tool interface for external integrations. Create `.vscode/mcp.json` as the primary config (also usable by other providers via their own config files).  
**Consequences:** New tool integrations should be MCP servers. Existing CLI tools remain accessible via MCP's stdio transport. Future MCPs for Goblin CLI, data access, etc.

---

### DEC-0009 — No runtime dependency on OPENAI_API_KEY

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** AGENTS.md prohibits: "Do not introduce a runtime dependency on `OPENAI_API_KEY` or a permanently open Codex session."  
**Decision:** Codex remains an outer operator/orchestration layer only. The deterministic kernel and `goblin` CLI must function without any AI provider API key.  
**Consequences:** Industry report generation (Phase 6) must work offline or with configurable data sources. AI-powered features are optional enhancements, not requirements.

---

### DEC-0010 — Industry report as local data aggregation (not live web scraping)

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** Phase 6 requires `goblin industry-report` CLI. An AI-powered web scraping approach would violate DEC-0009 (no API key dependency). A live web fetch approach has reliability concerns.  
**Decision:** Industry report aggregates data from local corpus, experiment results, and optionally fetched market calendars. It does not require an AI API key to function. Enhanced summaries can use AI when available.  
**Consequences:** Base report is always available offline. AI enhancement is opt-in. Report format is Markdown + HTML (Jinja template).

---

### DEC-0011 — Workflow governance fields are additive (backward-compatible)

**Date:** 2026-04-13  
**Status:** accepted  
**Context:** Adding `trigger`, `rollback`, and `on_failure` fields to workflow JSON could break the engine if it uses strict parsing.  
**Decision:** Add fields as optional. Verify engine tolerates unknown keys before applying. If not, make engine tolerant first.  
**Consequences:** Existing workflows continue working. New governance features activate only when explicitly configured.

---

### DEC-0012 — Git commit per batch (not squash)

**Date:** 2026-04-13  
**Status:** proposed  
**Context:** Migration has 12 batches. Committing per batch enables `git revert` and `git bisect`. Squashing loses per-batch granularity.  
**Decision:** Commit after each successful batch with conventional message format `goblin-migration: batch-N — <description>`.  
**Consequences:** Clean audit trail. Easy per-batch rollback. Slightly longer commit history.

---

## Template for New Decisions

```markdown
### DEC-NNNN — <Title>

**Date:** YYYY-MM-DD  
**Status:** proposed | accepted | superseded | rejected  
**Context:** <Why this decision is needed>  
**Decision:** <What was decided>  
**Consequences:** <What follows>
```
