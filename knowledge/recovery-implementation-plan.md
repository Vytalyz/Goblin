# Agentic Forex Recovery And Completion Plan

## Current State Snapshot

- Source-of-truth project path: `.`
- The root-level `Agentic Forex` project already exists with package scaffolding, workflows, prompts, CLI, runtime, corpus ingestion, market-data pipeline, approval flow, MT5 practice packet flow, and tests.
- Last known validation state: `23 passed` on March 21, 2026.
- The empty folder at `<USER_HOME>/OneDrive\Documents\Playground\Investment Strategy\Agentic Forex` is not the implementation target and must not be treated as the source of truth.

## Core Non-Negotiables

- Keep the project standalone and rooted at `.`.
- Do not import or reuse `Forex`, `FX Lab`, `investment_copilot`, Agent Builder, ChatKit, or visual workflow tooling.
- Keep discovery fresh-lens and isolated from sibling-project priors.
- Keep all market data, traces, reports, published snapshots, approvals, and MT5 artifacts local to this project.
- Keep `OANDA` as the canonical research data source.
- Keep historical OANDA backfill and QA reporting in the canonical research path.
- Keep a deterministic scalping benchmark lane that compares multiple variant families on the same canonical dataset before promotion.
- Keep the scalping exploration lane deterministic by default so new candidate generation remains usable without live API spend.
- Keep target-iteration work objective-driven, with explicit trade-count, stress, and OOS guardrails rather than open-ended tuning.
- Keep FTMO fit scoring as a soft policy layer, not a publish gate.
- Keep economic-calendar blackout windows separate from canonical market data and apply them only through policy-aware backtests.
- Keep account-size, position-sizing, margin, and leverage assumptions explicit and versioned in strategy specs.
- Keep data provenance, environment snapshots, execution-cost models, and risk envelopes mandatory for every promoted experiment stage.
- Keep a structured trial ledger and failure taxonomy under local project artifacts and observational knowledge.
- Keep safer autonomy under a single-step controller contract that opens bounded child campaigns, executes one legal step, persists recommendations, and stops.
- Keep the readiness ladder evidence-bound and provisional until CSCV/PBO exists.
- Keep the experiment comparison layer file-backed under `experiments/`, with candidate/date-range ranking derived from existing artifacts and FTMO fit included as a non-blocking score.
- Keep pair-universe expansion deferred until `EUR/USD` research is stable.
- Keep `MT5` as a downstream parity-validation lane only; never treat MT5 history as research or training input.
- Keep OANDA shadow-forward as the default forward gate after parity.
- Keep MT5 batch runs deterministic through generated tester configs, run specs, and no-live-trading defaults.
- Keep deterministic rule logic as the executable signal lane and keep ML in shadow mode unless a later approved process promotes it.
- Keep live LLM providers optional in phase 1; use `Codex` as the builder/operator and require measured payoff before any provider becomes part of the default workflow.
- Enforce human approval before MT5 packet generation and MT5 practice validation.
- Enforce human-review approval before publishing a research snapshot.
- Keep OANDA MetaTrader 5 practice-only.
- Preserve explicit costs, no leakage, no lookahead, and reproducible artifacts as baseline research governance.

## Detailed Recovery And Completion Plan

### Project Boundary And Scaffolding

- Maintain a standalone Python project rooted at `Playground\Agentic Forex` with its own `pyproject.toml`, `README.md`, `.gitignore`, `config/`, `workflows/`, `prompts/`, `agents/roles/`, `skills/`, `knowledge/`, `data/`, `traces/`, `reports/`, `published/`, `approvals/`, `experiments/`, `tests/`, and `src/agentic_forex/`.
- Keep package name `agentic_forex` and console entrypoint `agentic-forex`.
- Resolve all project paths from the root with `pathlib`; do not rely on current working directory.
- Keep the project fully isolated from sibling projects by implementation and by tests.

### Configuration And Governance

- Maintain a single settings loader with defaults for:
  - LLM provider, model, temperature, and API environment variable.
  - Market-data instrument and granularity.
  - Validation thresholds for minimum trades, out-of-sample profit factor, expectancy, drawdown review, and stress spread multiplier.
  - Default discovery and review workflow IDs.
- Maintain explicit TOML overlays for:
  - `config/data_contract.toml`
  - `config/eval_gates.toml`
  - `config/risk_policy.toml`
  - `config/mt5_env.toml`
- Keep governance local to `Agentic Forex`:
  - no lookahead
  - no leakage
  - explicit execution-cost assumptions
  - reproducible artifacts
  - practice-only execution
  - human approval before MT5 packet generation and MT5 validation
- Keep short governance docs in `knowledge/` and use this document as the detailed recovery baseline.

### Workflow Runtime

- Maintain a code-first workflow engine with typed schemas and four node types:
  - `agent`
  - `tool`
  - `router`
  - `finalize`
- Validate the workflow input schema before execution.
- Validate each node input before the node runs.
- Validate each node output before edge routing or finalization.
- Persist a full per-node trace for every run containing:
  - workflow id and version
  - trace id
  - node id, name, and type
  - validated input payload
  - output payload
  - route target
  - citations
  - timing
  - error
- Persist both `trace.json` and `trace.md`.
- Require router output to select the next node explicitly and validate the chosen edge contract.

### LLM Layer

- Keep a project-specific LLM abstraction with:
  - `BaseLLMClient`
  - `MockLLMClient`
  - `OpenAIClient`
- Keep `mock` as the default provider so the project remains runnable and testable without secrets.
- Treat live provider usage as optional rather than assumed; phase-1 research value must come primarily from deterministic workflows and local artifacts.
- Keep the mock client deterministic for:
  - reframed discovery requests
  - candidate drafts for `scalping` and `day_trading`
  - review packets
- Keep the OpenAI client behind the same structured-output interface and require `OPENAI_API_KEY`.
- Use `Codex` as the development and research copilot, not as a hidden runtime dependency for unattended workflows.
- Do not allow provider-specific logic to leak into workflows or tools.

### Discovery Workflows And Prompts

- Maintain workflow manifests under `workflows/` for:
  - `strategy_discovery_router_v1`
  - `scalping_discovery_v1`
  - `day_trading_discovery_v1`
  - `candidate_review_v1`
- Discovery flow must:
  - accept a research question and external mirror path
  - reframe the question
  - collect corpus context
  - route to `scalping` or `day_trading`
  - synthesize a candidate draft
  - finalize and persist the candidate
- Review flow must:
  - accept a compiled strategy spec
  - prepare quantitative context
  - synthesize a review packet
  - finalize and persist the review output
- Keep prompts externalized for reframe, scalping, day trading, and review.

### Corpus Catalog And Ingestion

- Support an external local `gnidart` mirror path and do not vendor the corpus into this project.
- Catalog supported sources into a local JSON manifest.
- Parse metadata from:
  - `_info.json`
  - `_info.text`
  - `Trading.txt`
- Extract normalized text from:
  - `.txt`
  - `.pdf`
  - `.epub`
- Store extracted text under `data/corpus/extracted/`.
- Maintain a digest layer that returns:
  - relevant source citations
  - short highlights
  - explicit contradiction notes
- Restrict discovery-time reads to the project root and the explicitly allowed external corpus root.

### Market Data, Features, Labels, And Strategy Specs

- Maintain deterministic CSV ingestion for local `EUR/USD` bid/ask M1 data.
- Maintain paginated OANDA history backfill into the canonical local research store.
- Require CSV columns:
  - `timestamp_utc`
  - `bid_o`, `bid_h`, `bid_l`, `bid_c`
  - `ask_o`, `ask_h`, `ask_l`, `ask_c`
  - `volume`
- Normalize ingested data into:
  - Parquet under `data/normalized/`
  - DuckDB under `data/state/`
- Emit QA reports for the canonical research parquet covering duplicate timestamps, missing bars, spread anomalies, and session coverage.
- Maintain feature engineering for:
  - 1-bar and 5-bar returns
  - rolling mean and standard deviation
  - z-score
  - momentum
  - rolling volatility
  - hour
  - spread pips
- Maintain forward labels using `holding_bars`.
- Compile `CandidateDraft` into `StrategySpec` with:
  - candidate id
  - family
  - instrument
  - base granularity
  - entry style
  - holding bars
  - threshold
  - stop loss
  - take profit
  - spread multiplier
  - time split
  - source citations
  - notes

### Backtesting, Stress, ML, Review, Publish, Approval, MT5

- Backtesting must:
  - load normalized data
  - generate signals from `StrategySpec`
  - write a trade ledger
  - write a backtest summary with profit factor, win rate, expectancy, drawdown, out-of-sample profit factor, regime breakdown, and failure attribution
- Keep support for at least:
  - `mean_reversion_pullback`
  - `session_breakout`
- Stress testing must rerun with a stressed spread multiplier and persist separate artifacts rather than overwriting the base backtest.
- ML training must:
  - train at least `LogisticRegression` and `RandomForestClassifier`
  - write `model_metrics.json`
  - report `rule_only`, `ml_filter`, `ml_primary`, and `hybrid` lanes
- Review must grade candidate readiness against config thresholds and persist `review_packet.json`.
- Review must include staged robustness context, readiness status, required evidence, and FTMO fit without turning them into hard publish gates by default.
- Publish must create immutable snapshot folders under `published/<candidate_id>/vNNNN/` and write `manifest.json`.
- Publish must require a human-review approval record before snapshot creation.
- Approval must append human decisions to `approvals/approval_log.jsonl`.
- Experiment comparison must scan saved candidate artifacts, write `experiments/registry.csv`, and emit ranked comparison reports that include FTMO fit without turning it into a hard gate.
- Forward evaluation must run as OANDA shadow-forward and write `forward_stage_report.json` plus ledger artifacts.
- MT5 must:
  - generate a practice-only handoff packet with logic manifest, expected signals, and notes
  - generate deterministic tester configs, compile requests, launch requests, and run specs
  - validate MT5 practice audit CSVs against expected signals
  - persist a validation report

### CLI Surface

- Maintain these subcommands:
  - `catalog-corpus`
  - `ingest-market`
  - `qa-market`
  - `ingest-calendar`
  - `discover`
  - `explore-scalping`
  - `iterate-scalping-target`
  - `spec-candidate`
  - `backtest`
  - `train-models`
  - `stress-test`
  - `shadow-forward`
  - `review-candidate`
  - `benchmark-scalping`
  - `compare-experiments`
  - `run-campaign`
  - `publish-candidate`
  - `approve`
  - `setup-oanda-credential`
  - `generate-mt5-packet`
  - `validate-mt5-practice`
- Keep `--project-root` and `--config` valid both before and after the subcommand.
- Ensure `discover` auto-catalogs the corpus when the local catalog is missing.
- Keep CLI outputs JSON so runs are scriptable and inspectable.

## Public Interfaces And Artifacts

### Typed Models

- `DiscoveryRequest`
- `ReframedQuestion`
- `RouteDecision`
- `CandidateDraft`
- `StrategySpec`
- `ReviewContext`
- `ReviewPacket`
- `PublishManifest`
- `ApprovalRecord`
- `MT5Packet`
- `MT5ValidationReport`

### Expected Persisted Artifacts

- `data/corpus/catalog.json`
- `reports/<candidate_id>/candidate.json`
- `reports/<candidate_id>/strategy_spec.json`
- `reports/<candidate_id>/backtest_summary.json`
- `reports/<candidate_id>/stress_summary.json`
- `reports/<candidate_id>/model_metrics.json`
- `reports/<candidate_id>/review_packet.json`
- `reports/<candidate_id>/data_provenance.json`
- `reports/<candidate_id>/environment_snapshot.json`
- `reports/<candidate_id>/robustness_report.json`
- `reports/<candidate_id>/forward_stage_report.json`
- `experiments/registry.csv`
- `experiments/trial_ledger.jsonl`
- `experiments/campaigns/<campaign_id>/state.json`
- `experiments/comparison_<timestamp>.json`
- `traces/<trace_id>/trace.json`
- `traces/<trace_id>/trace.md`
- `published/<candidate_id>/vNNNN/manifest.json`
- `approvals/approval_log.jsonl`
- `approvals/mt5_packets/<candidate_id>/validation_report.json`

## Test And Acceptance Checklist

- Unit tests:
  - node input and output schema failures still write traces
  - corpus catalog parses `_info.json`, `_info.text`, and `Trading.txt`
  - project isolation blocks sibling reads
  - path handling works from a root containing spaces
- Integration tests:
  - full discovery workflow for `scalping`
  - full discovery workflow for `day_trading`
  - end-to-end market ingest -> spec compile -> backtest -> stress -> ML -> review -> publish -> approval -> MT5 validation
- CLI and boundary tests:
  - commands run from outside the project directory when `--project-root` is supplied
  - no `forex_research` imports
  - no `investment_copilot` imports
  - no discovery-time reads from sibling repos
- Acceptance checks:
  - `discover` produces a candidate and trace
  - `backtest` and `stress-test` produce separate artifacts
  - `compare-experiments` writes a ranked registry and comparison report
  - `publish-candidate` creates immutable snapshots
  - `validate-mt5-practice` writes a parity report
  - `pytest` passes

## Recovery Order If Interrupted Again

1. Restore root-level scaffolding and config.
2. Restore workflow runtime and schemas.
3. Restore corpus and market pipelines.
4. Restore CLI and prompts.
5. Restore tests and rerun validation.
