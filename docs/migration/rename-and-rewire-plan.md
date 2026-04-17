# Phase 4 — Rename & Rewire Plan

**Generated:** 2026-04-13  
**Phase:** 4 — Migration Plan  
**Inputs:** Phase 3 gap analysis (13 gaps), Phase 2 target architecture

---

## Execution Principles

1. **Checkpoint before every batch** — `git stash` or commit before destructive operations
2. **One batch = one concern** — don't mix deletes with renames with new files
3. **Tests after every batch** — `python -m pytest tests/ -x --tb=short`
4. **Resumable** — each batch is independent; partial completion is safe
5. **No behavioral changes to runtime** — only additive or cosmetic until explicit migration

---

## Migration Batches

### Batch 0: Pre-Flight

**Checkpoint:** `git stash` or clean working tree  
**Verify:** `python -m pytest tests/ -x --tb=short` passes  
**Output:** Baseline test status recorded

---

### Batch 1: Delete Duplicates (GAP-02)

Delete 8 exact-duplicate skill directories from `.codex/skills-src/`.

| Action | Path |
|--------|------|
| DELETE | `.codex/skills-src/artifact-audit/SKILL.md` |
| DELETE | `.codex/skills-src/candidate-refinement/SKILL.md` |
| DELETE | `.codex/skills-src/capability-crawl/SKILL.md` |
| DELETE | `.codex/skills-src/governed-strategy-search/SKILL.md` |
| DELETE | `.codex/skills-src/incident-review/SKILL.md` |
| DELETE | `.codex/skills-src/parity-packaging/SKILL.md` |
| DELETE | `.codex/skills-src/promotion-readiness-review/SKILL.md` |
| DELETE | `.codex/skills-src/runtime-monitoring/SKILL.md` |
| DELETE | `.codex/skills-src/` (directory) |

**Rollback:** `git checkout -- .codex/skills-src/`  
**Test:** `python -m pytest tests/ -x --tb=short`  
**Verify:** `.agents/skills/` still has all 8 skills

---

### Batch 2: Archive Legacy Skills (GAP-03)

Move 3 legacy skill briefs out of active tree.

| Action | Old Path | New Path |
|--------|----------|----------|
| MOVE | `skills/critic-review.md` | `docs/archive/legacy-skills/critic-review.md` |
| MOVE | `skills/fresh-lens-discovery.md` | `docs/archive/legacy-skills/fresh-lens-discovery.md` |
| MOVE | `skills/strategy-discovery.md` | `docs/archive/legacy-skills/strategy-discovery.md` |
| DELETE | `skills/` (empty directory) |

**Rollback:** `git checkout -- skills/`  
**Test:** `python -m pytest tests/ -x --tb=short`

---

### Batch 3: Create Provider Adapters (GAP-04, GAP-05, GAP-07)

| Action | Path | Content Source |
|--------|------|---------------|
| CREATE | `.agents/hooks/README.md` | Hook contract schema from `component-contracts.md` §4 |
| CREATE | `.vscode/mcp.json` | Placeholder MCP config |
| CREATE | `.github/copilot-instructions.md` | Repo-level Copilot instructions referencing AGENTS.md |

**Rollback:** `git checkout -- .agents/hooks/ .vscode/mcp.json .github/`  
**Test:** `python -m pytest tests/ -x --tb=short`

---

### Batch 4: Create Canonical Agent Definitions (GAP-01)

Create 17 canonical agent definitions in `.agents/agents/`. Sources:

| Agent | Source: Codex TOML | Source: Role Brief | New Canonical |
|-------|-------------------|--------------------|---------------|
| portfolio-orchestrator | `.codex/agents/portfolio_orchestrator.toml` | — | `.agents/agents/portfolio-orchestrator.md` |
| gap-lane-explorer | `.codex/agents/gap_lane_explorer.toml` | — | `.agents/agents/gap-lane-explorer.md` |
| governance-auditor | `.codex/agents/governance_auditor.toml` | — | `.agents/agents/governance-auditor.md` |
| incident-reviewer | `.codex/agents/incident_reviewer.toml` | — | `.agents/agents/incident-reviewer.md` |
| lane-researcher | `.codex/agents/lane_researcher.toml` | — | `.agents/agents/lane-researcher.md` |
| runtime-observer | `.codex/agents/runtime_observer.toml` | — | `.agents/agents/runtime-observer.md` |
| throughput-worker | `.codex/agents/throughput_worker.toml` | — | `.agents/agents/throughput-worker.md` |
| validation-worker | `.codex/agents/validation_worker.toml` | — | `.agents/agents/validation-worker.md` |
| corpus-librarian | — | `agents/roles/corpus-librarian.md` | `.agents/agents/corpus-librarian.md` |
| day-trading-strategist | — | `agents/roles/day-trading-strategist.md` | `.agents/agents/day-trading-strategist.md` |
| execution-realist | — | `agents/roles/execution-realist.md` | `.agents/agents/execution-realist.md` |
| extraction-reviewer | — | `agents/roles/extraction-reviewer.md` | `.agents/agents/extraction-reviewer.md` |
| lead-orchestrator | — | `agents/roles/lead-orchestrator.md` | `.agents/agents/lead-orchestrator.md` |
| quant-critic | — | `agents/roles/quant-critic.md` | `.agents/agents/quant-critic.md` |
| review-synthesizer | — | `agents/roles/review-synthesizer.md` | `.agents/agents/review-synthesizer.md` |
| risk-critic | — | `agents/roles/risk-critic.md` | `.agents/agents/risk-critic.md` |
| scalping-strategist | — | `agents/roles/scalping-strategist.md` | `.agents/agents/scalping-strategist.md` |

**Process per agent:**
1. Read source TOML/brief
2. Map fields to canonical contract schema
3. Fill `mission`, `scope`, `anti-scope` from `developer_instructions` or brief bullets
4. Set `permissions.sandbox` from TOML `sandbox_mode` or default to `read-only`
5. Set `model_hint` from TOML `model` or omit
6. Add `governance` block from portfolio policy knowledge

**Rollback:** `git checkout -- .agents/agents/`  
**Test:** `python -m pytest tests/ -x --tb=short`

---

### Batch 5: Update Codex TOML Adapters (GAP-01 continued)

Slim down 8 Codex agent TOMLs to adapter-only content. Add `canonical_ref` pointing to `.agents/agents/` definition.

| File | Change |
|------|--------|
| `.codex/agents/portfolio_orchestrator.toml` | Add `canonical_ref`, keep model/sandbox/instructions |
| `.codex/agents/gap_lane_explorer.toml` | Add `canonical_ref`, keep model/sandbox/instructions |
| `.codex/agents/governance_auditor.toml` | Add `canonical_ref`, keep model/sandbox/instructions |
| `.codex/agents/incident_reviewer.toml` | Add `canonical_ref`, keep model/sandbox/instructions |
| `.codex/agents/lane_researcher.toml` | Add `canonical_ref`, keep model/sandbox/instructions |
| `.codex/agents/runtime_observer.toml` | Add `canonical_ref`, keep model/sandbox/instructions |
| `.codex/agents/throughput_worker.toml` | Add `canonical_ref`, keep model/sandbox/instructions |
| `.codex/agents/validation_worker.toml` | Add `canonical_ref`, keep model/sandbox/instructions |

**Note:** Codex reads `developer_instructions` from TOML, so instructions stay. The `canonical_ref` field is informational for humans/tools — Codex ignores it.

**Rollback:** `git checkout -- .codex/agents/`  
**Test:** `python -m pytest tests/ -x --tb=short`

---

### Batch 6: Identity Rename — Documentation (GAP-08 partial)

Rename "Agentic Forex" to "Goblin" in documentation files. **Do NOT touch `src/agentic_forex/`.**

| File | Search | Replace |
|------|--------|---------|
| `AGENTS.md` | `Agentic Forex` (title context) | `Goblin` |
| `codex.md` | `Agentic Forex` (identity refs) | `Goblin` |
| `README.md` | `Agentic Forex` (all occurrences) | `Goblin` |
| `README.md` | Hardcoded Windows paths | Relative paths |
| `.codex/rules/default.rules` | `python -m agentic_forex` | `python -m goblin` (or dual) |
| `.agents/skills/candidate-refinement/SKILL.md` | `python -m agentic_forex` | `goblin` CLI |
| `.agents/skills/capability-crawl/SKILL.md` | `python -m agentic_forex` | `goblin` CLI |
| `.agents/skills/governed-strategy-search/SKILL.md` | `python -m agentic_forex` | `goblin` CLI |
| `.agents/skills/parity-packaging/SKILL.md` | `python -m agentic_forex` | `goblin` CLI |
| `.agents/skills/promotion-readiness-review/SKILL.md` | `python -m agentic_forex` | `goblin` CLI |
| `automations/prompts/gap-lane-research.md` | `agentic_forex` refs | `goblin` CLI |

**Rollback:** `git checkout -- AGENTS.md codex.md README.md .codex/rules/ .agents/skills/ automations/prompts/`  
**Test:** `python -m pytest tests/ -x --tb=short` + grep verify: `grep -r "Agentic Forex" --include="*.md" --include="*.toml" --include="*.rules" | grep -v "src/" | grep -v "data/" | grep -v "reports/" | grep -v "traces/" | grep -v "experiments/" | grep -v ".git/"`

---

### Batch 7: Fix Hardcoded Paths (GAP-09)

| File | Current | Target |
|------|---------|--------|
| `config/default.toml` | `supplemental_source_paths = ["C:\\Users\\..."]` | `supplemental_source_paths = []` (empty, resolved at runtime) |
| `tests/test_cli_and_boundaries.py` | Hardcoded Windows path | `Path(__file__).resolve().parents[1]` or similar |
| `src/agentic_forex/mt5/ea_generator.py` | Windows-specific MQL path | Parameterized via config or `MT5EnvConfig` |

**Rollback:** `git checkout -- config/default.toml tests/test_cli_and_boundaries.py src/agentic_forex/mt5/ea_generator.py`  
**Test:** `python -m pytest tests/ -x --tb=short`

---

### Batch 8: Vendor Coupling (GAP-11)

| File | Current | Target |
|------|---------|--------|
| `src/agentic_forex/workflows/contracts.py` | `data_source` defaults to `"oanda"` | Default stays `"oanda"` but documented as configurable |
| `src/agentic_forex/forward/readiness.py` | MT5 gates hardcoded | Parameterize via `mt5_env.toml` or feature flag |
| `config/default.toml` | Credential targets: `agentic-forex-practice/live` | Add `goblin-practice/live` with backward-compat alias |

**Note:** OANDA as default is correct per AGENTS.md ("OANDA is the canonical research data source"). The change is making it configurable, not removing it.

**Rollback:** `git checkout -- src/agentic_forex/workflows/contracts.py src/agentic_forex/forward/readiness.py config/default.toml`  
**Test:** `python -m pytest tests/ -x --tb=short`

---

### Batch 9: Workflow Governance Extensions (GAP-10)

Add optional governance fields to 4 workflow JSON files.

| File | Fields Added |
|------|-------------|
| `workflows/strategy_discovery_router_v1.json` | `trigger`, `rollback`, per-node `on_failure` |
| `workflows/day_trading_discovery_v1.json` | `trigger`, `rollback`, per-node `on_failure` |
| `workflows/scalping_discovery_v1.json` | `trigger`, `rollback`, per-node `on_failure` |
| `workflows/candidate_review_v1.json` | `trigger`, `rollback`, per-node `on_failure`, `approval_required` |

**Rollback:** `git checkout -- workflows/`  
**Test:** `python -m pytest tests/ -x --tb=short` — engine should ignore unknown fields

---

### Batch 10: Component Registry (GAP-06)

Create `.agents/registry.json` indexing all components from Batches 1-9.

**Rollback:** `git checkout -- .agents/registry.json`  
**Test:** Validate JSON schema + verify all referenced paths exist

---

### Batch 11: Industry Update Skill & CLI (GAP-12 — Phase 6)

| Action | Path |
|--------|------|
| CREATE | `.agents/skills/industry-monitoring/SKILL.md` |
| CREATE | `src/agentic_forex/industry/` package |
| CREATE | `src/agentic_forex/industry/__init__.py` |
| CREATE | `src/agentic_forex/industry/report.py` |
| CREATE | `src/agentic_forex/industry/templates/report.html.jinja` |
| EDIT | `src/agentic_forex/cli/app.py` — add `industry-report` command |
| EDIT | `src/goblin/__init__.py` — add `industry` to bridge aliases |
| CREATE | `tests/test_industry_report.py` |
| CREATE | `reports/industry-update/.gitkeep` |

**Rollback:** `git checkout -- .agents/skills/industry-monitoring/ src/agentic_forex/industry/ src/goblin/__init__.py`; `git clean -fd reports/industry-update/`  
**Test:** `python -m pytest tests/test_industry_report.py -x --tb=short`

---

### Batch 12: Write GOBLIN.md (GAP-13)

Create root `GOBLIN.md` — canonical system document.

**Rollback:** `git checkout -- GOBLIN.md`  
**Test:** Verify all internal links resolve

---

## Batch Dependency Graph

```
Batch 0 (pre-flight)
  │
  ├── Batch 1 (delete duplicates)     ─── independent
  ├── Batch 2 (archive legacy skills)  ─── independent
  ├── Batch 3 (create adapters)        ─── independent
  │
  └── Batch 4 (canonical agents)       ─── depends on: Batch 2 (content absorption)
        │
        ├── Batch 5 (TOML adapters)    ─── depends on: Batch 4
        └── Batch 10 (registry)        ─── depends on: Batch 4, 9
  │
  ├── Batch 6 (identity rename)        ─── independent
  ├── Batch 7 (fix paths)              ─── independent
  ├── Batch 8 (vendor coupling)        ─── depends on: Batch 6 (credential naming)
  └── Batch 9 (workflow governance)    ─── independent
  │
  └── Batch 11 (industry update)       ─── depends on: Batch 4, 6
        │
        └── Batch 12 (GOBLIN.md)       ─── depends on: all prior batches
```

**Parallelizable groups:**
- Group A (independent): Batches 1, 2, 3, 6, 7, 9
- Group B (after Batch 4): Batches 5, 10
- Group C (after Batch 6): Batch 8
- Group D (after all): Batches 11, 12

---

## Rollback Strategy

### Per-Batch Rollback
Every batch specifies a `git checkout` command that reverts only that batch. Batches are designed to be independently revertible.

### Full Rollback
```powershell
git stash        # save any uncommitted work
git checkout .   # revert all tracked changes
git clean -fd docs/ .agents/agents/ .agents/hooks/ .github/ reports/industry-update/
```

### Resume After Partial Failure
1. Check which batch failed (last test failure)
2. Revert that batch only
3. Fix the issue
4. Re-run from the failed batch forward

---

## Validation Checkpoints

| After Batch | Validation |
|-------------|-----------|
| 0 | `pytest` passes; `git status` clean |
| 1 | `.codex/skills-src/` gone; `.agents/skills/` intact; `pytest` passes |
| 2 | `skills/` gone; `docs/archive/legacy-skills/` has 3 files |
| 3 | `.vscode/mcp.json`, `.github/copilot-instructions.md`, `.agents/hooks/README.md` exist |
| 4 | 17 files in `.agents/agents/`; all have valid YAML frontmatter |
| 5 | 8 TOML files have `canonical_ref` field |
| 6 | `grep -r "Agentic Forex" --include="*.md"` returns only `src/` and gitignored paths |
| 7 | `grep -rn "C:\\\\Users" --include="*.py" --include="*.toml"` returns 0 active-code hits |
| 8 | `goblin-practice` credential target works; OANDA default configurable |
| 9 | Workflow JSON files parse; engine loads without error |
| 10 | `registry.json` valid; all paths exist on disk |
| 11 | `goblin industry-report --help` works; test passes |
| 12 | `GOBLIN.md` links all resolve |
