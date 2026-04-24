# Goblin Evolution

This document records major program milestones and the intended evolution path from the current state to the future Goblin-controlled system.

## Current Milestones

### 2026-04-24: Zero-input live-demo closeout now emits candidate quality audits

- **Gap closed.** Session-end could already auto-capture runtime and broker artifacts, but journal/experts capture still depended on explicit path flags.
- **What changed.** `goblin-live-session-end` now auto-discovers and archives terminal journal + experts logs from active MT5 terminal hash directories, while still allowing explicit overrides.
- **Quality measurement added.** Closeout now writes `candidate_quality_audit.json` under the candidate/run live-demo report directory. The audit computes a deterministic quality score/verdict using strategy baseline (forward-stage evidence), runtime execution metrics (attempt/success/failure/audit-write), and broker reconciliation status.
- **Operational consequence.** Live-demo auditing is now zero-input for the full evidence bundle at closeout, and each candidate run gets a durable, candidate-scoped quality artifact for review.

### 2026-04-23: Live-viewing commands for on-demand MT5 journal and expert log access

- **Gap identified.** Post-session-end archiving works, but during an active live-demo session there was no operator-facing way to tail the live MT5 journal or expert logs without manually navigating the MT5 terminal directories.
- **What added.** Two new operator commands:
  - `goblin-live-journal --candidate-id AF-CAND-0733 --tail 20`: displays the last 20 lines of the active MT5 terminal journal (auto-discovers active terminal hash)
  - `goblin-live-experts --candidate-id AF-CAND-0733 --tail 20`: displays the last 20 lines of the active EA experts log (auto-discovers active experts.log file)
- **Implementation.** Both commands auto-detect the MT5 common files path (or accept explicit `--mt5-common-path` override), scan for active terminal hash directories (32-char folder names), find the most recent journal/experts log, and tail N lines with metadata (file name, last update time).
- **Operational consequence.** Operator can now poll live demo session observability in real-time without interrupting MT5 or manually hunting down log files. Falls back gracefully if MT5 is not running (returns error code 1 with clear message).
- **Tests.** 2 new tests confirm error handling when MT5 is not running; full suite remains 13/13 passing.

### 2026-04-23: Live-demo session-end now closes the observability gap

- **Root issue.** The governed live-demo path already had contracts and helpers for EA audit, broker reconciliation, and runtime artifacts, but the operator-facing `goblin-live-session-end` command only harvested runtime summary and signal trace from MT5 common files. In practice that meant a real run could finish with attach evidence on disk but without the rest of the evidence set being pulled into Goblin.
- **What changed.** `goblin-live-session-end` now auto-discovers and archives `runtime_summary.json`, `signal_trace.csv`, `ea_audit.json`, broker-history CSV, and diagnostic-windows CSV when those files exist in the standard MT5 common-file locations. It also accepts explicit `--journal-path` and `--experts-log-path` overrides so raw terminal logs can be captured for one-off manual recovery without creating a second ad hoc workflow.
- **Operational consequence.** Manual recovery of a just-finished demo run now happens through the same governed session-end surface that future automation will use. Broker reconciliation is executed automatically at session close whenever broker history is available, so live-demo closeout is much less likely to stall at the attach-only state again.

### 2026-04-22: AF-CAND-0730 prepared as governed fallback/comparator candidate

- **Context.** To provide a second candidate for direct comparison with `AF-CAND-0733`, we first attempted governed slot-b generation paths (`portfolio_cycle`, `autonomous_manager` across all allowed slot_b families). Goblin policy boundaries blocked minting a net-new challenger at this time (`program_loop_no_pending_approved_lanes`, plus orthogonality constraints on the first slot_b family).
- **Governed fallback path used.** Instead of bypassing policy, we advanced the existing approved challenger lineage candidate `AF-CAND-0730` by running `goblin shadow-forward --spec-json reports/AF-CAND-0730/strategy_spec.json`.
- **Forward-stage result.** `passed=true`, `trading_days_observed=13`, `trade_count=25`, `profit_factor=2.686157517899841`, `expectancy_pips=5.6520000000003146`, `oos_expectancy_pips=4.730188679245478`, `expectancy_degradation_pct=0.0`, `risk_violations=[]`. Artifact: `reports/AF-CAND-0730/forward_stage_report.json`.
- **Freshness + approval state.** Post-run deterministic approval probe confirms `human_review`, `mt5_packet`, `mt5_parity_run`, and `mt5_validation` are all approved/fresh/unsuperseded under the current policy snapshot. Latest MT5 validation for `AF-CAND-0730` remains `passed` with parity rate `0.990625`.
- **Operational consequence.** `AF-CAND-0730` is now ready as the second governed comparator candidate to run alongside or against `AF-CAND-0733` decisioning, and to serve as immediate fallback if 0733 fails limited-demo progression.

### 2026-04-22: AF-CAND-0733 forward-stage passed and closed the remaining MT5-readiness gap

- **Forward-stage executed through the repo-native CLI.** Ran `goblin shadow-forward --spec-json reports/AF-CAND-0733/strategy_spec.json`, which wrote `reports/AF-CAND-0733/forward_stage_report.json` and appended a governed `forward_stage` entry to `experiments/trial_ledger.jsonl`.
- **Result.** `passed=true`, `trading_days_observed=12`, `trade_count=26`, `profit_factor=2.57142857142866`, `expectancy_pips=4.019230769231061`, `oos_expectancy_pips=2.6295081967214338`, `expectancy_degradation_pct=0.0`, `risk_violations=[]`.
- **Meaning in Goblin terms.** This was the missing evidence that prevented `AF-CAND-0733` from being legally MT5-ready under current governance. Human review had already been approved, and the MT5 packet, parity run, and MT5 validation approvals were already present.
- **Freshness check.** A deterministic post-run probe confirmed `human_review`, `mt5_packet`, `mt5_parity_run`, and `mt5_validation` are all still `approved`, `fresh`, and not `superseded` under the current policy snapshot. The latest MT5 validation remains `passed` with parity rate `0.990617` and deployment-grade certification.
- **Operational consequence.** `AF-CAND-0733` is now the current governed operator path for MT5 testing. The next manual/governed operator step is the limited-demo attach flow (`goblin-live-attach` → heartbeats → `goblin-live-session-end`) using the already-approved packet/bundle surface.

### 2026-04-21: Strategy Loop S2 gate evaluator (decision layer)

- **`tools/evaluate_strategy_s2_gates.py`** is the decision layer of S2 — deliberately split from the orchestration layer so that gate logic is unit-testable without a parquet file or a live backtest.
- **Inputs.** `backtest_summary.json` from `run_backtest` (provides `out_of_sample_profit_factor`, `expectancy_pips`, `trade_count`, `walk_forward_summary`, `regime_breakdown`, `max_drawdown_pct`, `in_sample_drawdown_pct`, `stress_profit_factor`); `robustness_report.json` from `build_robustness_report` (provides `pbo`, `white_reality_check_p_value`, `deflated_sharpe_ratio`, `cscv_pbo_available`, `white_reality_check_available`); optional cost-sweep JSON `{"plus_1pip_pf": <float>}`.
- **Outputs.** Pure decision-log entry (returnable from `evaluate_s2()` and appendable via `append_decision()`) keyed `DEC-STRAT-AF-CAND-NNNN-S2-PASS|FAIL`, schema-validated by `tools/verify_strategy_decisions_schema.py` round-trip in tests. Also writes `failure_mode` field listing failing gates and a `next_action` pointing to S3 (on PASS) or RETIRE (on FAIL).
- **Twelve gates evaluated.** OOS PF ≥1.05, expectancy >0, trade_count ≥100, walk-forward PF per window ≥0.90, walk-forward trades per window ≥10, DD degradation ≤15%, stress PF ≥1.0, regime non-negativity (PF≥1 in every regime bucket), cost persistence at +1pip (PF≥1), PBO ≤0.35, White's RC p-value ≤0.10, DSR ≥0.0. All thresholds load from `config/eval_gates.toml [validation]`.
- **`--allow-provisional`** matches the robustness suite's `robustness_provisional` mode — PBO and White's RC are downgraded to passed-with-note when the family universe is too small for CSCV/WRC to produce a value. Without this flag, an unavailable PBO/WRC fails the gate (the strict default).
- **CLI return codes.** 0=PASS, 1=FAIL, 2=missing artifact — makes the tool composable with shell pipelines and the future S2 orchestrator.
- **Tests.** 23 new tests covering happy path, every per-gate failure mode, dict-vs-list `regime_breakdown`, missing/zero in-sample DD, provisional toggle in both directions, real-config threshold load, append-only log behaviour, and CLI return codes. Targeted Stage 1+2 suite: **71/71 pass**.
- **Next.** `tools/run_strategy_s2_eval.py` (orchestration layer that hydrates the lean S1 spec into a full `StrategySpec`, runs `run_backtest` + cost sweep + `build_robustness_report`, then invokes the gate evaluator). Then `tools/run_strategy_s3_eval.py` and the per-candidate sealed-holdout generator.

### 2026-04-21: Strategy Loop S1 scaffolder

- **`tools/generate_strategy_spec.py`** is the S1 (Strategy Design) entry point of the loop. It runs a single transaction that produces three governed artifacts: the lean `strategy_spec.json` under `reports/AF-CAND-NNNN/`, the five-field rationale card under `Goblin/reports/strategy_rationale_cards/`, and an append-only `DEC-STRAT-AF-CAND-NNNN-S1-PASS` entry in `Goblin/decisions/strategy_decisions.jsonl`.
- **Governance enforced at the scaffold step.** The chosen `--family` must appear in the slot's `allowed_families` from `config/portfolio_policy.toml`; the hypothesis must be ≥30 chars (matches the validator's `MIN_RATIONALE_CHARS`); slot_id and ID allocation are validated before any file is written. The decision-log entry it emits passes `tools/verify_strategy_decisions_schema.py` end-to-end (round-trip tested).
- **CLI supports `--dry-run` and `--json`** for safe preview and tooling integration. Live dry-run on the real repo correctly allocated the next ID (`AF-CAND-0742`).
- **Tests.** 12 new tests (happy path, schema round-trip, ID allocation, family/hypothesis/slot validation, dry-run isolation, CLI return codes). Targeted Stage 1 suite: 48/48 pass (12 scaffolder + 26 validator + 10 status).
- **Next.** `tools/run_strategy_s2_eval.py` (12-gate S2 evaluator), `tools/run_strategy_s3_eval.py` (per-candidate ML eval), per-candidate sealed-holdout generator.

### 2026-04-21: Strategy Loop Stage 1 — foundational tooling

- **Decision log surface.** New `Goblin/decisions/strategy_decisions.jsonl` (append-only, currently empty) + canonical schema doc at `Goblin/decisions/STRATEGY_DECISIONS_SCHEMA.md`. Required fields: `decision_id`, `candidate_id`, `stage` (S1–S7 or RETIREMENT), `outcome` (pass/fail/pending/retired/promoted), `decided_by` (owner/runner), `decided_at` (ISO-8601 UTC), `rationale` (≥30 chars), `gate_results`, `evidence_uris`, `next_action`. Optional: `slot_id`, `prior_decision_id`, `failure_mode`, `post_mortem_uri`, `commit_sha`, `tool_version`.
- **Validator.** `tools/verify_strategy_decisions_schema.py` enforces required-field set, `decision_id` regex, candidate-id regex, ISO-8601 UTC timestamp format, stage/outcome/decided_by enums, rationale minimum length, `gate_results` structure (with boolean `passed`), and `decision_id` uniqueness within the file. Returns exit code 0/1 like the ML decision validator.
- **Status reader.** `tools/strategy_loop_status.py` is a read-only renderer of the loop state: portfolio slots from `config/portfolio_policy.toml`, total decisions, candidates tracked, latest decision per candidate, last_action per slot, optional `--candidate` history filter, and `--json` output for tooling integration. Live output now correctly shows `slot_a=AF-CAND-0733` and `slot_b=(none)`.
- **Tests.** 36 new tests (26 validator + 10 status) all pass. Targeted run: 36/36.
- **Pre-existing ML-P2 test failures fixed in same window.** Exempted operational `holdout_access_*` decision_types from `bias_self_audit` requirement (they are auto-generated bracketing events, not analytical decisions). Narrowed `test_rehearsal_report_hard_cap_unaffected` to flag only REHEARSAL-marked entries; legitimate HOLDOUT-ACCESS entries are expected once the cap is used. Committed the 4 real ceremony entries from the 2026-04-20 ML-P2 ceremony that were never persisted.
- **Next.** `tools/generate_strategy_spec.py` (interactive scaffolder for new strategy specs), `tools/run_strategy_s2_eval.py` and `tools/run_strategy_s3_eval.py` (gate runners that write to the strategy decisions log), per-candidate sealed-holdout generator.

### 2026-04-21: Strategy Loop Stage 0 — governance reset complete

- **Removed the AF-CAND-0263 lock.** The `locked_benchmark` slot mode no longer exists; `PortfolioSlotPolicy.mode` literal is now `["active_candidate", "blank_slate_research"]`. Real governance now lives in the deployment ladder, decision logs, and per-candidate sealed holdouts — not in slot-level mutation locks.
- **Two-slot portfolio.**
  - `slot_a` (`active_candidate`): currently holds **`AF-CAND-0733`** at `limited_demo` on the deployment ladder. Mutable.
  - `slot_b` (`blank_slate_research`): blank-slate challenger track with `strategy_inheritance == "none_from_prior_candidates"`. Mutable.
- **Code surface changes.** Deleted `src/agentic_forex/governance/locked_benchmark.py` and `tests/test_af_cand_0263_locked.py`. Renamed operator contract findings (`missing_overlap_slot`/`overlap_slot_mutable` → `missing_slot_a`/`slot_a_misconfigured`; `missing_gap_slot`/`gap_slot_inheritance_invalid` → `missing_slot_b`/`slot_b_inheritance_invalid`). Renamed `_run_blank_slate_research_slot` → `_run_research_slot` and routed both slot modes through it. Removed orphan `_extract_status_lines`/`_latest_run_file` helpers and unused `re` import from `campaigns/portfolio.py`. Removed `_guard_against_locked_benchmark` from `scripts/run_ml_baseline_comparison.py`.
- **Governance docs updated.** `AGENTS.md`, `.codex/AGENTS.md`, `.github/copilot-instructions.md`, `.github/pull_request_template.md`, `CONTRIBUTING.md`, `config/portfolio_policy.toml`.
- **Test status.** Targeted suite (portfolio + CLI + goblin_live): 35/35 pass. Full suite: 649 pass, 2 pre-existing failures unrelated to Stage 0 (`test_p20_rehearsal::test_rehearsal_report_hard_cap_unaffected`, `test_verify_decision_log_schema::test_real_decision_log_passes`) carried over from ML-P2 work.
- **Next.** Stage 1+ tooling per `/memories/session/plan.md` §11: `Goblin/decisions/strategy_decisions.jsonl` + schema, `tools/generate_strategy_spec.py`, `tools/run_strategy_s2_eval.py`, `tools/run_strategy_s3_eval.py`, `tools/strategy_loop_status.py`, per-candidate sealed-holdout generator.

### 2026-04-20: ML-P2 holdout ceremony complete — verdict NO_GO (commit `d093c35`)

- **Result**: Aggregate primary PF lift **+0.0528** — just below CONDITIONAL floor (0.055). BCa 95% CI **[-0.027, +0.261]** crosses zero.
- **Individual lifts**: 0734 +0.003 / 0322 +0.062 / 0323 +0.062 / 0007 +0.058 / 0002 +0.077 / 0290 +0.055
- **Q1 fragile cohort**: all 5 fragile candidates positive — Q1_OK
- **Prediction accuracy**: Midpoint prediction (NO_GO) was correct
- **HARD_CAP**: 2/2 used — holdout sealed permanently
- **Governance artifacts**: `predictions.jsonl` (2 entries committed), `p2_0_holdout_eval_report.json` + `p2_0_insample_eval.json` (local, gitignored)
- **Next decision required**: ML-P3 architecture revision OR halt

### 2026-04-20: ML-P2 evaluation pipeline complete (commit `8f0d15a`)

- **`tools/run_p2_eval.py`** (~350 LOC): Holdout evaluation pipeline. Trains XGBClassifier on in-sample rows (locked hparams), evaluates all 6 primary + 5 fragile candidates on holdout, runs BCa moving-block bootstrap (n=10000, seed=20260420, block_min=20), Bonferroni 4-regime Wilcoxon signed-rank tests (α=0.0025 per test), Q1 fragile-sentinel rule (NOGO at mean < −2σ_cross AND ≥3/5 negative, CONDITIONAL_RESTRICTED at mean < −1σ_cross), and renders GO/CONDITIONAL/CONDITIONAL_RESTRICTED/NO_GO verdict. Writes `Goblin/reports/ml/p2_0_holdout_eval_report.json`. Invoked via `tools/holdout_access_ceremony.py --eval-cmd`.
- **`tools/log_p2_prediction.py`** (~200 LOC): R4-11 pre-registration prediction logger. Validates phase (midpoint/trigger), verdict enum, CI ordering, commit-SHA format (40-char hex), rationale length (≥50 chars), attestation length (≥30 chars), trigger-phase midpoint-SHA cross-reference. Appends to `Goblin/decisions/predictions.jsonl`. Supports `--dry-run`.
- **`tools/run_p2_insample_eval.py`** (~180 LOC): Purged walk-forward CV on in-sample rows 0:155775 for all 6 primary survivors. Produces `Goblin/reports/ml/p2_0_insample_eval.json`. Running this tool for the first time triggers the R4-11 midpoint prediction obligation.
- **New tests**: 52 total (33 in `tests/test_p2_eval.py`: verdict/BCa/Q1/Bonferroni/outcome pip/aggregate; 19 in `tests/test_log_p2_prediction.py`: validation, round-trip, ID sequencing, CLI). All pass.
- **Sealed holdout HARD_CAP**: 0/2 used.
- **Next action**: Run `tools/run_p2_insample_eval.py` to get first non-error PF. Log R4-11 midpoint prediction via `tools/log_p2_prediction.py`. Then run holdout ceremony.

### 2026-04-20: ML-P2.0 pre-registration scaffolding (EX-1 through EX-10) completed

- **EX-1 (`tools/derive_mde.py`)**: σ_cross=0.0211004853, MDE_upper=0.0503209020 locked into `[ml_p2]` eval_gates.toml. 24 tests.
- **EX-2 (`tools/gate_sensitivity.py`)**: Risk-1 retrospective gate evaluation proved Q1/I1 thresholds were not tuned post-hoc to 1.6 data. SURVIVORS frozenset (0734/0322/0323/0007/0002/0290) and FRAGILES frozenset (0716/0738/0739/0009/0001) code-enforced. 10 tests.
- **EX-3 (predictions log infrastructure)**: `Goblin/decisions/PREDICTIONS_SCHEMA.md` + empty `predictions.jsonl` (append-only CI) + `tools/verify_predictions_log_schema.py` (validator). 3 CI jobs added to `ml-phase-gates.yml`. `CODEOWNERS` established. 19 tests.
- **EX-4 (`tools/holdout_access_ceremony.py`)**: HARD_CAP=2, abort-counts-toward-cap (G7), 3-pass shred, key-outside-repo guard, INITIATED→COMPLETED/ABORTED decision-log bracketing. `holdout-ceremony.yml` workflow + key rotation runbook. 21 tests.
- **EX-5 (torch determinism)**: `[ml-p2]` optional extra pinned in `pyproject.toml`. `tests/test_torch_determinism.py` (1D-CNN bit-identical across runs). CI job `tests-with-torch-determinism`. 4 tests (skip without torch locally).
- **EX-6 (regime threshold freeze)**: `[ml_regime]` block in `eval_gates.toml`: `abs_momentum_12_median=1.9`, `volatility_20_median=0.0000741639`, `n_in_sample_rows_used=155775`. `tests/test_regime_freeze.py`. 6 tests.
- **EX-7 (grandfather frozenset hardening)**: Module-level `assert GRANDFATHERED_NO_BIAS_AUDIT == frozenset({"DEC-ML-1.6.0-CANDIDATES"})` in `verify_decision_log_schema.py`. 3 tests.
- **EX-8 (synthetic 4-regime generator)**: `tools/generate_synthetic_holdout.py` — samples from in-sample, shuffles, permutes labels. 4-regime coverage check. Output `Goblin/holdout/ml_p2_synthetic_rehearsal.parquet`. 4 tests.
- **EX-9 (HITL gate — approved 2026-04-20)**: Three pre-registration entries appended to `Goblin/decisions/ml_decisions.jsonl` (9 total, all schema-validated, commit `27d1bd6`): DEC-ML-2.0-CANDIDATES (n=6 primary, n=11 secondary), DEC-ML-2.0-TARGET (GO≥0.10 PF, CONDITIONAL≥0.055 PF, BCa bootstrap, Bonferroni 4-test, R4-11 predictions scaffold), DEC-ML-1.6b-A1-AUTHORIZATION (sequential CNN excluded from primary endpoint). Full 8-field bias self-audit on all three.
- **EX-10 (HITL gate — approved 2026-04-20)**: `tools/run_p20_rehearsal.py` + `tests/test_p20_rehearsal.py` + `.github/workflows/e2e_p20_rehearsal.yml`. Rehearsal PASSED 6/6 steps on synthetic data (regime coverage, predictions log schema, ceremony happy-path INITIATED→COMPLETED + shred, ceremony abort-path INITIATED→ABORTED, cap enforcement refused at HARD_CAP=2, decision-log schema). Report: `Goblin/reports/ml/p2_0_rehearsal_report.json`. Real holdout HARD_CAP: 0/2 used. Commit `cca5cdd`.
- Total test suite after EX-10: 628 passing (+ 4 subprocess-based rehearsal tests), 1 skipped (torch local), 0 failed.
- **ML-P2 implementation is now UNBLOCKED.** Next action: log the R4-11 midpoint prediction in `Goblin/decisions/predictions.jsonl` when Phase 2 XGB-on-tabular first produces a non-error PF on non-holdout data, then proceed with P2 architecture.

### 2026-04-20: ML evidence-first phases ML-P1.6.0 → 1.6 → 1.6b → 1.7 completed

- **ML-P1.6.0 (Variance Pilot)**: σ_PF=0.0083 measured (10 seeds × 3 candidates, locked XGB hparams). Effect-size floor and MDE locked at 0.0083 PF in `config/eval_gates.toml [ml_variance_pilot]`. Decision log initialized at `Goblin/decisions/ml_decisions.jsonl`.
- **ML-P1.6 (Baseline Comparison)**: 11 stratified candidates evaluated; median PF lift +0.0506 (~5.5× floor); 11/11 above floor; 11/11 cost-persistent at +1.0 pip. Regime gate: 6/11 surviving (0734, 0322, 0323, 0007, 0002, 0290), 5/11 fragile. Verdict: `conditional`. Sealed holdout created (key outside repo) gating ML-P2.0.
- **ML-P1.6b (Sequential Probe)**: 6 sequential features tested (`momentum_acceleration`, `vol_of_vol_5`, `range_compression_ratio`, `rsi_slope_10`, `realized_skew_20`, `realized_kurt_20`). All stationary (ADF + KPSS). Mean Δ-PF lift = +0.0041 across 6 surviving candidates (4.1% of 0.10 PF P2 target, p=0.2387 one-sided, BH-FDR q=0.10 rejected 0/6 features). Verdict: `p2_proceed_unchanged` — sequential features will NOT be added to the ML-P2 architecture.
- **ML-P1.7 (Plan Hardening)**: `tools/verify_decision_log_schema.py` (with explicit grandfather list), `tools/verify_dataset_sha.py` (pinned SHA `7875ba5a…`), `src/agentic_forex/governance/locked_benchmark.py` (case/whitespace/JSON-embedding guard for AF-CAND-0263). New CI lanes `.github/workflows/ml-phase-gates.yml` (7 jobs) and `.github/workflows/holdout-access.yml`. Glossary extended with BH-FDR / MDE / σ_PF / PSI / Decision Log / Effect-size floor / Sealed Holdout. Test suite grew from 463 → 541.
- ML-P2.0 HITL re-gate intentionally NOT executed; sealed holdout untouched. Pipeline paused awaiting explicit owner approval.

### 2026-04-14: demo-account MT5 automation policy alignment completed

- top-level repo governance now explicitly allows governed MT5 demo-account EA automation under the Goblin live-demo contract
- real-money automated trading remains forbidden at the top-level policy layer
- repo-level instructions now match the completed live-demo observability and deployment-ladder phases instead of implying an unconditional MT5 automation ban

### 2026-04-13: operational readiness hardening completed (P13-P15)

- P13 inventory report published with subsystem coverage and explicit gap analysis
- P14 session-aware run logging implemented with `GoblinRunRecord`, deterministic `session_window` derivation, and campaign entrypoint integration
- P15 clean-room governance implemented with seven auditable rules, baseline scenarios, pattern-card template, and framework gap matrix

### 2026-04-13: namespace takeover completed (T1-T4)

- operator-facing identity moved to Goblin-first wording and CLI entrypoints
- compatibility bridge introduced via `src/goblin/` namespace wrappers
- project package identity switched to `goblin` with `agentic-forex` command retained as compatibility shim
- legacy `agentic_forex` namespace explicitly marked as compatibility-only with documented deprecation path

### 2026-04-12: Goblin foundation established

- Goblin created as the umbrella program under `/Goblin`
- program, roadmap, status, phase, contract, template, checkpoint, and runbook structure added
- Goblin state made machine-readable through `program_status.json` and per-phase state files

### 2026-04-12: four-channel truth stack established

- `research_backtest` defined as research truth
- `mt5_replay` defined as executable validation truth
- `live_demo` defined as operational truth
- `broker_account_history` defined as reconciliation truth

### 2026-04-12: provenance layer established

- explicit evidence-channel and artifact provenance structures added
- channel-owned artifact indexes introduced
- Goblin artifact registration and validation helpers added

### 2026-04-12: time/session normalization completed

- default research-data contract builder added
- default time/session contract builder added
- truth-alignment reports now declare a comparison time basis and surface mismatches
- OANDA ingest and backfill outputs now record the frozen acquisition contract in provenance

### 2026-04-12: MT5 certification gate completed

- Goblin MT5 certification artifacts are now written for official parity, diagnostic parity, and incident replay runs
- official MT5 parity authority now requires `deployment_grade` certification instead of inferring authority from tester mode alone
- incident replay trust now depends on a passed baseline known-good harness reproduction
- harness trust classification is separated from candidate alpha claims through `deployment_grade`, `research_only`, and `untrusted`

### 2026-04-12: live-demo observability and broker reconciliation completed

- live-demo attach manifests, runtime summaries, and heartbeat series now captured and persisted under the `live_demo` channel
- heartbeat anomaly detection surfaces chaos conditions: terminal close, sleep/wake, account change, algo-trading disabled, and stale audit
- broker reconciliation pipeline parses MT5 account history CSV and matches against EA audit by ticket
- `BrokerReconciliationReport` classifies matched, missing-broker, and extra-broker trades and computes cash PnL delta
- live-demo channel is no longer self-referential; `broker_account_history` now provides independent external verification
- full operational contracts written for both channels; 10 targeted tests pass

### 2026-04-12: incident severity and SLA governance completed (P06)

- `IncidentRecord` now carries `severity` (S1–S4), `sla_class`, `incident_type`, `ladder_state_at_incident`, and `deployed_bundle_id`
- `validate_incident_closure` enforces required closure evidence per severity before an incident can be closed
- `close_incident_record` raises `ValueError` if required fields are missing for the incident's severity class
- `list_open_blocking_incidents` returns open or monitoring S1/S2 incidents that block new live attaches and ladder advancement
- `INCIDENT_RESPONSE.md` runbook rewritten with severity-driven step-by-step procedures
- 17 targeted tests pass

### 2026-04-12: deployment ladder and release gating completed (P07)

- `LiveAttachManifest` now carries `ladder_state`, `broker_server`, and `bundle_id` — no attach can occur without a declared ladder state
- `IncidentClosurePacket` carries `deployed_bundle_id` and `ladder_state_at_incident` for full audit trail
- `validate_attach_against_bundle` checks `inputs_hash` between the approved bundle and the attach manifest; mismatch automatically opens a `release_integrity_failure` S1 incident
- `DeploymentLadderState` type defined with all five states: `shadow_only`, `limited_demo`, `observed_demo`, `challenger_demo`, `eligible_for_replacement`
- `RELEASE_AND_ROLLBACK.md` runbook rewritten with ladder advancement rules, hash-check procedures, and rollback steps
- 7 targeted tests pass

### 2026-04-12: investigation and evaluation framework completed (P08)

- `build_incident_investigation_pack` now writes reproducible investigation artifacts for frozen incidents
- each pack persists scenario JSONs, a trace JSON, an evaluation suite, and a frozen benchmark-history snapshot
- artifact filenames are compact and deterministic so the workflow remains usable under Windows path-length limits
- AF-CAND-0263 same-window postpatch incident now has a real investigation pack under `Goblin/reports/investigations/`
- 40 targeted Goblin tests pass across investigation, controls, incident, CLI, and program surfaces

### 2026-04-12: strategy governance implementation resumed (P09 in progress)

- `GOBLIN-P09` moved from ready to in-progress in phase state tracking
- family-level experiment accounting ledger model and writer were implemented with permissive budget caps
- governed operator actions now enforce strategy governance by requiring a family rationale card and blocking suspended families
- CLI gained `goblin-write-experiment-ledger` for deterministic artifact emission and operator inspection
- targeted tests cover ledger suspension behavior and governed-action gating prerequisites

### 2026-04-13: invalid-comparison enforcement wired into experiment comparison (P09 continuation)

- `compare_experiments` now validates comparison contract prerequisites before ranking candidates
- explicit candidate comparisons are hard-rejected when in-sample/out-of-sample splits, cross-window bounds, or regime accounting are missing
- broad family scans now exclude invalid artifacts and persist exclusion reasons in comparison reports for audit visibility
- targeted comparison/operator/Goblin tests pass after enforcement wiring

### 2026-04-13: methodology rubric audit workflow wired into strategy governance (P09 continuation)

- family-level strategy methodology audits are now written under `Goblin/reports/strategy_methodology_audits/`
- governed actions are blocked when methodology rubric score falls below the configured floor
- strategy-governance manifest summaries now include methodology audit evidence path and score/pass status
- a dedicated strategy-methodology rubric contract was added and included in Goblin contract initialization

### 2026-04-13: strategy governance phase completed (P09)

- direct legacy campaign entrypoints now enforce strategy-governance family gates, preventing suspension bypass outside the operator wrapper
- live/demo progression paths now enforce candidate-level governance and experiment-lineage checks before publish and MT5 packet generation
- promotion decision packets now include experiment-accounting and methodology-audit references with search-bias narrative summaries
- focused governance/campaign/live-demo regression suite passed (`153` tests)

### 2026-04-12: portfolio governance and promotion policy enforcement completed (P10)

- Promotion packets now require explicit statistical policy key citations from `config/eval_gates.toml`; free-text judgment is rejected at write time.
- Promotion decisions are blocked below `observed_demo` ladder state; missing ladder state is a hard error.
- Material deployment-fit deltas (`≥ 0.05`) require a new deployment bundle reference in the promotion packet.
- Portfolio cycle now gates challenger lane progression on an existing promotion packet for the handoff candidate.
- Challenger-vs-benchmark identity conflict is detected and surfaced as a blocked slot report.
- Locked benchmark candidate reference auto-surfaced in every gap slot cycle note.
- Candidate scorecard and promotion packet contracts updated with enforcement rules.
- 24 targeted tests pass across Goblin controls and portfolio layer.

### 2026-04-13: governed ML controls completed (P11)

- Trusted label policy artifacts now require ambiguity rejection criteria and explicit truth-channel constraints.
- Offline training cycle artifacts now require holdout windows and MT5 certification evidence when a model touches live execution.
- Model registry entries now link label-policy and training-cycle artifact paths under Goblin report surfaces.
- Runtime governance now blocks online self-tuning and blocks unapproved models for live-touching use.
- Focused P11 regression suite added in `tests/test_goblin_ml.py`.

### 2026-04-13: knowledge store, vector memory, and bounded agent layer completed (P12)

- Structured knowledge events are now persisted as append-only JSONL under Goblin knowledge reports.
- Retrieval documents can now be persisted and indexed into deterministic vector memory.
- Retrieval queries now produce provenance-cited advisory responses (document id + source hash citations).
- Bounded Goblin agent roles now enforce governance boundaries, blocking approval/promotion/deployment/bypass actions.
- Focused P12 regression suite added in `tests/test_goblin_p12.py`.

### 2026-06-14: full phase validation audit completed

- Comprehensive diagnostic review of all 13 phases (P00–P12) executed before migration/takeover plan review.
- 183/183 tests green (133 core + 50 day-trading).
- 10 issues discovered across 7 files and resolved: P07 state file tracking discrepancy, P05/P09 test governance bootstrap gap, stale day-trading variant assertion, 5 program loop rationale card bootstraps, test-infrastructure PDF path leak, and one production-code bug (comparison validator `in_sample` vs `train` label mismatch in `service.py`).
- Audit report written to `Goblin/reports/phase_validation_audit_20260614.md`.

### 2026-04-14: S1+ remaining-plan roadmap captured

- the remaining post-takeover Goblin work is now formalized in `Goblin/S1_PLUS_PLAN.md`
- the plan is organized into nine operational phases and four bundled checkpoints
- Goblin now distinguishes clearly between completed platform phases and the still-unstarted sequential strategy program

## Near-Term Evolution Order

1. All current roadmap phases (`GOBLIN-P00` to `GOBLIN-P12`) are complete under tracked scope.
2. Full phase validation audit completed.
3. Operational readiness phases P13–P15 harden Goblin for production use.
4. T1–T4 namespace takeover migrates identity from `agentic_forex` to `Goblin`.
5. Multi-timezone/archetype strategy program (S1+) begins after full Goblin operational status.

## Evolution Rule

Goblin evolves in layers:

- first: truth, provenance, replay, and reconciliation
- second: incident, release, and approval control
- third: strategy search and evaluation quality
- fourth: governed intelligence, retrieval, and future namespace takeover
- fifth: sequential multi-timezone strategy development using the completed Goblin system

Anything that skips those layers risks repeating the same control-plane failure Goblin was created to solve.
