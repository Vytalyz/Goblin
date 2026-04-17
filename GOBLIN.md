# GOBLIN

**Goblin** is a governed algorithmic forex research platform. It discovers, evaluates, and monitors trading strategy candidates through a deterministic kernel with AI-operator orchestration on top.

---

## Identity

| Attribute | Value |
|-----------|-------|
| Project name | `goblin` (pyproject.toml) |
| Kernel namespace | `src/agentic_forex/` (deterministic — preserved until explicit migration) |
| Bridge namespace | `src/goblin/` (sys.modules aliasing → `agentic_forex`) |
| CLI entry points | `goblin`, `agentic-forex` (both → same `main()`) |
| Research data source | OANDA (canonical) |
| Practice/parity platform | MT5 (never research truth) |
| Live trading | Forbidden by policy |

---

## Architecture

### Layers

```
┌──────────────────────────────────────────┐
│  AI Operator Layer (outer)               │
│  Claude Code · OpenAI Codex · Copilot    │
│  ─ orchestration only, no runtime dep ─  │
├──────────────────────────────────────────┤
│  Goblin Control Plane                    │
│  Goblin/ (status, phases, incidents,     │
│  deployment bundles, runbooks)           │
├──────────────────────────────────────────┤
│  Agentic Components (.agents/)           │
│  agents · skills · hooks · workflows ·   │
│  prompts · MCP · registry                │
├──────────────────────────────────────────┤
│  Deterministic Kernel (src/)             │
│  config · market_data · backtesting ·    │
│  experiments · governance · forward ·    │
│  approval · operator · runtime           │
└──────────────────────────────────────────┘
```

### Design Principles

1. **Python/TOML control plane is authoritative** — AI operators advise, kernel decides
2. **One canonical home per component** — no duplication without documented reason
3. **Provider-neutral core** — canonical definitions in `.agents/`; provider adapters in dotfiles
4. **MCP as universal tool interface** — supported by all major providers
5. **No runtime AI dependency** — everything works without an API key
6. **Governed by provenance** — no stage bypasses approvals, parity, or trial ledgers

---

## Key Directories

| Directory | Purpose |
|-----------|---------|
| `.agents/` | Canonical agentic component definitions (agents, skills, hooks, registry) |
| `.claude/`, `.codex/`, `.vscode/`, `.github/` | Provider-specific adapters |
| `src/agentic_forex/` | Deterministic kernel (24 subpackages, ~60 CLI commands) |
| `src/goblin/` | Bridge namespace (aliasing layer) |
| `Goblin/` | Program control plane (status, phases, incidents, runbooks, contracts) |
| `config/` | TOML policy and runtime configuration |
| `workflows/` | JSON workflow definitions (node-based) |
| `prompts/` | Prompt templates (system/user.txt pairs) |
| `agents/roles/` | Runtime role briefs (consumed by workflow engine) |
| `docs/` | Architecture, migration, operations, and governance documentation |
| `reports/` | Generated candidate reports and industry updates |

---

## Governance Rules

See [AGENTS.md](AGENTS.md) for the complete repository governance policy. Key constraints:

- `AF-CAND-0263` is locked as the overlap benchmark — mutation is forbidden
- `gap_blank_slate` slot must not borrow from `AF-CAND-0263`
- No candidate rescue through the gap lane
- MT5 evidence explains failures but cannot establish promotion truth
- One phase at a time; acceptance evidence required before advancing

---

## Active Portfolio Slots

| Slot | Status | Constraint |
|------|--------|-----------|
| `overlap_benchmark` | AF-CAND-0263 locked | Immutable benchmark reference |
| `gap_blank_slate` | Open | Fresh strategy families only |

---

## Architecture Documentation

Phase outputs from the Goblin architecture overhaul:

| Phase | Deliverable | Path |
|-------|------------|------|
| 0 — Audit | Repository inventory | [docs/audit/repo-inventory.md](docs/audit/repo-inventory.md) |
| 0 — Audit | Component registry (CSV) | [docs/audit/component-registry.csv](docs/audit/component-registry.csv) |
| 1 — Research | Provider comparison matrix | [docs/architecture/provider-comparison.md](docs/architecture/provider-comparison.md) |
| 2 — Target | Target folder structure | [docs/architecture/target-folder-structure.md](docs/architecture/target-folder-structure.md) |
| 2 — Target | Component contracts | [docs/architecture/component-contracts.md](docs/architecture/component-contracts.md) |
| 3 — Gap | Current-vs-target gap analysis | [docs/audit/current-vs-target-gap-analysis.md](docs/audit/current-vs-target-gap-analysis.md) |
| 4 — Migration | Rename & rewire plan | [docs/migration/rename-and-rewire-plan.md](docs/migration/rename-and-rewire-plan.md) |
| 5 — Operations | Incident runbook | [docs/operations/incident-runbook.md](docs/operations/incident-runbook.md) |
| 5 — Operations | Rollback & resume | [docs/operations/rollback-and-resume.md](docs/operations/rollback-and-resume.md) |
| 5 — Governance | Decision log | [docs/governance/decision-log.md](docs/governance/decision-log.md) |
| 5 — Governance | Risk register | [docs/governance/risk-register.md](docs/governance/risk-register.md) |
| 6 — Industry | Industry update skill | [.agents/skills/industry-monitoring/SKILL.md](.agents/skills/industry-monitoring/SKILL.md) |
| 6 — Industry | Report module | [src/agentic_forex/industry/report.py](src/agentic_forex/industry/report.py) |
| 6 — Industry | Tests | [tests/test_industry_report.py](tests/test_industry_report.py) |

---

## Quick Start

```powershell
# Install in development mode
pip install -e .

# Run the CLI
goblin --help

# Generate an industry update report
goblin industry-report

# Export operator state
goblin export-operator-state

# Validate operator contracts
goblin validate-operator-contract --strict
```

---

## Related Documents

- [AGENTS.md](AGENTS.md) — Repository governance rules
- [codex.md](codex.md) — Codex operator playbook
- [Goblin/STATUS.md](Goblin/STATUS.md) — Program phase status
- [Goblin/MATURITY.md](Goblin/MATURITY.md) — Maturity assessment
- [Goblin/EVOLUTION.md](Goblin/EVOLUTION.md) — Evolution history
- [Goblin/TAKEOVER_PLAN.md](Goblin/TAKEOVER_PLAN.md) — Takeover migration plan
