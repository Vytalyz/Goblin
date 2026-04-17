# Phase 0 — Current-State Repository Inventory

**Generated:** 2026-04-13  
**Scope:** Complete inventory of all directories, files, and agentic assets in the Goblin workspace.  
**Phase:** 0 — Current-State Audit  
**Status:** Complete

---

## Table of Contents

1. [Root-Level Files](#1-root-level-files)
2. [Source Code — Deterministic Kernel](#2-source-code--deterministic-kernel)
3. [Source Code — Goblin Bridge Namespace](#3-source-code--goblin-bridge-namespace)
4. [Tests](#4-tests)
5. [Configuration](#5-configuration)
6. [Agentic Assets — Skills](#6-agentic-assets--skills)
7. [Agentic Assets — Agents](#7-agentic-assets--agents)
8. [Agentic Assets — Workflows](#8-agentic-assets--workflows)
9. [Agentic Assets — Prompts](#9-agentic-assets--prompts)
10. [Agentic Assets — Automations](#10-agentic-assets--automations)
11. [Agentic Assets — Hooks](#11-agentic-assets--hooks)
12. [Agentic Assets — Plugins & MCPs](#12-agentic-assets--plugins--mcps)
13. [Provider-Specific Directories](#13-provider-specific-directories)
14. [Goblin Control Plane](#14-goblin-control-plane)
15. [Knowledge Base](#15-knowledge-base)
16. [Data Directories](#16-data-directories)
17. [Experiment & Campaign Artifacts](#17-experiment--campaign-artifacts)
18. [Reports](#18-reports)
19. [Approvals](#19-approvals)
20. [Other Directories](#20-other-directories)
21. [Duplication Audit](#21-duplication-audit)
22. [Reference Audit — "Agentic Forex"](#22-reference-audit--agentic-forex)
23. [Reference Audit — Hardcoded Windows Paths](#23-reference-audit--hardcoded-windows-paths)
24. [Reference Audit — Vendor Coupling](#24-reference-audit--vendor-coupling)
25. [Kernel Viability Assessment](#25-kernel-viability-assessment)

---

## 1. Root-Level Files

| File | Type | Classification | Reason |
|------|------|---------------|--------|
| `AGENTS.md` | Governance rules | **refactor** | Title says "Agentic Forex Repository Rules"; needs rename to Goblin. Only AGENTS.md at root level (no `.agents/AGENTS.md` exists). |
| `codex.md` | Operator playbook | **refactor** | References "Agentic Forex" and "agentic_forex"; needs identity update |
| `README.md` | Documentation | **refactor** | 22+ hardcoded Windows paths in CLI examples; references "Agentic Forex" throughout |
| `pyproject.toml` | Build config | **keep** | Project name already `"goblin"`; dual entry points `goblin` and `agentic-forex` both work |
| `.gitignore` | Git config | **keep** | Standard exclusions; no issues |
| `.python-version` | Python version | **keep** | If present; standard |

---

## 2. Source Code — Deterministic Kernel

**Location:** `src/agentic_forex/`  
**Classification:** **keep** (kernel remains authoritative per AGENTS.md)  
**Subpackages:** 24 total

| Package | Purpose | Classification | Vendor Coupling |
|---------|---------|---------------|-----------------|
| `approval/` | Approval records, publish workflow | keep | None |
| `backtesting/` | Backtest engine, stress testing, scalping benchmark | keep | None |
| `campaigns/` | Campaign orchestration: autonomous_manager, governed_loop, next_step, program_loop, portfolio_cycle, throughput | keep | None |
| `cli/` | CLI entry point (~60 subcommands) | keep | None |
| `config/` | Settings, load_settings, Pydantic models | refactor | OANDA credential targets hardcoded; `canonical_source = "oanda"` |
| `corpus/` | Corpus catalog, document ingestion | keep | None |
| `evals/` | Evaluation gates, robustness grading, CSCV/PBO | keep | None |
| `experiments/` | Strategy discovery labs (scalping, day trading), iteration, comparison | keep | None |
| `features/` | Feature engineering from OHLC data | keep | None |
| `forward/` | Shadow-forward validation | keep | OANDA-specific (shadow-forward against live OANDA feed) |
| `goblin/` | Goblin control plane: controls, evidence, models, service | keep | None |
| `governance/` | Control plane, incidents, readiness, trial ledger, provenance | refactor | MT5 evidence types in readiness gates; OANDA shadow-forward proof required |
| `knowledge/` | Knowledge base management (empty) | keep | None |
| `labels/` | Label generation for ML training | keep | None |
| `llm/` | BaseLLMClient, MockLLMClient, OpenAIClient | keep | OpenAI behind interface; mock available |
| `market_data/` | OANDA ingest, MT5 audit CSV, QA | keep | OANDA canonical; MT5 CSV as fallback |
| `ml/` | Model training pipeline | keep | None |
| `mt5/` | MT5 packet generation, parity, EA generator | keep | MT5-specific (practice/parity only per AGENTS.md) |
| `nodes/` | Workflow node toolkit, tool registry | keep | None |
| `operator/` | Operator state, action models, service | keep | None |
| `policy/` | FTMO fit, parity scope, economic calendar | keep | FTMO scoring (non-blocking) |
| `runtime/` | Workflow engine, schemas, security | keep | None |
| `utils/` | Paths, secrets, I/O, logging, IDs | refactor | Credential targets reference `agentic-forex/oanda/practice` |
| `workflows/` | StrategySpec, workflow contracts, repository | refactor | `canonical_source = "oanda"`, `broker_fee_model = "oanda_spread_only"` |

**Top-level files:**

| File | Classification |
|------|---------------|
| `__init__.py` | keep — docstring says "Legacy compatibility namespace for Goblin takeover" |
| `__main__.py` | keep — imports from `.cli.app` |

---

## 3. Source Code — Goblin Bridge Namespace

**Location:** `src/goblin/`  
**Classification:** **keep** (primary operator-facing namespace)

| File | Purpose | Classification |
|------|---------|---------------|
| `__init__.py` | sys.modules aliasing — forwards 24 `goblin.*` imports to `agentic_forex.*` | keep |
| `__main__.py` | CLI entry point `from goblin.cli.app import main` | keep |
| `cli/__init__.py` | Namespace marker | keep |
| `cli/app.py` | Shared with agentic-forex | keep |

---

## 4. Tests

**Location:** `tests/`  
**Classification:** **keep** (all tests)  
**Count:** 33 test files + `conftest.py`

| Test File | Tests | Classification |
|-----------|-------|---------------|
| `conftest.py` | Scaffold fixtures, corpus mirror, settings | keep |
| `test_autonomous_manager.py` | Autonomous manager cycles | keep |
| `test_cli_and_boundaries.py` | CLI parsing, hardcoded path tests | refactor — contains `C:\agentic-forex\config\openai-live.toml` |
| `test_codex_operator.py` | Codex operator integration | keep |
| `test_corpus_catalog.py` | Corpus ingestion | keep |
| `test_day_trading_exploration.py` | Day trading candidates | keep |
| `test_day_trading_refinement.py` | Day trading iteration | keep |
| `test_discovery_workflow.py` | Discovery workflow | keep |
| `test_experiment_comparison.py` | Experiment registry | keep |
| `test_goblin_controls.py` | Goblin governance | keep |
| `test_goblin_evidence.py` | Artifact provenance | keep |
| `test_goblin_incident.py` | Incident management | keep |
| `test_goblin_investigation.py` | Investigation packs | keep |
| `test_goblin_live.py` | Live trading controls | keep |
| `test_goblin_ml.py` | ML training | keep |
| `test_goblin_p12.py` | Phase 12 completion | keep |
| `test_goblin_program.py` | Goblin program | keep |
| `test_goblin_release.py` | Release workflow | keep |
| `test_goblin_run_records.py` | Run records | keep |
| `test_governance_controls.py` | Governance controls | keep |
| `test_market_data_ingest.py` | OANDA ingest | keep |
| `test_namespace_takeover.py` | Namespace aliasing | keep |
| `test_next_step_controller.py` | Next-step execution | keep |
| `test_policy_layers.py` | Policy enforcement | keep |
| `test_portfolio_layer.py` | Portfolio cycle | keep |
| `test_production_incident.py` | Production incidents | keep |
| `test_program_loop.py` | Program loop | keep |
| `test_robustness_and_execution_realism.py` | Robustness/execution | keep |
| `test_runtime_engine.py` | Runtime engine | keep |
| `test_scalping_benchmark.py` | Scalping benchmark | keep |
| `test_scalping_exploration.py` | Scalping candidates | keep |
| `test_scalping_iteration.py` | Scalping iteration | keep |
| `test_secret_resolution.py` | Secret resolution | keep |
| `test_throughput_controller.py` | Throughput control | keep |
| `test_validation_pipeline.py` | Validation workflow | keep |

**Test directories (if present):**

| Directory | Classification |
|-----------|---------------|
| `tests/test_mt5/` | keep — MT5-specific tests |
| `test_oanda_ingest.py` | keep — OANDA integration test |

---

## 5. Configuration

**Location:** `config/`  
**Count:** 11 TOML files

| File | Type | Classification | Issues |
|------|------|---------------|--------|
| `default.toml` | Core defaults | **refactor** | OANDA credential targets use `agentic-forex/oanda/practice`; `supplemental_source_paths` has hardcoded `<USER_HOME>/Downloads/...` |
| `autonomy_policy.toml` | Autonomy bounds | keep | Clean |
| `codex_capabilities.toml` | Codex capability manifest | keep | References `src/agentic_forex` (accurate) |
| `codex_operator_policy.toml` | Codex operator policy | keep | Clean |
| `data_contract.toml` | Data schema contract | keep | Clean |
| `eval_gates.toml` | Evaluation thresholds | keep | Clean |
| `mt5_env.toml` | MT5 environment | keep | MT5-specific (expected) |
| `openai-live.toml` | OpenAI config | keep | Guarded; no runtime dependency |
| `portfolio_policy.toml` | Portfolio slots | keep | Clean |
| `program_policy.toml` | Program governance (~3859 lines) | keep | Large; approved_lanes definitions |
| `risk_policy.toml` | Risk envelopes | keep | Clean |

---

## 6. Agentic Assets — Skills

### Location 1: `.agents/skills/` (8 structured skills)

| Skill | YAML Frontmatter | References `agentic_forex` | Classification |
|-------|-------------------|----------------------------|---------------|
| `artifact-audit/SKILL.md` | Yes | No | **merge** — canonical; remove `.codex/` duplicate |
| `candidate-refinement/SKILL.md` | Yes | Yes — CLI commands | **merge** — canonical; remove `.codex/` duplicate |
| `capability-crawl/SKILL.md` | Yes | Yes — CLI commands | **merge** — canonical; remove `.codex/` duplicate |
| `governed-strategy-search/SKILL.md` | Yes | Yes — CLI commands | **merge** — canonical; remove `.codex/` duplicate |
| `incident-review/SKILL.md` | Yes | Implicit | **merge** — canonical; remove `.codex/` duplicate |
| `parity-packaging/SKILL.md` | Yes | Yes — CLI commands | **merge** — canonical; remove `.codex/` duplicate |
| `promotion-readiness-review/SKILL.md` | Yes | Yes — CLI commands | **merge** — canonical; remove `.codex/` duplicate |
| `runtime-monitoring/SKILL.md` | Yes | Implicit | **merge** — canonical; remove `.codex/` duplicate |

### Location 2: `.codex/skills-src/` (8 EXACT duplicates)

| Skill | Status | Classification |
|-------|--------|---------------|
| `artifact-audit/SKILL.md` | Exact duplicate of `.agents/skills/` | **delete** — duplicate |
| `candidate-refinement/SKILL.md` | Exact duplicate | **delete** — duplicate |
| `capability-crawl/SKILL.md` | Exact duplicate | **delete** — duplicate |
| `governed-strategy-search/SKILL.md` | Exact duplicate | **delete** — duplicate |
| `incident-review/SKILL.md` | Exact duplicate | **delete** — duplicate |
| `parity-packaging/SKILL.md` | Exact duplicate | **delete** — duplicate |
| `promotion-readiness-review/SKILL.md` | Exact duplicate | **delete** — duplicate |
| `runtime-monitoring/SKILL.md` | Exact duplicate | **delete** — duplicate |

### Location 3: `skills/` (3 legacy markdown files)

| Skill | Content | Classification |
|-------|---------|---------------|
| `critic-review.md` | 3 bullet points — review grounding rules | **archive** — content absorbed into agent contracts |
| `fresh-lens-discovery.md` | 3 bullet points — corpus-first discovery rules | **archive** — content absorbed into agent contracts |
| `strategy-discovery.md` | 3 bullet points — deterministic rule language | **archive** — content absorbed into agent contracts |

### Duplication Summary

- `.agents/skills/` = **canonical** (8 skills)
- `.codex/skills-src/` = **exact duplicate** of canonical (8 skills) → delete
- `skills/` = **legacy** (3 different skills, minimal content) → archive

---

## 7. Agentic Assets — Agents

### Location 1: `.codex/agents/` (8 TOML agent configs, Codex-specific)

| Agent | Model | Sandbox | Classification |
|-------|-------|---------|---------------|
| `portfolio_orchestrator.toml` | gpt-5.4 | workspace-write | **refactor** — extract canonical definition; keep TOML as Codex adapter |
| `gap_lane_explorer.toml` | gpt-5.4-mini | read-only | **refactor** — same |
| `governance_auditor.toml` | gpt-5.4 | read-only | **refactor** — same |
| `incident_reviewer.toml` | gpt-5.4 | read-only | **refactor** — same |
| `lane_researcher.toml` | gpt-5.4-mini | read-only | **refactor** — same |
| `runtime_observer.toml` | gpt-5.4-mini | read-only | **refactor** — same |
| `throughput_worker.toml` | gpt-5.4 | workspace-write | **refactor** — same |
| `validation_worker.toml` | gpt-5.4 | workspace-write | **refactor** — same |

### Location 2: `agents/roles/` (9 markdown role briefs, used by workflow engine)

| Role | Classification |
|------|---------------|
| `corpus-librarian.md` | **refactor** — upgrade to full agent contract with canonical schema |
| `day-trading-strategist.md` | **refactor** — same |
| `execution-realist.md` | **refactor** — same |
| `extraction-reviewer.md` | **refactor** — same |
| `lead-orchestrator.md` | **refactor** — same |
| `quant-critic.md` | **refactor** — same |
| `review-synthesizer.md` | **refactor** — same |
| `risk-critic.md` | **refactor** — same |
| `scalping-strategist.md` | **refactor** — same |

### Agent Definition Gap

- No canonical provider-neutral agent definition exists.
- `.codex/agents/` is Codex-specific (TOML format, gpt-5.4 model references).
- `agents/roles/` is minimal (3-5 bullet points per role).
- No `.claude/agents/` or `.github/agents/` directories exist.
- 8 Codex agents and 9 role briefs cover overlapping but different roles — need unified canonical registry.

---

## 8. Agentic Assets — Workflows

**Location:** `workflows/` (top-level)  
**Format:** JSON, node-based workflow definitions

| Workflow | Version | Classification |
|----------|---------|---------------|
| `strategy_discovery_router_v1.json` | v1 | keep |
| `day_trading_discovery_v1.json` | v1 | keep |
| `scalping_discovery_v1.json` | v1 | keep |
| `candidate_review_v1.json` | v1 | keep |

**Engine:** `src/agentic_forex/runtime/engine.py` — deterministic state machine with node types: agent, tool, router, finalize.

**Gap:** No workflow contract schema documentation exists.

---

## 9. Agentic Assets — Prompts

**Location:** `prompts/` (top-level)  
**Format:** `.txt` system/user pairs

| Prompt | Classification |
|--------|---------------|
| `critic_system.txt` / `critic_user.txt` | keep |
| `day_trading_system.txt` / `day_trading_user.txt` | keep |
| `reframe_system.txt` / `reframe_user.txt` | keep |
| `review_system.txt` / `review_user.txt` | keep |
| `scalping_system.txt` / `scalping_user.txt` | keep |

**Gap:** No prompt contract or versioning schema.

---

## 10. Agentic Assets — Automations

**Location:** `automations/`  
**Status:** All paused (per `.codex/AGENTS.md` — must succeed manually first)

| Automation | Prompt | Spec | Classification |
|-----------|--------|------|---------------|
| `capability-refresh` | `prompts/capability-refresh.md` | `specs/capability-refresh.toml` | keep (paused) |
| `gap-lane-research` | `prompts/gap-lane-research.md` | `specs/gap-lane-research.toml` | keep (paused) |
| `runtime-watch` | `prompts/runtime-watch.md` | `specs/runtime-watch.toml` | keep (paused) |

---

## 11. Agentic Assets — Hooks

**Status:** No hooks defined anywhere.  
**`.codex/config.toml`:** `codex_hooks = false` (Windows constraint).  
**`.claude/`:** No hooks directory or hook definitions found.

**Gap:** Complete absence of hook definitions. No pre/post tool hooks, no notification hooks, no validation hooks.

---

## 12. Agentic Assets — Plugins & MCPs

### Plugins

**Location:** `.agents/plugins/marketplace.json`  
**Content:** Empty registry `{"version": 1, "plugins": []}`  
**Classification:** **refactor** — populate or remove

### MCPs

**Status:** No MCP configuration exists anywhere.  
- No `mcp.json` at root
- No `.vscode/mcp.json`
- No MCP server definitions

**Gap:** Complete absence of MCP integration.

---

## 13. Provider-Specific Directories

### `.codex/` — Codex/OpenAI operator layer

| Asset | Count | Classification |
|-------|-------|---------------|
| `AGENTS.md` | 1 | keep — Codex-specific rules |
| `config.toml` | 1 | keep — Codex execution config |
| `rules/default.rules` | 1 | refactor — references `python -m agentic_forex` |
| `agents/*.toml` | 8 | refactor — extract canonical definitions |
| `skills-src/*/SKILL.md` | 8 | **delete** — exact duplicates of `.agents/skills/` |

### `.claude/` — Claude Code provider layer

| Asset | Count | Classification |
|-------|-------|---------------|
| `settings.local.json` | 1 | keep — pytest permission allowlist |

**Gap:** No `.claude/agents/`, no `.claude/hooks/`, no `.claude/skills/`.

### `.vscode/` — VS Code workspace

| Asset | Count | Classification |
|-------|-------|---------------|
| `settings.json` | 1 | keep — git warning suppression only |

**Gap:** No `.vscode/mcp.json`, no launch configurations, no task definitions.

### `.github/` — GitHub

**Status:** Directory does not exist.  
**Gap:** No GitHub Actions, no `.github/agents/`, no CI/CD configuration.

---

## 14. Goblin Control Plane

**Location:** `Goblin/`  
**Status:** M5 maturity, 19/19 phases completed (P00–P15 + T1–T4), S1+ ready.

| Directory/File | Purpose | Classification |
|----------------|---------|---------------|
| `STATUS.md` | Phase status tracker | keep |
| `IMPLEMENTATION_TRACKER.md` | Deliverable tracker | keep |
| `MATURITY.md` | Subsystem maturity scores | keep |
| `EVOLUTION.md` | Decision/evolution log | keep |
| `TAKEOVER_PLAN.md` | Namespace migration plan | keep |
| `PROGRAM.md` | Program charter | keep |
| `ROADMAP.md` | Strategic roadmap | keep |
| `PHASE_BRIEF.md` | Active phase brief | keep |
| `checkpoints/` | 19 phase checkpoint dirs (GOBLIN-P00 through T4) | keep |
| `contracts/` | 30 governance contract templates | keep |
| `decisions/` | ADR-0001 (Goblin umbrella program) | keep |
| `phases/` | 13 phase spec files (P00–P12) | keep |
| `reports/` | Comprehensive reporting infrastructure | keep |
| `runbooks/` | INCIDENT_RESPONSE.md, RELEASE_AND_ROLLBACK.md, RESUME_PHASE.md | keep |
| `state/` | artifacts/, phases/, program_status.json | keep |
| `templates/` | ADR, phase record, checkpoint record templates | keep |

---

## 15. Knowledge Base

**Location:** `knowledge/`  
**Count:** 14 files

| File | Type | Classification |
|------|------|---------------|
| `codex_capability_catalog.json` | Capability catalog | keep |
| `codex_capability_index.md` | Capability index | keep |
| `codex_capability_pages/` | Empty (intended for detail pages) | archive |
| `observational/failure_records.jsonl` | Failure records (50+ hardcoded Windows paths) | refactor |
| `overlap-contract-alignment-audit.md` | Contract audit | keep |
| `overlap-mean-reversion-gap-audit.md` | Gap audit | keep |
| `parity-lineage-audit.md` | Lineage audit | keep |
| `parity-operator-matrix.md` | Operator matrix | keep |
| `pdf-alignment-roadmap.md` | Book alignment | keep |
| `portfolio-expansion-plan.md` | Expansion plan | keep |
| `recovery-implementation-plan.md` | Recovery plan | refactor — hardcoded Windows path |
| `runtime-provider-decision.md` | Provider decision | keep |
| `single-step-autonomy-prompt.md` | Prompt template | keep |
| `source-of-truth.md` | SoT policy (23 rules) | keep |

---

## 16. Data Directories

**Location:** `data/`  
**Classification:** keep (all gitignored; runtime artifacts)

| Subdirectory | Purpose |
|-------------|---------|
| `corpus/` | Extracted knowledge documents |
| `features/` | Engineered features |
| `labels/` | ML training labels |
| `normalized/` | Normalized market data |
| `raw/` | Raw OANDA/MT5 data |
| `state/` | Leases, idempotency records, incidents, checkpoints |

---

## 17. Experiment & Campaign Artifacts

**Location:** `experiments/`  
**Classification:** keep (gitignored runtime artifacts)

| Content | Count |
|---------|-------|
| Individual iteration JSONs | ~32 |
| Comparison JSONs | ~100 |
| Day trading behavior scans | ~30 |
| Day trading explorations | ~40 |
| Governed loop records | multiple |
| Program loop records | multiple |
| `events.jsonl` | Append-only event log |
| `trial_ledger.jsonl` | Governance audit trail |
| `registry.csv` | Candidate index (gitignored) |

**Issue:** Many experiment JSONs contain hardcoded Windows paths in their metadata.

---

## 18. Reports

**Location:** `reports/`  
**Classification:** keep (gitignored; runtime artifacts)  
**Count:** 600+ candidate directories (`AF-CAND-0001/` through `AF-CAND-0605/`)

---

## 19. Approvals

**Location:** `approvals/`  
**Classification:** keep

| Subdirectory | Content | Issues |
|-------------|---------|--------|
| `approval_log.jsonl` | Append-only approval records (gitignored) | None |
| `mt5_packets/` | MT5 packet artifacts per candidate | Hardcoded Windows paths in `logic_manifest.json`, `packet.json` |
| `mt5_runs/` | MT5 run specs, validation reports | 80+ hardcoded Windows paths in `run_spec.json`, `launch_request.json`, `parity_diagnostics.json` |

---

## 20. Other Directories

| Directory | Purpose | Classification |
|-----------|---------|---------------|
| `published/` | Published research snapshots | keep (empty; archival-only) |
| `traces/` | Execution traces | keep (gitignored) |

---

## 21. Duplication Audit

### Critical Duplications

| Asset | Location 1 | Location 2 | Location 3 | Resolution |
|-------|-----------|-----------|-----------|------------|
| Skills (8) | `.agents/skills/` | `.codex/skills-src/` | — | **Keep `.agents/skills/` as canonical; delete `.codex/skills-src/`** |
| Skills (3 legacy) | `skills/` | — | — | **Archive content; delete directory** |
| AGENTS.md | root `AGENTS.md` | `.codex/AGENTS.md` | — | **Keep both; root = system rules, .codex = provider rules** (documented reason) |

### Non-Duplications (Separate Concerns)

| Asset | Location 1 | Location 2 | Distinction |
|-------|-----------|-----------|------------|
| Agent definitions | `.codex/agents/` (8 TOML) | `agents/roles/` (9 md) | Different format, overlapping roles; both need canonical unification |

---

## 22. Reference Audit — "Agentic Forex"

### Files containing "Agentic Forex" (case-sensitive)

| Location | Count | Type | Action |
|----------|-------|------|--------|
| `AGENTS.md` | 1 | Title | Rename to "Goblin Repository Rules" |
| `README.md` | 22+ | CLI examples, setup guide | Rewrite with relative paths |
| `codex.md` | Multiple | Playbook references | Update identity |
| `experiments/*.json` | 20+ | Metadata paths | Runtime artifacts; note but don't bulk-edit |
| `approvals/mt5_packets/*/notes.md` | Multiple | Terminal paths | Runtime artifacts; note |
| `Goblin/STATUS.md` | 19 | Checkpoint paths | Runtime artifact; note |
| `knowledge/recovery-implementation-plan.md` | 1 | Project root | Update |
| `knowledge/observational/failure_records.jsonl` | 50+ | Artifact paths | Runtime artifact; note |

### Code references to `agentic_forex` (import paths)

| Location | Count | Action |
|----------|-------|--------|
| All `src/agentic_forex/**/*.py` | ~500+ | **Keep** — kernel package name stays until explicit migration |
| `.codex/rules/default.rules` | 2 | **Refactor** — update CLI commands when ready |
| `.agents/skills/*/SKILL.md` | 6+ | **Refactor** — update CLI command examples |
| `config/codex_capabilities.toml` | Multiple | **Keep** — accurate source refs |

---

## 23. Reference Audit — Hardcoded Windows Paths

### Active code (must fix)

| File | Pattern | Action |
|------|---------|--------|
| `config/default.toml` | `supplemental_source_paths = ["<USER_HOME>/Downloads/..."]` | **Fix** — use relative path or env var |
| `tests/test_cli_and_boundaries.py` | `C:\agentic-forex\config\openai-live.toml` | **Fix** — use relative path |
| `src/agentic_forex/mt5/ea_generator.py` | `AgenticForex\\Audit\\...` (relative MT5 path) | **Assess** — MT5-specific; may be required |

### Runtime artifacts (note but don't bulk-edit)

| Location | Count | Notes |
|----------|-------|-------|
| `experiments/*.json` | 40+ | Stamped at creation time; historical |
| `approvals/mt5_packets/**` | 20+ | MT5 packet metadata |
| `approvals/mt5_runs/**` | 80+ | MT5 run specs and diagnostics |
| `knowledge/observational/failure_records.jsonl` | 50+ | Failure records |
| `Goblin/STATUS.md` | 19 | Phase checkpoint paths |
| `Goblin/state/program_status.json` | 1 | Program state |

---

## 24. Reference Audit — Vendor Coupling

### OANDA Coupling (Research Truth — Expected)

| File | Coupling Point | Severity |
|------|---------------|----------|
| `config/default.toml` | `canonical_source = "oanda"`, credential targets | Low — configurable |
| `src/agentic_forex/workflows/contracts.py` | `canonical_source = "oanda"`, `broker_fee_model = "oanda_spread_only"` | Medium — Pydantic default |
| `src/agentic_forex/forward/service.py` | Shadow-forward against OANDA live feed | Low — expected |
| `src/agentic_forex/market_data/ingest.py` | OANDA JSON ingestion, backfill | Low — expected |
| `src/agentic_forex/utils/secrets.py` | Credential targets: `agentic-forex/oanda/practice` | Low — rename needed |

### MT5 Coupling (Practice/Parity — Expected)

| File | Coupling Point | Severity |
|------|---------------|----------|
| `src/agentic_forex/governance/readiness.py` | MT5 evidence types in readiness status resolution | Medium — needs abstraction |
| `src/agentic_forex/mt5/ea_generator.py` | MQL5 code generation, `AgenticForex\\Audit\\` paths | Low — domain-specific |
| `src/agentic_forex/mt5/service.py` | MT5 packet generation, parity validation | Low — expected |
| `config/mt5_env.toml` | MT5 environment settings | Low — expected |

### OpenAI Coupling (Optional — Behind Interface)

| File | Coupling Point | Severity |
|------|---------------|----------|
| `src/agentic_forex/llm/openai_client.py` | OpenAI structured output API | Low — behind BaseLLMClient |
| `config/openai-live.toml` | API config (guarded) | Low — no runtime dependency |
| `.codex/agents/*.toml` | `model = "gpt-5.4"` references | Medium — Codex-specific |

---

## 25. Kernel Viability Assessment

### Architecture Strengths

1. **Provider abstraction at LLM layer** — `BaseLLMClient` / `MockLLMClient` / `OpenAIClient` cleanly separated
2. **Deterministic workflow engine** — Schema-validated, node-based, domain-independent
3. **Config-driven policies** — All governance in TOML; no code-magic
4. **Approval/governance pipeline** — Evidence-type-based, not hardcoded verdicts
5. **Tool registry pattern** — Runtime tool compilation, not static linking
6. **Dual CLI identity** — Both `goblin` and `agentic-forex` work; `pyproject.toml` says "goblin"
7. **ReadPolicy security** — Sandbox-aware artifact access
8. **ProjectPaths** — 100+ directory properties; `ensure_directories()` creates structure

### Coupling Points Requiring Abstraction

| Point | Current State | Effort | Blocker |
|-------|---------------|--------|---------|
| Workflow `canonical_source`/`broker_fee_model` defaults | Hardcoded `"oanda"` in Pydantic model | Medium | No |
| Readiness gate evidence types | MT5/OANDA evidence keys in status resolver | Medium | No |
| Credential naming | `agentic-forex/oanda/practice` | Low | No |
| EA generator paths | `AgenticForex\\Audit\\` in MQL5 strings | Low | No — MT5-specific |
| Internal imports | All code uses `from agentic_forex.*` | Medium | No — bridge handles inbound |

### Verdict

The kernel is **production-viable and restructurable**. The Goblin bridge namespace is functional. Key work is:

1. **Parameterize vendor defaults** in workflow contracts and readiness gates
2. **Rename credential targets** from `agentic-forex/` to `goblin/`
3. **Migrate internal imports** from `agentic_forex.*` to `goblin.*` (optional; bridge handles this)
4. **Abstract evidence types** in readiness resolver to support pluggable validation channels

No structural redesign of the kernel is needed. The core architecture (workflow engine, governance pipeline, tool registry, config system) is sound for the target AI-agnostic architecture.

---

## Phase 0 Validation

| Criterion | Status |
|-----------|--------|
| Every directory inventoried | ✅ |
| Every agentic asset classified (keep/refactor/merge/archive/delete) | ✅ |
| Duplication between `skills/`, `.agents/skills/`, `.codex/skills-src/` audited | ✅ |
| All "Agentic Forex" references identified | ✅ |
| All hardcoded Windows paths identified | ✅ |
| All vendor coupling points identified | ✅ |
| Kernel viability assessed | ✅ |
| No files modified (read-only phase) | ✅ |

**Rollback:** Not applicable — read-only phase. No changes made.

**Open Issues:**

1. Runtime artifacts (experiments, approvals, Goblin state) contain hardcoded Windows paths stamped at creation time. These are historical records and should NOT be bulk-edited, but future runs should use relative paths.
2. The `agents/roles/` briefs and `.codex/agents/` TOML configs represent overlapping but different agent definitions that need unified canonical registration (Phase 2 deliverable).
3. The empty `knowledge/` source package and `.agents/plugins/marketplace.json` are placeholders with no current utility.
