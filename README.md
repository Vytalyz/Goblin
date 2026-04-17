# Goblin

**Goblin** is a governed, agentic algorithmic forex research platform. It automates the full lifecycle of trading strategy discovery, backtesting, robustness evaluation, and broker-parity validation — while keeping humans in the loop for every decision that matters.

> **Research only.** Real-money automated trading is forbidden by repository governance. See [SECURITY.md](SECURITY.md) and [AGENTS.md](AGENTS.md).

## Highlights

- **End-to-end pipeline:** corpus ingestion → feature engineering → strategy discovery → backtesting → walk-forward validation → MT5 parity testing → staged promotion
- **Governed autonomy:** every promotion step is approval-gated; a single-step controller runs bounded iterations and stops at policy boundaries
- **Agentic architecture:** 15+ specialist agents (strategist, critic, observer, guardian) orchestrate research through deterministic workflows
- **Multi-source data:** OANDA (canonical research), MetaTrader 5 (practice parity), with built-in QA for duplicates, gaps, and spread anomalies
- **Execution realism:** fill delay, commission modelling, regime-quality filters, and family-level CSCV/PBO robustness checks
- **Publish-safe:** automated pre-push validation (secrets, paths, binaries, terminal hashes) with a guardian agent and CI gate

## Project Structure

| Path | Purpose |
|------|---------|
| `src/agentic_forex/` | Deterministic Python kernel (all business logic) |
| `src/goblin/` | Bridge namespace (`sys.modules` alias to `agentic_forex`) |
| `.agents/` | Agentic component definitions (agents, skills, hooks) |
| `config/` | TOML policy files (risk, eval gates, MT5, portfolio) |
| `workflows/` | JSON node-based workflow definitions |
| `experiments/` | Research artifacts, trial ledgers, campaign state |
| `approvals/` | MT5 packets, run configs, and governance records |
| `Goblin/` | Program control plane (status, phases, incidents) |
| `scripts/` | Utility scripts (sanitizer, validator, etc.) |

## Requirements

- Python 3.13+
- Windows (for MT5 integration; core research runs on any OS)
- OANDA practice account (for live data fetching)

## Secrets

- Goblin resolves secrets from environment variables first, then from Windows Credential Manager.
- Default OpenAI target: `openai-api-key`
- Preferred OANDA target: `agentic-forex/oanda/practice`
- Legacy OANDA fallback targets: `forex-research/oanda/practice`, `api-token@forex-research/oanda/practice`
- Environment overrides remain available through `OPENAI_API_KEY` and `OANDA_API_TOKEN`.
- Secure interactive OANDA setup with no token echo:

```powershell
goblin setup-oanda-credential --project-root .
```

## Install

```powershell
pip install -e ".[dev]"
```

## Local Configuration

The repo ships with sane defaults in `config/default.toml` and domain-specific
files (`config/mt5_env.toml`, etc.).  For machine-specific overrides:

1. **Copy the example files:**

   ```powershell
   cp .env.example .env
   cp config/local.toml.example config/local.toml
   ```

2. **Edit `.env`** with your API credentials (or use Windows Credential
   Manager — see *Secrets* below):

   ```ini
   OANDA_API_TOKEN=your-practice-token
   OPENAI_API_KEY=sk-...
   MT5_TERMINAL_PATH=C:\Program Files\OANDA MetaTrader 5 Terminal\terminal64.exe
   ```

3. **Edit `config/local.toml`** for MT5 or OANDA overrides:

   ```toml
   [mt5_env]
   terminal_paths = ["C:\\Program Files\\OANDA MetaTrader 5 Terminal\\terminal64.exe"]
   ```

Both `.env` and `config/local.toml` are **gitignored** and will never be pushed.

**Config load order** (later wins):
`config/default.toml` → domain TOML files → `config/local.toml` → explicit
`--config` flag → environment variables.

## Goblin Commands

```powershell
goblin goblin-init --project-root .
goblin goblin-status --project-root .
goblin goblin-phase-update --project-root . --phase-id GOBLIN-P00 --status completed
goblin goblin-checkpoint --project-root . --phase-id GOBLIN-P00 --summary "Initialized Goblin scaffolding"
goblin goblin-register-artifact --project-root . --channel research_backtest --candidate-id AF-CAND-0263 --run-id run-001 --artifact-origin backtest_summary --artifact-path reports/AF-CAND-0263/artifact.json --symbol EUR_USD --timezone-basis UTC
goblin goblin-build-truth-report --project-root . --candidate-id AF-CAND-0263
goblin goblin-open-incident --project-root . --candidate-id AF-CAND-0263 --title "Executable parity mismatch"
goblin goblin-build-deployment-bundle --project-root . --candidate-id AF-CAND-0263
```

## Core Commands

```powershell
goblin catalog-corpus --project-root . --mirror-path path/to/gnidart
goblin ingest-market --project-root . --input-csv path/to/eurusd_m1.csv
goblin ingest-market --project-root . --oanda-json path/to/oanda_candles.json
goblin ingest-market --project-root . --fetch-oanda --instrument EUR_USD --granularity M1 --count 5000
goblin ingest-market --project-root . --backfill-oanda --instrument EUR_USD --granularity M1 --start "2026-01-01T00:00:00Z" --end "2026-03-20T00:00:00Z" --chunk-size 5000
goblin qa-market --project-root . --instrument EUR_USD --granularity M1
goblin ingest-calendar --project-root . --input-csv path/to/economic_calendar.csv
goblin discover --project-root . --question "Build a scalping strategy for EUR/USD" --mirror-path path/to/gnidart
goblin explore-scalping --project-root . --mirror-path path/to/gnidart --count 4 --max-sources 5
goblin iterate-scalping-target --project-root . --baseline-id AF-CAND-0001 --target-id AF-CAND-0002
goblin spec-candidate --project-root . --candidate-json path/to/candidate.json
goblin backtest --project-root . --spec-json path/to/strategy_spec.json
goblin train-models --project-root . --spec-json path/to/strategy_spec.json
goblin stress-test --project-root . --spec-json path/to/strategy_spec.json
goblin shadow-forward --project-root . --spec-json path/to/strategy_spec.json
goblin review-candidate --project-root . --spec-json path/to/strategy_spec.json
goblin benchmark-scalping --project-root . --spec-json path/to/strategy_spec.json
goblin compare-experiments --project-root . --family scalping --limit 10
goblin run-campaign --project-root . --baseline-id AF-CAND-0001 --target-id AF-CAND-0014 --target-id AF-CAND-0015 --max-iterations 2 --trial-cap 12
goblin run-next-step --project-root . --allowed-step-type diagnose_existing_candidates
goblin run-next-step --project-root . --allowed-step-type mutate_one_candidate
goblin run-next-step --project-root . --allowed-step-type re_evaluate_one_candidate
goblin run-governed-loop --project-root . --family scalping --max-steps 6
goblin approve --project-root . --candidate-id AF-CAND-0001 --stage human_review --decision approve --approver josep --rationale "Approve research snapshot publication."
goblin publish-candidate --project-root . --candidate-id AF-CAND-0001
goblin approve --project-root . --candidate-id AF-CAND-0001 --stage mt5_packet --decision approve --approver josep --rationale "Generate MT5 practice packet."
goblin generate-mt5-packet --project-root . --candidate-id AF-CAND-0001
goblin approve --project-root . --candidate-id AF-CAND-0001 --stage mt5_validation --decision approve --approver josep --rationale "Run MT5 parity validation."
goblin validate-mt5-practice --project-root . --candidate-id AF-CAND-0001 --audit-csv path/to/mt5_audit.csv
```

`publish-candidate` requires an existing `review_packet.json` and an approved `human_review` record. `generate-mt5-packet` and `validate-mt5-practice` are approval-gated and stay practice-only.

`ingest-market --backfill-oanda` writes paginated raw manifests under `data/raw/oanda/backfill/`, updates the canonical research parquet, and emits a QA report under `reports/market_data_quality/`.

`benchmark-scalping` expands one base scalping spec into a deterministic comparison set including breakout, volatility-breakout, pullback-continuation, and failed-break-fade variants, then writes ranked results to the base candidate report directory.

`ingest-calendar` writes a normalized local economic calendar used only for news blackout windows and policy scoring. It never becomes canonical market data.

`explore-scalping` generates several deterministic, corpus-aligned scalping candidates, compiles and reviews them with the local mock review lane, then writes an experiment manifest plus a scoped comparison report for those new candidates.

`iterate-scalping-target` uses an existing baseline and a weaker session-breakout target to generate tuned breakout variants, score them against the iteration objective, and write both a targeted iteration report and a scoped comparison report.

`compare-experiments` scans current candidate report folders, writes `experiments/registry.csv`, emits a timestamped comparison report, and includes FTMO fit alongside empirical performance when ranking candidates or benchmark variants.

`shadow-forward` runs an OANDA shadow-forward pass, writes `forward_stage_report.json`, and appends the run to the structured trial ledger with forward gate outcomes.

`run-campaign` executes bounded narrow-lane iteration against explicit candidate targets, writes campaign state under `experiments/campaigns/`, and respects configured iteration and trial budgets.

`run-next-step` loads the latest completed campaign (or an explicitly supplied parent campaign), opens a bounded child campaign, executes exactly one supported next-step type, writes machine-readable next recommendations, and stops. Each step report now includes `continuation_status`, `stop_class`, `auto_continue_allowed`, and `recommended_follow_on_step` so higher-level automation can continue safely without bypassing governance.

`run-governed-loop` repeatedly calls `run-next-step` and stops automatically on the first real boundary:
- approval required
- lane exhausted
- integrity issue
- budget exhaustion
- ambiguity or policy boundary

It does not bypass approvals, relabel readiness, or continue past a family/hypothesis boundary.

Supplemental governance config overlays now live in:
- `config/data_contract.toml`
- `config/eval_gates.toml`
- `config/risk_policy.toml`
- `config/mt5_env.toml`

## Tests

```powershell
python -m pytest
```

## Pre-Push Validation

Before pushing, run the publish-guardian validation gate:

```powershell
python scripts/validate_for_publish.py --skip-tests
```

This checks for secrets, absolute paths, tracked binaries, MT5 terminal hashes, log files, config hygiene, and repository completeness. CRITICAL and HIGH findings block the push.

To sanitize artifact paths automatically:

```powershell
python scripts/sanitize_paths_for_publish.py
```

## Contributing

1. Fork the repository and create a feature branch
2. Run `python scripts/validate_for_publish.py` before submitting a PR
3. Ensure all tests pass with `python -m pytest`
4. Do not commit `.env`, `config/local.toml`, or any files under `data/state/`
5. Never modify the locked benchmark `AF-CAND-0263` unless you know what you are doing

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

[MIT](LICENSE)
