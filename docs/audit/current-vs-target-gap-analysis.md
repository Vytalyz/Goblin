# Phase 3 — Current-vs-Target Gap Analysis

**Generated:** 2026-04-13  
**Phase:** 3 — Gap Analysis  
**Inputs:** Phase 0 (`repo-inventory.md`, `component-registry.csv`), Phase 2 (`target-folder-structure.md`, `component-contracts.md`)

---

## Summary

| Category | Current | Target | Gaps |
|----------|---------|--------|------|
| Agent definitions | 17 (split across 3 formats) | 17 canonical `.agents/agents/*.md` | **17 new files** + 8 TOML adapters updated |
| Skills | 8 canonical + 8 duplicates + 3 legacy | 9 canonical (no duplicates) | **8 deletes**, **3 archives**, **1 new** (industry-monitoring) |
| Hooks | 0 | Contract schema + placeholder | **1 new** contract README |
| Workflows | 4 JSON | 4 JSON (governance fields added) | **4 edits** (trigger/rollback fields) |
| MCP servers | 0 | `.vscode/mcp.json` config | **1 new** file |
| Component registry | 0 | `.agents/registry.json` | **1 new** file |
| GitHub adapter | 0 | `.github/copilot-instructions.md` | **1 new** file |
| GOBLIN.md | 0 | Root canonical document | **1 new** file |
| Identity rename | "Agentic Forex" in 200+ refs | "Goblin" | **Mass rename** across docs, configs, skills |
| Hardcoded paths | 200+ Windows absolute paths | Relative or `ProjectPaths` | **3 active-code** files, many in gitignored artifacts |

---

## Gap Detail

### GAP-01: No Canonical Agent Definitions

**Current state:** Agent identities are split across three incompatible formats:
- 8 Codex TOML configs (`.codex/agents/*.toml`) — name, model, sandbox, instructions
- 9 role briefs (`agents/roles/*.md`) — 3-line Markdown bullets
- No canonical format that all providers can consume

**Target state:** 17 canonical Markdown+YAML frontmatter files in `.agents/agents/` with the full contract schema (identity, scope, triggers, I/O, tools, permissions, memory, escalation, observability, governance).

**Action:** Create 17 `.agents/agents/*.md` files. Extract mission/scope from TOML `developer_instructions` and role brief content. Codex TOMLs become thin adapters referencing canonical definitions.

**Effort:** Medium  
**Risk:** Low — additive; no existing behavior changes  
**Files affected:** 17 new + 8 TOML updates + 9 role briefs updated to reference canonical

---

### GAP-02: Duplicate Skills (8 exact copies)

**Current state:** `.codex/skills-src/` contains 8 directories that are byte-identical copies of `.agents/skills/`.

**Target state:** Single canonical location at `.agents/skills/`. No `.codex/skills-src/` directory.

**Action:** Delete `.codex/skills-src/` entirely. Verify Codex configuration can resolve skills from `.agents/skills/`.

**Effort:** Low  
**Risk:** Low — Codex reads `.agents/skills/` already  
**Files affected:** 8 deletes

---

### GAP-03: Legacy Skill Briefs

**Current state:** `skills/` directory contains 3 files (`critic-review.md`, `fresh-lens-discovery.md`, `strategy-discovery.md`) — each is a 3-bullet legacy brief with no YAML frontmatter and no contract structure.

**Target state:** Content absorbed into canonical agent contracts in `.agents/agents/`. Directory removed.

**Action:** Extract relevant content into agent contracts. Archive directory.

**Effort:** Low  
**Risk:** Low — legacy briefs are not referenced by any runtime code  
**Files affected:** 3 archives, referenced in 3+ agent contracts

---

### GAP-04: No Hook System

**Current state:** Zero hooks defined. `.codex/config.toml` disables Claude hooks for Windows.

**Target state:** `.agents/hooks/README.md` contract schema. Optional Claude implementations in `.claude/hooks/`.

**Action:** Create hook contract schema. No mandatory implementations yet (hooks are the least portable component — document the contract and implement when a provider supports them).

**Effort:** Low  
**Risk:** Very Low — greenfield  
**Files affected:** 1 new README

---

### GAP-05: No MCP Server Configuration

**Current state:** No MCP servers configured. No `.vscode/mcp.json`, no `.mcp.json`.

**Target state:** `.vscode/mcp.json` with at least a placeholder configuration. Additional provider MCP configs as needed.

**Action:** Create `.vscode/mcp.json`. Document available MCP servers for the Goblin ecosystem (filesystem, Goblin CLI, data access).

**Effort:** Low  
**Risk:** Low — additive  
**Files affected:** 1 new

---

### GAP-06: No Component Registry

**Current state:** No machine-readable index of all agentic components. Discovery requires manual file traversal.

**Target state:** `.agents/registry.json` with entries for all agents, skills, hooks, workflows, MCP servers.

**Action:** Generate registry from filesystem. Plan `goblin registry-sync` CLI command for maintenance.

**Effort:** Low-Medium  
**Risk:** Low — additive  
**Files affected:** 1 new JSON, 1 new CLI command (optional)

---

### GAP-07: No GitHub Provider Adapter

**Current state:** No `.github/` directory. No `copilot-instructions.md`.

**Target state:** `.github/copilot-instructions.md` providing repo-level Copilot instructions.

**Action:** Create file with Goblin-relevant coding guidelines, project conventions, and pointer to `AGENTS.md`.

**Effort:** Low  
**Risk:** Low — additive  
**Files affected:** 1 new

---

### GAP-08: Identity — "Agentic Forex" References

**Current state:** 200+ occurrences of "Agentic Forex" across:
- `AGENTS.md`, `codex.md`, `README.md` (documentation)
- `config/default.toml` (credential targets: `agentic-forex-practice`, `agentic-forex-live`)
- `.codex/rules/default.rules` (CLI refs: `python -m agentic_forex`)
- 5+ skill SKILL.md files (CLI refs)
- `src/agentic_forex/` package (namespace — keep per AGENTS.md)
- Numerous runtime artifacts in `data/`, `reports/`, `traces/` (gitignored)

**Target state:**
- Documentation: "Goblin" as primary identity; "agentic_forex" acknowledged as kernel namespace
- Config: Credential targets renamed to `goblin-practice`, `goblin-live` (with backward-compat aliases)
- CLI refs in skills: Use `goblin` CLI alias (already exists via `pyproject.toml` entry point)
- `src/agentic_forex/`: **Keep as-is** per AGENTS.md rule
- Gitignored artifacts: No action needed

**Action:** Rename in 15-20 active files. Leave `src/agentic_forex/` namespace untouched. Leave gitignored artifacts as-is.

**Effort:** Medium  
**Risk:** Medium — credential target renames need OANDA secret store alignment  
**Files affected:** ~20 files (documented in Phase 4 rename plan)

---

### GAP-09: Hardcoded Windows Paths

**Current state:** 200+ hardcoded absolute Windows paths. Three categories:
1. **Active code** (must fix):
   - `config/default.toml` — `supplemental_source_paths` hardcoded to `C:\Users\...`
   - `tests/test_cli_and_boundaries.py` — hardcoded path in test
   - `src/agentic_forex/mt5/ea_generator.py` — Windows-specific paths
2. **Goblin state files** (cosmetic — checkpoint paths in STATUS.md): Fix opportunistically
3. **Gitignored runtime artifacts** (`data/`, `reports/`, `traces/`, `knowledge/`): No action

**Target state:** Active code uses relative paths or `ProjectPaths` resolution. State files use relative references.

**Action:** Fix 3 active-code files. Address state files during migration phase.

**Effort:** Low  
**Risk:** Low-Medium — must verify `ProjectPaths` resolution works cross-platform  
**Files affected:** 3 active (must), ~5 cosmetic (should)

---

### GAP-10: Workflow Governance Extensions

**Current state:** 4 workflow JSON files define node-based workflows with `input_schema`/`output_schema` but lack:
- `trigger` block (implicit CLI invocation)
- `on_failure` per node
- `rollback` configuration
- `approval_required` per node

**Target state:** Workflows include governance fields per component contract.

**Action:** Add optional fields to existing JSON. Backward-compatible — engine ignores unknown fields.

**Effort:** Medium  
**Risk:** Low — additive fields  
**Files affected:** 4 workflow JSON files

---

### GAP-11: Vendor Coupling in Kernel

**Current state:**
- `src/agentic_forex/workflows/contracts.py` — OANDA as default `data_source`
- `src/agentic_forex/forward/readiness.py` — MT5 gates hardcoded
- `src/agentic_forex/credentials/secrets.py` + `config/default.toml` — credential target names use `agentic-forex`

**Target state:**
- Data source configurable (OANDA remains default, not hardcoded)
- MT5 gates parameterized (MT5 remains practice/parity, not hardcoded)
- Credential targets use `goblin-*` naming with backward-compat aliases

**Action:** Parameterize defaults. Add aliases for smooth migration.

**Effort:** Medium  
**Risk:** Medium — must not break existing OANDA live config  
**Files affected:** 3 source files + 1 config

---

### GAP-12: No Industry Update Capability

**Current state:** No industry monitoring skill or report generation.

**Target state:** 
- `.agents/skills/industry-monitoring/SKILL.md`
- `goblin industry-report` CLI command
- `reports/industry-update/latest.md` + `latest.html` output
- Tests

**Action:** New skill + CLI + templates + tests. Phase 6 deliverable.

**Effort:** High  
**Risk:** Medium — requires web access or data source for industry content  
**Files affected:** 5+ new files

---

### GAP-13: No Root GOBLIN.md

**Current state:** No canonical system document at root. System identity is distributed across `AGENTS.md`, `codex.md`, `Goblin/PROGRAM.md`, `README.md`.

**Target state:** `GOBLIN.md` at repo root — single entry point explaining system identity, architecture, and referencing all phase outputs.

**Action:** Write `GOBLIN.md` referencing all docs/ outputs. Last deliverable.

**Effort:** Low  
**Risk:** Low — additive  
**Files affected:** 1 new

---

## Gap Priority Matrix

| Gap | ID | Effort | Risk | Dependency | Phase |
|-----|-----|--------|------|------------|-------|
| Delete duplicate skills | GAP-02 | Low | Low | None | 4 |
| Archive legacy skills | GAP-03 | Low | Low | None | 4 |
| Create hook contract | GAP-04 | Low | Very Low | None | 4 |
| Create MCP config | GAP-05 | Low | Low | None | 4 |
| Create GitHub adapter | GAP-07 | Low | Low | None | 4 |
| Create component registry | GAP-06 | Low-Med | Low | GAP-01 | 4 |
| Create agent definitions | GAP-01 | Medium | Low | None | 4 |
| Rename identity | GAP-08 | Medium | Medium | None | 4 |
| Fix hardcoded paths | GAP-09 | Low | Low-Med | None | 4 |
| Workflow governance ext. | GAP-10 | Medium | Low | GAP-01 | 4 |
| Vendor coupling | GAP-11 | Medium | Medium | GAP-08 | 4 |
| Industry update | GAP-12 | High | Medium | GAP-01 | 6 |
| Write GOBLIN.md | GAP-13 | Low | Low | All | Final |

---

## Metrics

- **Total new files to create:** ~25 (17 agents + registry + GOBLIN.md + MCP config + GitHub adapter + hook README + industry skill + CLI)
- **Total files to delete:** 8 (duplicate skills in `.codex/skills-src/`)
- **Total files to archive:** 4 (3 legacy skills + 1 empty knowledge dir)
- **Total files to edit:** ~30 (8 TOML adapters + 9 role briefs + 4 workflows + ~10 identity renames including docs/config/skills)
- **Source code changes:** 3 files (vendor coupling) + 1 new CLI command
- **Zero behavioral changes to runtime kernel** until explicit migration
