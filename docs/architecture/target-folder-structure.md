# Phase 2a — Goblin Target Folder Structure

**Generated:** 2026-04-13  
**Phase:** 2 — Target Architecture  
**Inputs:** Phase 0 inventory, Phase 1 provider comparison

---

## Design Principles

1. **One canonical home per component type** — no duplication without documented reason
2. **Provider-neutral core** — canonical definitions use portable formats (Markdown, YAML frontmatter, JSON, TOML)
3. **Provider adapters isolated** — each provider gets its own dotfile directory for provider-specific wiring
4. **MCP as universal tool interface** — all external tool integrations use MCP
5. **No hardcoded absolute paths** — all paths relative to project root or resolved via `ProjectPaths`
6. **Goblin-canonical systems untouched** — workflow engine, eval system, approval pipeline, state/checkpoints, telemetry stay where they are

---

## Target Directory Tree

```
Goblin/                              # ← workspace root (renamed from "Agentic Forex")
│
├── GOBLIN.md                        # Canonical system document — single entry point
├── AGENTS.md                        # Repository governance rules (renamed title)
├── codex.md                         # Codex operator playbook (updated identity)
├── README.md                        # Project overview (updated, no hardcoded paths)
├── pyproject.toml                   # Build config (already name="goblin")
├── .gitignore                       # Git exclusions
│
├── .agents/                         # ═══ CANONICAL agentic definitions (provider-neutral) ═══
│   ├── agents/                      # Canonical agent definitions (Markdown + YAML frontmatter)
│   │   ├── portfolio-orchestrator.md
│   │   ├── gap-lane-explorer.md
│   │   ├── governance-auditor.md
│   │   ├── incident-reviewer.md
│   │   ├── lane-researcher.md
│   │   ├── runtime-observer.md
│   │   ├── throughput-worker.md
│   │   ├── validation-worker.md
│   │   ├── corpus-librarian.md      # Upgraded from agents/roles/
│   │   ├── day-trading-strategist.md
│   │   ├── execution-realist.md
│   │   ├── extraction-reviewer.md
│   │   ├── lead-orchestrator.md
│   │   ├── quant-critic.md
│   │   ├── review-synthesizer.md
│   │   ├── risk-critic.md
│   │   └── scalping-strategist.md
│   │
│   ├── skills/                      # Canonical skill definitions (already here — keep)
│   │   ├── artifact-audit/SKILL.md
│   │   ├── candidate-refinement/SKILL.md
│   │   ├── capability-crawl/SKILL.md
│   │   ├── governed-strategy-search/SKILL.md
│   │   ├── incident-review/SKILL.md
│   │   ├── industry-monitoring/SKILL.md    # NEW — Phase 6 deliverable
│   │   ├── parity-packaging/SKILL.md
│   │   ├── promotion-readiness-review/SKILL.md
│   │   └── runtime-monitoring/SKILL.md
│   │
│   ├── hooks/                       # Canonical hook definitions (provider-neutral contracts)
│   │   └── README.md                # Hook contract schema; implementations in provider dirs
│   │
│   ├── plugins/                     # Plugin registry
│   │   └── marketplace.json         # Populated or removed
│   │
│   └── registry.json                # Component registry — machine-readable index of all agents, skills, hooks
│
├── .claude/                         # ═══ Claude Code provider adapter ═══
│   ├── settings.local.json          # Claude Code local settings (already exists)
│   ├── hooks/                       # Claude-specific hook implementations (PowerShell handlers)
│   │   ├── pre-tool-use.json
│   │   └── post-tool-use.json
│   ├── agents/                      # Claude sub-agent wiring (refs → .agents/agents/)
│   │   └── README.md                # Explains: agents here import from .agents/agents/ canonical defs
│   └── CLAUDE.md                    # Claude-specific project instructions
│
├── .codex/                          # ═══ OpenAI Codex provider adapter ═══
│   ├── AGENTS.md                    # Codex-specific rules (already exists — keep)
│   ├── config.toml                  # Codex execution config (already exists — keep)
│   ├── rules/                       # Codex command allowlist
│   │   └── default.rules            # Updated CLI refs
│   └── agents/                      # Codex agent TOML configs (refs → .agents/agents/ for mission/scope)
│       ├── portfolio_orchestrator.toml
│       ├── gap_lane_explorer.toml
│       ├── governance_auditor.toml
│       ├── incident_reviewer.toml
│       ├── lane_researcher.toml
│       ├── runtime_observer.toml
│       ├── throughput_worker.toml
│       └── validation_worker.toml
│   # NOTE: .codex/skills-src/ REMOVED — was exact duplicate of .agents/skills/
│
├── .vscode/                         # ═══ VS Code / GitHub Copilot provider adapter ═══
│   ├── settings.json                # Workspace settings (already exists)
│   └── mcp.json                     # MCP server configuration (NEW)
│
├── .github/                         # ═══ GitHub provider adapter ═══ (NEW)
│   └── copilot-instructions.md      # GitHub Copilot repo-level instructions
│
├── agents/                          # ═══ Runtime role briefs (workflow engine input) ═══
│   └── roles/                       # Simplified role briefs consumed by runtime engine
│       ├── corpus-librarian.md      # Kept for backward compat; canonical in .agents/agents/
│       ├── day-trading-strategist.md
│       ├── execution-realist.md
│       ├── extraction-reviewer.md
│       ├── lead-orchestrator.md
│       ├── quant-critic.md
│       ├── review-synthesizer.md
│       ├── risk-critic.md
│       └── scalping-strategist.md
│
├── workflows/                       # Workflow definitions (provider-neutral JSON — keep)
│   ├── strategy_discovery_router_v1.json
│   ├── day_trading_discovery_v1.json
│   ├── scalping_discovery_v1.json
│   └── candidate_review_v1.json
│
├── prompts/                         # Prompt templates (provider-neutral .txt — keep)
│   ├── critic_system.txt / critic_user.txt
│   ├── day_trading_system.txt / day_trading_user.txt
│   ├── reframe_system.txt / reframe_user.txt
│   ├── review_system.txt / review_user.txt
│   └── scalping_system.txt / scalping_user.txt
│
├── automations/                     # Automation specs and prompts (keep — paused)
│   ├── prompts/
│   └── specs/
│
├── config/                          # TOML policy and config files (keep)
│   ├── default.toml                 # Updated: no hardcoded paths
│   ├── autonomy_policy.toml
│   ├── codex_capabilities.toml
│   ├── codex_operator_policy.toml
│   ├── data_contract.toml
│   ├── eval_gates.toml
│   ├── mt5_env.toml
│   ├── openai-live.toml
│   ├── portfolio_policy.toml
│   ├── program_policy.toml
│   └── risk_policy.toml
│
├── src/                             # ═══ Source code ═══
│   ├── agentic_forex/               # Deterministic kernel (keep — per AGENTS.md)
│   │   └── (24 subpackages unchanged)
│   └── goblin/                      # Bridge namespace (keep)
│       └── (aliasing bridge unchanged)
│
├── tests/                           # Test suite (keep)
│
├── Goblin/                          # Goblin control plane (keep — all subdirs)
│   ├── STATUS.md, MATURITY.md, EVOLUTION.md, etc.
│   ├── checkpoints/, contracts/, decisions/, phases/
│   ├── reports/, runbooks/, state/, templates/
│   └── (unchanged)
│
├── docs/                            # ═══ Architecture & operations documentation ═══ (NEW)
│   ├── audit/
│   │   ├── repo-inventory.md        # Phase 0 output
│   │   ├── component-registry.csv   # Phase 0 output
│   │   └── current-vs-target-gap-analysis.md  # Phase 3 output
│   ├── architecture/
│   │   ├── target-folder-structure.md  # This file (Phase 2)
│   │   ├── provider-comparison.md      # Phase 1 output
│   │   └── component-contracts.md      # Phase 2 output
│   ├── migration/
│   │   └── rename-and-rewire-plan.md   # Phase 4 output
│   ├── operations/
│   │   ├── incident-runbook.md         # Phase 5 output
│   │   └── rollback-and-resume.md      # Phase 5 output
│   └── governance/
│       ├── decision-log.md             # Phase 5 output
│       └── risk-register.md            # Phase 5 output
│
├── reports/                         # Runtime reports (gitignored — keep)
│   ├── AF-CAND-*/ (600+ candidate dirs)
│   └── industry-update/             # Phase 6 output
│       ├── latest.md
│       └── latest.html
│
├── knowledge/                       # Knowledge base (keep)
├── data/                            # Research data (keep — gitignored)
├── experiments/                     # Experiment artifacts (keep — gitignored)
├── approvals/                       # Approval records (keep)
├── published/                       # Published snapshots (keep — empty)
└── traces/                          # Execution traces (keep — gitignored)

# REMOVED:
# skills/                            # Legacy 3-file dir → archived into .agents/agents/
# .codex/skills-src/                 # Exact duplicate of .agents/skills/ → deleted
```

---

## Key Decisions

### 1. Canonical Component Home

| Component Type | Canonical Location | Format |
|---------------|-------------------|--------|
| Agent definitions | `.agents/agents/*.md` | Markdown + YAML frontmatter (provider-neutral contract) |
| Skill definitions | `.agents/skills/*/SKILL.md` | Markdown + YAML frontmatter |
| Hook contracts | `.agents/hooks/` | Markdown (contract) + provider implementations in `.claude/hooks/`, etc. |
| Workflows | `workflows/*.json` | JSON node-based definitions |
| Prompts | `prompts/*.txt` | Plain text system/user pairs |
| Automations | `automations/` | Markdown prompts + TOML specs |
| Role briefs (runtime) | `agents/roles/*.md` | Simplified Markdown for workflow engine |
| MCP config | `.vscode/mcp.json` | JSON (MCP standard) |
| Component registry | `.agents/registry.json` | JSON (machine-readable index) |
| Config/policy | `config/*.toml` | TOML |

### 2. Provider Adapter Pattern

Each provider directory contains ONLY:
- Provider-specific configuration formats (e.g., Codex TOML agent configs)
- Provider-specific wiring (e.g., Claude hooks in PowerShell)
- References back to canonical definitions in `.agents/`

No business logic or canonical definitions live in provider directories.

### 3. What Gets Removed

| Item | Current Location | Action |
|------|-----------------|--------|
| `.codex/skills-src/` (8 dirs) | `.codex/skills-src/` | Delete — exact duplicates of `.agents/skills/` |
| `skills/` (3 files) | `skills/` | Archive content into `.agents/agents/` contracts; delete directory |

### 4. What Gets Created

| Item | Location | Purpose |
|------|----------|---------|
| `.agents/agents/` (17 files) | `.agents/agents/` | Canonical agent definitions with full contracts |
| `.agents/hooks/README.md` | `.agents/hooks/` | Hook contract schema |
| `.agents/registry.json` | `.agents/` | Machine-readable component index |
| `.vscode/mcp.json` | `.vscode/` | MCP server configuration |
| `.github/copilot-instructions.md` | `.github/` | Copilot repo instructions |
| `GOBLIN.md` | Root | Canonical system document |
| `docs/` tree | `docs/` | Architecture, migration, operations documentation |

---

## Rollback

Design-only phase — no files modified. Rollback is not applicable.
