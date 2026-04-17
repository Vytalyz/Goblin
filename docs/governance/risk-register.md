# Risk Register — Goblin Architecture Migration

**Generated:** 2026-04-13  
**Phase:** 5 — Operational Resilience  
**Purpose:** Track identified risks, their likelihood, impact, and mitigations

---

## Risk Matrix

| Likelihood \ Impact | Low | Medium | High |
|---------------------|-----|--------|------|
| **High** | — | — | — |
| **Medium** | R-05 | R-03, R-06 | R-01 |
| **Low** | R-07, R-08 | R-04 | R-02 |

---

## Risks

### R-01 — Credential Target Rename Breaks OANDA Research Runs

**Likelihood:** Medium  
**Impact:** High — blocks all data fetching and research  
**Phase:** Batch 8 (vendor coupling)  
**Description:** Renaming credential targets from `agentic-forex-practice/live` to `goblin-practice/live` will break OANDA API access if the secret store isn't updated simultaneously.  
**Mitigation:**
1. DEC-0006 mandates backward-compat aliases (old names continue to work)
2. Test credential resolution BEFORE dropping old names
3. Batch 8 rollback documented: `git checkout -- config/default.toml`
**Owner:** Operator  
**Status:** Open — mitigated by design

---

### R-02 — Workflow Engine Rejects Governance Fields (Strict JSON)

**Likelihood:** Low  
**Impact:** High — breaks all strategy discovery workflows  
**Phase:** Batch 9 (workflow governance extensions)  
**Description:** If the workflow engine uses strict JSON parsing and rejects unknown keys, adding `trigger`, `rollback`, and `on_failure` fields will cause runtime failures.  
**Mitigation:**
1. Test engine tolerance before applying batch
2. If strict: make engine tolerant first (DEC-0011)
3. Batch 9 rollback: `git checkout -- workflows/`
**Owner:** Kernel developer  
**Status:** Open — requires pre-flight validation

---

### R-03 — Bridge Alias Regression

**Likelihood:** Medium  
**Impact:** Medium — `import goblin.X` fails but `import agentic_forex.X` still works  
**Phase:** Batch 11 (industry update adds new package to bridge)  
**Description:** Adding `industry` to `src/goblin/__init__.py` bridge could introduce a bug if the aliasing pattern is disrupted.  
**Mitigation:**
1. Follow existing aliasing pattern exactly
2. Test both `from goblin.industry import report` and `from agentic_forex.industry import report`
3. Rollback: `git checkout -- src/goblin/__init__.py`
**Owner:** Operator  
**Status:** Open — standard development risk

---

### R-04 — Provider Adapter Staleness

**Likelihood:** Low  
**Impact:** Medium — operator loses capability with specific provider  
**Description:** Canonical definitions in `.agents/` may drift from provider adapters in `.codex/`, `.claude/`, `.vscode/` over time if updates are applied to canonical but not synchronized to adapters.  
**Mitigation:**
1. `.agents/registry.json` tracks adapter paths per component
2. Plan `goblin registry-sync` CLI to detect drift
3. Documentation in each adapter directory explains the reference pattern
**Owner:** Operator (ongoing)  
**Status:** Open — accepted risk with monitoring plan

---

### R-05 — Gitignored Artifacts Contain Stale Identity

**Likelihood:** Medium  
**Impact:** Low — cosmetic; no runtime effect  
**Description:** 200+ references to "Agentic Forex" and hardcoded Windows paths exist in gitignored artifacts (`data/`, `reports/`, `traces/`, `experiments/`). These won't be updated by the migration.  
**Mitigation:**
1. Decision: do not modify gitignored artifacts (they are generated output)
2. New runs will use updated identity/paths
3. Historical artifacts retain their original identity as provenance record
**Owner:** N/A  
**Status:** Accepted — no action required

---

### R-06 — Industry Report Feature Scope Creep

**Likelihood:** Medium  
**Impact:** Medium — delays migration completion  
**Phase:** Batch 11 (Phase 6)  
**Description:** The industry report capability could expand into complex web scraping, AI summarization, or multi-source aggregation that exceeds the migration scope.  
**Mitigation:**
1. DEC-0009 and DEC-0010 constrain scope: local data only, no API key required
2. Define MVP: aggregates existing corpus/experiment data into MD + HTML
3. AI-enhanced features are follow-up work, not Phase 6 requirements
**Owner:** Operator  
**Status:** Open — mitigated by scope constraints

---

### R-07 — Test Suite Has Pre-Existing Failures

**Likelihood:** Medium  
**Impact:** Low — hard to distinguish migration regressions from pre-existing issues  
**Description:** Terminal history shows `pytest` exit code 1 on the full suite, suggesting pre-existing test failures.  
**Mitigation:**
1. Batch 0 (pre-flight) records baseline test status
2. Track which tests fail BEFORE migration
3. Migration batches only need to verify no NEW failures  
4. Use `pytest --lf` (last-failed) to quickly check for new regressions
**Owner:** Operator  
**Status:** Open — requires baseline capture

---

### R-08 — Codex Agent TOML Format Changes Upstream

**Likelihood:** Low  
**Impact:** Low — only affects Codex provider adapter  
**Description:** OpenAI may change the Codex agent TOML schema, breaking existing `.codex/agents/*.toml` files.  
**Mitigation:**
1. Canonical definitions are in `.agents/agents/` (Markdown) — unaffected
2. TOML adapters can be regenerated from canonical definitions
3. `.codex/AGENTS.md` and `config.toml` track Codex-specific conventions
**Owner:** Operator (reactive)  
**Status:** Accepted — inherent external dependency risk

---

## Risk Tracking

| ID | Status | Last Reviewed | Trigger |
|----|--------|---------------|---------|
| R-01 | Open (mitigated) | 2026-04-13 | Batch 8 execution |
| R-02 | Open | 2026-04-13 | Batch 9 pre-flight |
| R-03 | Open | 2026-04-13 | Batch 11 execution |
| R-04 | Open | 2026-04-13 | Ongoing post-migration |
| R-05 | Accepted | 2026-04-13 | N/A |
| R-06 | Open (constrained) | 2026-04-13 | Phase 6 planning |
| R-07 | Open | 2026-04-13 | Batch 0 execution |
| R-08 | Accepted | 2026-04-13 | Codex platform updates |
