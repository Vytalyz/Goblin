# Goblin ML Evolution Plan

This document is the authoritative plan for evolving Goblin's machine learning, evolutionary algorithm (EvA), and neural network capabilities.

It exists to answer a different question from `Goblin/S1_PLUS_PLAN.md`:

- `Goblin/S1_PLUS_PLAN.md` explains how the completed Goblin system is used to finish the operational trading program.
- `Goblin/ML_EVOLUTION_PLAN.md` explains how Goblin's ML subsystem evolves from its current minimal state toward institutional-grade capabilities without breaking the deterministic kernel or introducing overfitting.

## Terminology

| Term | Meaning |
| --- | --- |
| EvA | Evolutionary Algorithm (CMA-ES, GP, NSGA-II, NEAT, etc.) |
| EA | Expert Advisor (MT5 compiled trading robot) |
| OOS | Out-of-sample |
| PBO | Probability of Backtest Overfitting |
| DSR | Deflated Sharpe Ratio |
| HITL | Human-in-the-loop |
| GP | Genetic Programming |

These must never be conflated. "EvA" is always an optimization algorithm. "EA" is always an MT5 Expert Advisor.

## Planning Objective

Evolve Goblin's ML capabilities through bounded, evidence-gated phases. Each phase must prove its value before the next begins. High-risk phases require explicit owner approval through a structured Go/No-Go protocol with mandatory anti-bias self-audit.

### Core Constraints

- The deterministic kernel (`src/agentic_forex/`) remains authoritative for all trading decisions.
- ML/EvA models are frozen research artifacts — never autonomous decision-makers.
- OANDA is canonical for research and alpha claims. MT5 data is used for deployment-readiness validation.
- `AF-CAND-0263` is immutable. No ML/EvA work may modify the locked benchmark.
- Real-money automated trading remains forbidden unless explicitly reauthorized by repo governance.
- Every ML model must pass the full overfitting defense stack before promotion.

## Current State Audit

### What Exists (ML)

| Component | Location | Status |
| --- | --- | --- |
| LogisticRegression signal filter | `src/agentic_forex/ml/train.py` | `implemented` — scikit-learn, secondary signal filtering role |
| RandomForestClassifier signal filter | `src/agentic_forex/ml/train.py` | `implemented` — scikit-learn, ensemble with LogReg |
| 10 hand-crafted features | `src/agentic_forex/features/service.py` | `implemented` — ret_1, ret_5, zscore_10, momentum_12, volatility_20, etc. |
| Path-aware labels | `src/agentic_forex/ml/train.py` | `implemented` — simulates SL/TP/timeout outcomes |
| 70/30 train/test split | `src/agentic_forex/ml/train.py` | `implemented` — simple split, no purging |
| Ephemeral models (no persistence) | `src/agentic_forex/ml/train.py` | `implemented` — retrained per candidate, not saved |

### What Exists (Anti-Overfitting)

| Component | Location | Threshold | Status |
| --- | --- | --- | --- |
| CSCV / PBO | `src/agentic_forex/evals/robustness.py` | PBO <= 0.35, 8 partitions | `implemented` |
| White's Reality Check | `src/agentic_forex/evals/robustness.py` | p <= 0.10, block_size=5, 250 samples | `implemented` |
| Deflated Sharpe Ratio | `src/agentic_forex/evals/robustness.py` | >= 0.0 | `implemented` |
| Walk-Forward Validation | `src/agentic_forex/backtesting/engine.py` | 3 windows, PF >= 0.90 per window | `implemented` |
| Stress Testing | `src/agentic_forex/backtesting/engine.py` | spread multiplier 1.25x, PF >= 1.0 | `implemented` |
| Rule-based regime breakdown | `src/agentic_forex/backtesting/engine.py` | session/volatility/context buckets | `implemented` |
| Trusted label policy | `src/agentic_forex/ml/` (P11) | ambiguity-rejection gate | `implemented` |
| Offline training cycle controls | `src/agentic_forex/ml/` (P11) | holdout and MT5-live-touch checks | `implemented` |
| Model governance enforcement | `src/agentic_forex/ml/` (P11) | blocks online self-tuning and unapproved live models | `implemented` |

### What Does Not Exist

| Capability | Status |
| --- | --- |
| Purged walk-forward CV with embargo | `not_started` |
| Feature importance / permutation testing | `not_started` |
| Label randomization test | `not_started` |
| Adversarial validation | `not_started` |
| Model persistence / versioning | `not_started` |
| XGBoost / LightGBM | `not_started` |
| EvAs (CMA-ES, GP, NSGA-II, NEAT) | `not_started` |
| GMM/HMM regime classifier | `not_started` |
| MT5 feature alignment test | `not_started` |
| Deep learning (LSTM, CNN, TFT) | `not_started` |
| Reinforcement learning | `not_started` |
| Autoencoder feature discovery | `not_started` |

### Strategy Search Gap

Current candidate generation: LLM one-shot produces a complete `CandidateDraft` with all parameters. Post-generation mutation is limited to 3 narrow diagnostic types (`trim_allowed_hours`, `suppress_context_bucket`, `refresh_execution_cost_defaults`). No population-based search, no continuous parameter optimization, no multi-objective Pareto frontier. EvAs are the natural fit for this gap.

---

## Governance Tiers

| Phase | Tier | Autopilot Behavior | Owner Action Required |
| --- | --- | --- | --- |
| ML-P0 | Autopilot-eligible | Standard governance gates | None — review at completion |
| ML-P1 | Autopilot-eligible | Standard governance gates | None — review at completion |
| ML-P1.5 | Autopilot with elevated validation | GP rule complexity audit before proceeding | None — review at completion |
| ML-P2 | **HITL-gated** | MUST STOP before implementation; deliver Go/No-Go analysis | **Explicit Go/No-Go approval** |
| ML-P3 | **HITL-gated, per-capability** | MUST STOP per sub-capability; deliver independent Go/No-Go per item | **Explicit Go/No-Go approval per capability** |

Autopilot may never advance past a HITL gate without explicit owner approval. Bundling multiple HITL approvals into a single decision is forbidden.

---

## Data Policy

### OANDA-Primary, MT5-Validated

OANDA and MT5 have structural differences that create a distribution mismatch for ML models:

| Aspect | OANDA | MT5 |
| --- | --- | --- |
| Price model | Real bid/ask pair per bar | Single price stream + broker spread |
| Spread | Real market spread from API | Configured/broker-derived |
| Volume | Tick count per minute | Relative volume (not comparable) |
| Tick provenance | Real market ticks | Synthetic OHLC generation in parity mode |
| Commission | Spread-only | Configurable per symbol |

The existing parity system already tolerates ±0.30 pip price differences and requires only 80% structural match rate, acknowledging this divergence.

### Policy

- **Research/discovery**: OANDA-primary. All training data sourced from OANDA API.
- **ML validation**: Must include MT5 feature alignment test (adversarial classifier on OANDA vs MT5 features, AUC <= 0.60).
- **Signal filter calibration**: If a model informs EA behavior, final calibration must include MT5 execution data to account for spread/fill differences.
- **Governance**: OANDA remains canonical for alpha claims. MT5 data validates deployment readiness but never overrides research truth.

---

## Phase Map

| Phase | Title | Depends On | Governance | Risk | Primary Outcome |
| --- | --- | --- | --- | --- | --- |
| `ML-P0` | Harden Existing ML Infrastructure | Goblin P11 complete | Autopilot | Low | Production-grade ML pipeline with purged CV, feature importance, label randomization, adversarial validation, model persistence |
| `ML-P1` | EvA Parameter Optimization + Regime Classifier + Gradient-Boosted Filter | `ML-P0` | Autopilot | Medium | CMA-ES/DE optimizer, GMM regime classifier, XGBoost signal filter, MT5 feature alignment |
| `ML-P1.5` | Genetic Programming for Rule Discovery | `ML-P1` | Autopilot (elevated) | Medium | GP-evolved entry/exit rules from feature primitives |
| `ML-P2` | Lightweight Temporal Models | `ML-P1.5` | **HITL** | High | Small LSTM/CNN feature extractors (< 50K params) |
| `ML-P3a` | Temporal Fusion Transformer | `ML-P2` | **HITL** | High | Small TFT (< 100K params) multi-horizon forecasting |
| `ML-P3b` | RL Position Sizing | `ML-P2` | **HITL** | High | PPO/SAC agent for lot size optimization |
| `ML-P3c` | NEAT Neuroevolution | `ML-P2` | **HITL** | High | Topology+weight co-evolution of minimal NNs |
| `ML-P3d` | Autoencoder Feature Discovery | `ML-P2` | **HITL** | High | Bottleneck autoencoder for latent feature extraction |

---

## Execution Bundles

### Bundle A: ML Foundation Hardening

Includes: `ML-P0`

Purpose: Make the existing ML pipeline production-grade before adding any new capabilities. This is independently valuable even if no further phases are executed.

Definition of done:
- Purged walk-forward CV with embargo replaces 70/30 split
- Feature importance analysis identifies which of the 10 features contribute
- Label randomization test verifies models are not memorizing noise
- Adversarial validation detects train/test distribution shift
- Model persistence saves trained models as versioned artifacts with lineage
- All existing 391+ tests pass
- New tests cover every new gate

Rollback: Revert `ml/train.py`, `evals/robustness.py`, and `eval_gates.toml` changes. Existing pipeline is unchanged.

Checkpoint: `Goblin/checkpoints/ML-BUNDLE-A/ml-foundation-hardened.json`

### Bundle B: Intelligent Search and Signal Enhancement

Includes: `ML-P1`, `ML-P1.5`

Purpose: Add the three highest-value ML capabilities: systematic parameter search (EvA), market regime awareness (GMM), better signal filtering (XGBoost), and rule discovery (GP).

Definition of done:
- CMA-ES/DE finds parameters that beat LLM-guessed defaults on OOS data
- GMM regime classifier produces stable labels across walk-forward windows
- XGBoost signal filter beats LogReg+RF ensemble on OOS metrics
- MT5 feature alignment test passes (AUC <= 0.60)
- GP discovers at least 1 human-interpretable rule that passes all governance gates
- All governance gates pass on every new model
- Rule-only baseline comparison documented for every addition

Rollback: Remove new modules (`regime.py`, `optimizer.py`, `gp_rules.py`, `primitives.py`). Revert `train.py` to Phase 0 state. Remove `xgboost`, `cma`/`pymoo`, `deap` from `pyproject.toml`.

Checkpoint: `Goblin/checkpoints/ML-BUNDLE-B/eva-regime-xgboost-gp-complete.json`

### Bundle C: Deep Learning Exploration (HITL-Gated)

Includes: `ML-P2`

Purpose: Explore whether temporal neural nets add measurable OOS value beyond tree-based models. This is speculative — the hypothesis is that sequential patterns in price action contain signal that XGBoost cannot capture.

Definition of done:
- Go/No-Go analysis delivered and approved by owner
- Small LSTM or 1D-CNN (< 50K params) implemented as feature extractor
- Temporal features fed into XGBoost, not used as standalone predictor
- OOS improvement is statistically significant (White's test)
- All governance gates pass including PBO <= 0.35
- Label randomization confirms model is not memorizing noise

Rollback: Remove `temporal.py`, `ensemble.py`. Remove `torch` from `pyproject.toml`. Revert to Phase 1.5 pipeline.

Checkpoint: `Goblin/checkpoints/ML-BUNDLE-C/temporal-models-evaluated.json`

### Bundle D: Advanced Capabilities (HITL-Gated, Per-Capability)

Includes: `ML-P3a`, `ML-P3b`, `ML-P3c`, `ML-P3d` (each independently approved)

Purpose: Explore advanced techniques that institutions use in production. Each capability is independently evaluated and approved.

Definition of done (per capability):
- Independent Go/No-Go analysis delivered and approved
- Capability implemented with all mandatory controls
- Beats Phase 2 baseline on OOS data
- All governance gates pass
- Complexity caps enforced

Rollback: Remove the specific capability module. No cross-dependency between P3 sub-phases.

Checkpoint: One per sub-phase:
- `Goblin/checkpoints/ML-BUNDLE-D/tft-evaluated.json`
- `Goblin/checkpoints/ML-BUNDLE-D/rl-sizing-evaluated.json`
- `Goblin/checkpoints/ML-BUNDLE-D/neat-evaluated.json`
- `Goblin/checkpoints/ML-BUNDLE-D/autoencoder-evaluated.json`

---

## Phase Detail

### `ML-P0`: Harden Existing ML Infrastructure

**Risk:** Low
**Governance:** Autopilot-eligible
**Goal:** Make current ML pipeline production-grade before adding complexity

#### Steps

| Step | Task | File(s) | Depends On |
| --- | --- | --- | --- |
| P0.1 | Replace 70/30 split with purged walk-forward CV | `src/agentic_forex/ml/train.py` | — |
| P0.2 | Implement embargo buffer: `embargo_bars = max(holding_bars, 10)` | `src/agentic_forex/ml/train.py` | P0.1 |
| P0.3 | Add permutation feature importance analysis | `src/agentic_forex/ml/train.py` | — |
| P0.4 | Add label randomization test (retrain on shuffled labels, verify accuracy <= 0.55) | `src/agentic_forex/ml/train.py` | — |
| P0.5 | Add adversarial validation (train/test distribution shift, AUC <= 0.55) | `src/agentic_forex/ml/train.py` | — |
| P0.6 | Add model persistence with versioned artifacts and lineage metadata | `src/agentic_forex/ml/train.py` | — |
| P0.7 | Add new thresholds to `config/eval_gates.toml` | `config/eval_gates.toml` | P0.4, P0.5 |
| P0.8 | Write tests for all new gates | `tests/test_ml_hardening.py` (new) | P0.1–P0.7 |
| P0.9 | Verify all existing tests still pass | all test files | P0.8 |

#### New Config Keys

```toml
[ml_hardening]
label_randomization_accuracy_ceiling = 0.55
adversarial_auc_threshold = 0.55
purged_cv_embargo_minimum_bars = 10
feature_importance_top3_floor = 0.40
model_persistence_format = "joblib"
```

#### Acceptance Criteria

- [x] Purged CV with embargo replaces 70/30 split in all training paths
- [x] Feature importance report generated for every trained model
- [x] Label randomization test runs automatically and gates model promotion
- [x] Adversarial validation runs automatically and gates model promotion
- [x] Model artifacts saved with lineage (candidate_id, training_timestamp, feature_set_hash, data_window)
- [x] All new gates have thresholds in `eval_gates.toml`
- [x] All existing tests pass (407)
- [x] New test coverage for every new function (16 tests in test_ml_hardening.py)

#### Rollback Procedure

1. Revert `ml/train.py` to pre-P0 state (restore 70/30 split)
2. Revert `evals/robustness.py` to remove adversarial validation and label randomization
3. Revert `eval_gates.toml` to remove new thresholds
4. Remove `ml/registry.py` if created
5. Remove `tests/test_ml_hardening.py`
6. Run full test suite to confirm clean revert

---

### `ML-P1`: EvA Parameter Optimization + Regime Classifier + Gradient-Boosted Filter

**Risk:** Medium
**Governance:** Autopilot-eligible
**Goal:** Add systematic parameter search, market regime awareness, and better signal filtering
**Depends on:** `ML-P0` complete

#### Steps

| Step | Task | File(s) | Depends On |
| --- | --- | --- | --- |
| P1.1 | Add `xgboost` dependency to `pyproject.toml` | `pyproject.toml` | — |
| P1.2 | Add `cma` or `pymoo` dependency to `pyproject.toml` | `pyproject.toml` | — |
| P1.3 | Implement CMA-ES/DE parameter optimizer | `src/agentic_forex/ml/optimizer.py` (new) | P1.2 |
| P1.4 | Define optimizer bounds from governance-allowed ranges | `config/eval_gates.toml` | P1.3 |
| P1.5 | Implement GMM regime classifier | `src/agentic_forex/ml/regime.py` (new) | — |
| P1.6 | Add `regime_label` to feature pipeline | `src/agentic_forex/features/service.py` | P1.5 |
| P1.7 | Replace RandomForest with XGBoost in signal filter | `src/agentic_forex/ml/train.py` | P1.1 |
| P1.8 | Add SHAP-based interpretability to XGBoost outputs | `src/agentic_forex/ml/train.py` | P1.7 |
| P1.9 | Implement MT5 feature alignment test (adversarial OANDA vs MT5) | `src/agentic_forex/evals/robustness.py` | — |
| P1.10 | Wire EvA optimizer into campaign loop as alternative to LLM parameter guessing | `src/agentic_forex/campaigns/next_step.py` | P1.3 |
| P1.11 | Write tests for all new components | `tests/test_ml_phase1.py` (new) | P1.3–P1.10 |
| P1.12 | Run rule-only baseline comparison and document results | `Goblin/reports/ml/` | P1.11 |

#### CMA-ES Optimizer Specification

- **Parameters optimized:** `stop_loss_pips`, `take_profit_pips`, `signal_threshold`, `holding_bars`
- **Fitness function:** OOS profit factor from walk-forward, penalized by PBO score
- **Population size:** 20–50 (configurable)
- **Bounds:** Governed by `config/eval_gates.toml` and `config/risk_policy.toml`
- **Budget:** Each individual requires a full backtest (~1s each). Population=50, generations=100 = ~5000 backtests = ~80 min.
- **Governance:** Every individual in the population must pass PBO before fitness ranking

#### GMM Regime Classifier Specification

- **Input features:** `[volatility_20, momentum_12, zscore_10, spread_to_range_10, hour]`
- **Training:** Rolling windows, scikit-learn `GaussianMixture`
- **Output:** `regime_label` — one of `[crisis, steady, volatile, transitional]` (start with 3–4, validate which granularity overfits)
- **Validation:** Labels must be stable across walk-forward windows
- **Institutional precedent:** Two Sigma (2021) — GMM on 17-factor returns for 4 market conditions

#### New Config Keys

```toml
[eva_optimizer]
default_population_size = 30
default_generations = 80
fitness_pbo_penalty_weight = 0.3
stop_loss_pips_bounds = [5.0, 50.0]
take_profit_pips_bounds = [5.0, 100.0]
signal_threshold_bounds = [0.3, 0.9]
holding_bars_bounds = [5, 120]

[regime_classifier]
n_components_range = [3, 5]
regime_stability_min_window_agreement = 0.60

[mt5_alignment]
feature_alignment_auc_threshold = 0.60

[signal_filter]
model_type = "xgboost"
max_leaves = 500
```

#### Acceptance Criteria

- [ ] CMA-ES/DE finds parameters that beat LLM-guessed defaults on OOS data
- [ ] GMM regime classifier produces stable labels across all walk-forward windows (>= 60% agreement)
- [ ] XGBoost signal filter beats LogReg+RF ensemble on OOS profit factor
- [ ] MT5 feature alignment test passes (AUC <= 0.60)
- [ ] SHAP importance values generated for every XGBoost model
- [ ] PBO, White's, DSR all pass with new models
- [ ] Rule-only baseline comparison documented in `Goblin/reports/ml/`
- [ ] All existing + new tests pass

#### Rollback Procedure

1. Remove `src/agentic_forex/ml/optimizer.py`, `src/agentic_forex/ml/regime.py`
2. Revert `train.py` to Phase 0 state (restore LogReg+RF)
3. Revert `features/service.py` to remove `regime_label`
4. Revert `evals/robustness.py` to remove MT5 alignment test
5. Revert `eval_gates.toml` to Phase 0 thresholds
6. Remove `xgboost`, `cma`/`pymoo` from `pyproject.toml`
7. Remove `tests/test_ml_phase1.py`
8. Run full test suite

---

### `ML-P1.5`: Genetic Programming for Rule Discovery

**Risk:** Medium
**Governance:** Autopilot-eligible with elevated validation (GP rule complexity audit)
**Goal:** Discover novel entry/exit rules from feature primitives instead of LLM one-shot generation
**Depends on:** `ML-P1` complete, CMA-ES proves parameter optimization adds measurable value

#### Steps

| Step | Task | File(s) | Depends On |
| --- | --- | --- | --- |
| P1.5.1 | Add `deap` dependency to `pyproject.toml` | `pyproject.toml` | — |
| P1.5.2 | Define feature primitive set | `src/agentic_forex/ml/primitives.py` (new) | — |
| P1.5.3 | Implement GP rule discovery engine | `src/agentic_forex/ml/gp_rules.py` (new) | P1.5.1, P1.5.2 |
| P1.5.4 | Wire parsimony pressure (tree depth penalty in fitness) | `src/agentic_forex/ml/gp_rules.py` | P1.5.3 |
| P1.5.5 | Connect GP output to CandidateDraft pipeline | `src/agentic_forex/campaigns/` | P1.5.3 |
| P1.5.6 | Write tests | `tests/test_ml_gp.py` (new) | P1.5.3–P1.5.5 |
| P1.5.7 | Run GP discovery, document results in `Goblin/reports/ml/` | — | P1.5.6 |

#### GP Specification

- **Primitive set:** Features (`ret_1`, `ret_5`, `zscore_10`, `momentum_12`, `volatility_20`, `spread_pips`, `hour`, etc.) + operators (`+`, `-`, `*`, `/`, `>`, `<`, `AND`, `OR`)
- **Individual:** Boolean expression tree representing an entry rule
- **Fitness:** OOS profit factor from walk-forward, penalized by tree depth
- **Crossover:** Subtree swap
- **Mutation:** Point mutation, subtree insertion
- **Population:** 100–200 individuals, 50–100 generations
- **Parsimony:** Max tree depth 6–8 (configurable). Without this, GP evolves massive trees that overfit.
- **Output:** Best rules become new `CandidateDraft` specs for the standard pipeline

#### New Config Keys

```toml
[gp_rules]
population_size = 150
generations = 75
max_tree_depth = 7
parsimony_coefficient = 0.01
crossover_probability = 0.7
mutation_probability = 0.2
tournament_size = 5
```

#### Acceptance Criteria

- [ ] GP discovers at least 1 rule that passes all governance gates (PBO <= 0.35, White's p <= 0.10)
- [ ] Evolved rules are human-interpretable (max tree depth enforced, printed in readable form)
- [ ] GP-discovered rules beat at least one LLM-generated candidate on OOS metrics
- [ ] Parsimony pressure measurably reduces tree complexity (compare with/without)
- [ ] All tests pass

#### Rollback Procedure

1. Remove `src/agentic_forex/ml/gp_rules.py`, `src/agentic_forex/ml/primitives.py`
2. Remove `deap` from `pyproject.toml`
3. Revert campaign wiring if modified
4. Remove `tests/test_ml_gp.py`
5. Run full test suite

---

### `ML-P2`: Lightweight Temporal Models

**Risk:** High
**Governance:** HITL-gated — autopilot MUST STOP and deliver Go/No-Go analysis before implementation
**Goal:** Explore whether temporal neural nets add measurable OOS value beyond tree-based models
**Depends on:** `ML-P1.5` complete, XGBoost shows measurable OOS improvement over rule-only baseline

#### HITL Gate

Before ANY implementation in this phase:

1. Autopilot produces a complete Go/No-Go Analysis Package (see protocol below)
2. Autopilot runs the Pre-Delivery Self-Audit
3. Owner reviews and provides explicit GO, NO-GO, or CONDITIONAL GO
4. Only on GO does implementation begin

#### Steps (Contingent on Owner GO)

| Step | Task | File(s) | Depends On |
| --- | --- | --- | --- |
| P2.1 | Add `torch` (CPU only) as optional dependency | `pyproject.toml` | Owner GO |
| P2.2 | Implement small 1D-CNN or LSTM feature extractor (< 50K params) | `src/agentic_forex/ml/temporal.py` (new) | P2.1 |
| P2.3 | Implement multi-seed ensemble averaging | `src/agentic_forex/ml/ensemble.py` (new) | P2.2 |
| P2.4 | Wire temporal features into XGBoost filter as additional input | `src/agentic_forex/ml/train.py` | P2.2 |
| P2.5 | Enforce mandatory controls: dropout 0.3–0.5, early stopping patience=10, weight decay 1e-4, batch norm, ensemble 3+ seeds | `src/agentic_forex/ml/temporal.py` | P2.2 |
| P2.6 | Write tests | `tests/test_ml_temporal.py` (new) | P2.2–P2.5 |
| P2.7 | Run against Phase 1 baseline, document results | `Goblin/reports/ml/` | P2.6 |

#### Temporal Model Specification

- **Architecture:** Small 1D-CNN or LSTM (< 50K parameters enforced)
- **Input:** Rolling window of raw features (last 20 bars)
- **Output:** Learned embedding vector fed into XGBoost filter — NOT a standalone predictor
- **Mandatory controls:**
  - Dropout: 0.3–0.5 on all hidden layers
  - Early stopping: patience=10 on validation loss
  - Weight decay: L2 regularization at 1e-4
  - Batch normalization on inputs
  - Ensemble: minimum 3 random seeds, average predictions
  - Purged CV for all training
- **Complexity cap:** < 50K parameters (enforced at initialization)

#### Acceptance Criteria

- [ ] Owner has provided explicit GO approval
- [ ] OOS improvement over Phase 1 baseline is statistically significant (White's test, p <= 0.10)
- [ ] PBO <= 0.35 maintained
- [ ] Label randomization confirms model is not memorizing noise (accuracy <= 0.55 on shuffled labels)
- [ ] Model size < 50K parameters (verified programmatically)
- [ ] Multi-seed ensemble shows reduced variance compared to single-seed
- [ ] All tests pass

#### Rollback Procedure

1. Remove `src/agentic_forex/ml/temporal.py`, `src/agentic_forex/ml/ensemble.py`
2. Revert `train.py` to Phase 1 state (remove temporal feature inputs)
3. Remove `torch` from `pyproject.toml`
4. Remove `tests/test_ml_temporal.py`
5. Run full test suite

---

### `ML-P3a`: Temporal Fusion Transformer

**Risk:** High
**Governance:** HITL-gated — requires independent Go/No-Go analysis and owner approval
**Goal:** Evaluate whether a small TFT provides value beyond LSTM/CNN
**Depends on:** `ML-P2` complete, temporal models show measurable OOS improvement

#### HITL Gate

Independent Go/No-Go analysis required. Cannot be bundled with P3b/P3c/P3d.

#### Steps (Contingent on Owner GO)

| Step | Task | File(s) |
| --- | --- | --- |
| P3a.1 | Implement small TFT variant (< 100K params) | `src/agentic_forex/ml/tft.py` (new) |
| P3a.2 | Variable selection network for built-in feature importance | `src/agentic_forex/ml/tft.py` |
| P3a.3 | Wire into signal filter pipeline | `src/agentic_forex/ml/train.py` |
| P3a.4 | Tests and baseline comparison | `tests/test_ml_tft.py` (new) |

#### Acceptance Criteria

- [ ] Must beat Phase 2 LSTM/CNN baseline on OOS data AND pass all governance gates
- [ ] Feature importance from variable selection network is consistent with permutation importance

#### Rollback

Remove `tft.py`, revert `train.py`, remove test file.

---

### `ML-P3b`: RL Position Sizing

**Risk:** High
**Governance:** HITL-gated — requires independent Go/No-Go analysis and owner approval
**Goal:** Optimize lot sizing and trade timing within existing signals (NOT signal generation)
**Depends on:** `ML-P2` complete

#### HITL Gate

Independent Go/No-Go analysis required. Cannot be bundled with P3a/P3c/P3d.

#### Steps (Contingent on Owner GO)

| Step | Task | File(s) |
| --- | --- | --- |
| P3b.1 | Build simulation environment on Goblin's backtesting engine | `src/agentic_forex/ml/sizing_env.py` (new) |
| P3b.2 | Implement PPO or SAC agent | `src/agentic_forex/ml/sizing_rl.py` (new) |
| P3b.3 | Define reward function: risk-adjusted PnL (Sharpe-based) | `src/agentic_forex/ml/sizing_rl.py` |
| P3b.4 | Enforce risk_policy.toml limits within agent action space | `src/agentic_forex/ml/sizing_rl.py` |
| P3b.5 | Tests and baseline comparison | `tests/test_ml_rl.py` (new) |

#### Constraints

- Must not violate `risk_policy.toml` limits: `max_total_exposure_lots=5.0`, `risk_per_trade_pct=0.25`
- Agent action space must be bounded to governance-allowed lot sizes
- Requires `stable-baselines3` dependency

#### Acceptance Criteria

- [ ] RL-sized positions produce better risk-adjusted returns than fixed sizing on OOS data
- [ ] No risk_policy.toml limit violations across any test scenario

#### Rollback

Remove `sizing_env.py`, `sizing_rl.py`, `stable-baselines3` dep, revert test file.

---

### `ML-P3c`: NEAT Neuroevolution

**Risk:** High
**Governance:** HITL-gated — requires independent Go/No-Go analysis and owner approval
**Goal:** Evolve small NN topology + weights together as alternative to hand-designed architecture
**Depends on:** `ML-P2` complete

#### HITL Gate

Independent Go/No-Go analysis required. Cannot be bundled with P3a/P3b/P3d.

#### Steps (Contingent on Owner GO)

| Step | Task | File(s) |
| --- | --- | --- |
| P3c.1 | Implement NEAT evolution engine | `src/agentic_forex/ml/neat_evolver.py` (new) |
| P3c.2 | Population governance: each individual passes through PBO | `src/agentic_forex/ml/neat_evolver.py` |
| P3c.3 | Complexity cap on evolved topology | `src/agentic_forex/ml/neat_evolver.py` |
| P3c.4 | Tests and Phase 2 baseline comparison | `tests/test_ml_neat.py` (new) |

#### Constraints

- Requires `neat-python` dependency
- Evolved networks start from zero complexity (NEAT default)
- Population governance: every individual passes PBO before fitness ranking

#### Acceptance Criteria

- [ ] NEAT-evolved networks beat Phase 2 LSTM/CNN baseline on OOS data
- [ ] Evolved topology is minimal (verifiable node/connection count)

#### Rollback

Remove `neat_evolver.py`, `neat-python` dep, test file.

---

### `ML-P3d`: Autoencoder Feature Discovery

**Risk:** High
**Governance:** HITL-gated — requires independent Go/No-Go analysis and owner approval
**Goal:** Learn compressed latent features from raw bar windows
**Depends on:** `ML-P2` complete

#### HITL Gate

Independent Go/No-Go analysis required. Cannot be bundled with P3a/P3b/P3c.

#### Steps (Contingent on Owner GO)

| Step | Task | File(s) |
| --- | --- | --- |
| P3d.1 | Implement small bottleneck autoencoder (< 30K params) | `src/agentic_forex/ml/autoencoder.py` (new) |
| P3d.2 | Feed latent features into XGBoost alongside hand-crafted features | `src/agentic_forex/ml/train.py` |
| P3d.3 | Validate latent features via feature importance test | `src/agentic_forex/ml/autoencoder.py` |
| P3d.4 | Tests and baseline comparison | `tests/test_ml_autoencoder.py` (new) |

#### Acceptance Criteria

- [ ] Latent features contribute measurably to signal filter (permutation importance > 0)
- [ ] Autoencoder reconstruction loss is meaningful (not trivially memorizing)
- [ ] Combined XGBoost (hand-crafted + latent) beats hand-crafted-only baseline on OOS

#### Rollback

Remove `autoencoder.py`, revert `train.py`, remove test file.

---

## Overfitting Defense Stack

Every ML model at every phase must pass ALL applicable gates before promotion:

| Gate | Threshold | Introduced | Applies To |
| --- | --- | --- | --- |
| PBO (CSCV) | <= 0.35 | Existing | All phases |
| White's Reality Check | p <= 0.10 | Existing | All phases |
| Deflated Sharpe Ratio | >= 0.0 | Existing | All phases |
| Walk-Forward Stability | PF >= 0.90 per window | Existing | All phases |
| Label Randomization | accuracy <= 0.55 on shuffled labels | `ML-P0` | All phases from P0 onward |
| Adversarial Validation | AUC <= 0.55 (train vs test) | `ML-P0` | All phases from P0 onward |
| Feature Importance | top-3 features >= 40% importance | `ML-P0` | All phases from P0 onward |
| OOS Baseline Beat | must beat rule-only baseline | `ML-P0` | All phases from P0 onward |
| Purged CV | embargo = max(holding_bars, 10) | `ML-P0` | All phases from P0 onward |
| Model Complexity Cap | <= 50K params NNs, <= 500 leaves trees | `ML-P1` | All phases from P1 onward |
| MT5 Feature Alignment | AUC <= 0.60 (OANDA vs MT5 classifier) | `ML-P1` | All phases from P1 onward |
| EvA Population Governance | every individual passes PBO before fitness ranking | `ML-P1` | EvA phases (P1, P1.5, P3c) |
| GP Parsimony Pressure | max tree depth enforced, complexity penalized | `ML-P1.5` | GP phases (P1.5) |

---

## HITL Go/No-Go Analysis Protocol

### When It Triggers

Autopilot reaches a HITL-gated phase boundary (`ML-P2`, `ML-P3a`, `ML-P3b`, `ML-P3c`, `ML-P3d`). It MUST stop and produce the analysis package below before any implementation begins.

### Go/No-Go Analysis Package

The analysis must contain ALL of the following sections:

**1. Evidence Summary**
- Quantitative results from the prior phase: OOS profit factor, PBO score, White's p-value, DSR
- Comparison: current baseline vs proposed addition (what gap does this fill?)
- Sample size and statistical power assessment
- Walk-forward results for ALL windows (not cherry-picked)

**2. Risk Assessment**
- What can break in Goblin if this phase introduces a fault?
- Overfitting risk specific to this technique (cite research, not opinion)
- Dependency impact: new libraries, compute cost, maintenance burden
- Reversibility: how hard is it to roll back?
- Interaction risks: does this change the behavior of existing phases?

**3. Institutional Evidence**
- Which verified institutions use this technique in production? (name firms, cite papers or public disclosures)
- What scale do they operate at vs Goblin's scale?
- Known failure modes from published research

**4. Counter-Arguments (Mandatory Anti-Bias Section)**
- At least 2 concrete reasons NOT to proceed
- Published evidence or logical arguments against this technique in the forex/low-SNR domain
- Assessment: are the prior-phase results strong enough to justify added complexity, or could they be noise/luck?
- Null hypothesis framing: "What would we expect to see if the prior phase improvements were random?"

**5. Recommendation**
- **GO:** proceed with implementation, citing specific evidence thresholds met
- **NO-GO:** defer or abandon, citing specific evidence thresholds not met
- **CONDITIONAL GO:** proceed only if [specific condition] — list exact conditions

### Pre-Delivery Self-Audit

Before presenting the Go/No-Go package to the owner, autopilot must run this self-audit checklist:

| Check | Question | Fail Action |
| --- | --- | --- |
| Confirmation bias | Does the analysis assume the answer is "go"? Are counter-arguments genuine or token? | Rewrite counter-arguments with strongest available evidence against |
| Cherry-picking | Are OOS metrics cherry-picked from favorable windows? Is the full walk-forward shown? | Include ALL windows, including worst-performing |
| Anchoring | Is the recommendation anchored to the plan rather than the evidence? | Recommendation must cite evidence, not plan sequence |
| Complexity creep | Is the proposed addition proportional to the measured gap? Could a simpler approach close the same gap? | Name the simpler alternative and explain why it's insufficient (or recommend it instead) |
| Sample size | Is there enough OOS data to distinguish real improvement from noise? | Calculate minimum detectable effect size; if underpowered, recommend NO-GO or data collection |
| Survivorship | Are we only reporting the metrics that look good? | Include all governance gate results, including near-misses |

If any self-audit check fails, the analysis must be revised before delivery. The self-audit results must be disclosed in the analysis package.

---

## Explicitly Excluded (Hard Governance Conflicts)

| Capability | Reason | Reversibility |
| --- | --- | --- |
| LLM as trade decision-maker | Violates deterministic kernel contract; non-reproducible; unauditable | N/A — hard exclusion |
| GAN-based synthetic data augmentation | Generates artificial patterns that contaminate the research truth stack; parity system cannot validate synthetic data | N/A — hard exclusion |
| Full-scale transformers (GPT/BERT-style) | Millions of parameters; completely disproportionate to forex M1 bar data sample size | N/A — hard exclusion |

These exclusions may only be revisited through an explicit governance change authored in `AGENTS.md`.

---

## Status Tracker

### Phase Status

| Phase | Status | Started | Completed | Blocker | Notes |
| --- | --- | --- | --- | --- | --- |
| `ML-P0` | `completed` | 2025-07-18 | 2025-07-18 | — | All 9 steps implemented; 407 tests pass |
| `ML-P1` | `not_started` | — | — | `ML-P0` | — |
| `ML-P1.5` | `not_started` | — | — | `ML-P1` | — |
| `ML-P2` | `not_started` | — | — | `ML-P1.5` + HITL | — |
| `ML-P3a` | `not_started` | — | — | `ML-P2` + HITL | — |
| `ML-P3b` | `not_started` | — | — | `ML-P2` + HITL | — |
| `ML-P3c` | `not_started` | — | — | `ML-P2` + HITL | — |
| `ML-P3d` | `not_started` | — | — | `ML-P2` + HITL | — |

Status values: `not_started`, `in_progress`, `hitl_pending` (waiting for Go/No-Go), `approved`, `completed`, `no_go` (rejected at HITL gate), `rolled_back`

### Bundle Status

| Bundle | Status | Phases | Notes |
| --- | --- | --- | --- |
| Bundle A | `completed` | ML-P0 | ML Foundation Hardening |
| Bundle B | `not_started` | ML-P1, ML-P1.5 | Intelligent Search and Signal Enhancement |
| Bundle C | `not_started` | ML-P2 | Deep Learning Exploration (HITL) |
| Bundle D | `not_started` | ML-P3a–P3d | Advanced Capabilities (HITL per-capability) |

### Go/No-Go Decision Log

| Phase | Analysis Delivered | Self-Audit Passed | Owner Decision | Decision Date | Conditions |
| --- | --- | --- | --- | --- | --- |
| `ML-P2` | — | — | — | — | — |
| `ML-P3a` | — | — | — | — | — |
| `ML-P3b` | — | — | — | — | — |
| `ML-P3c` | — | — | — | — | — |
| `ML-P3d` | — | — | — | — | — |

### Incident Log

| Date | Phase | Severity | Description | Resolution | Rollback Required |
| --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — |

---

## Institutional Research References

| Source | Author/Firm | Year | Relevance | Used In |
| --- | --- | --- | --- | --- |
| "Advances in Financial Machine Learning" | Lopez de Prado (AQR/Cornell) | 2018 | Purged CV, feature importance, triple barrier labeling | ML-P0 |
| "The Probability of Backtest Overfitting" | Lopez de Prado & Bailey | 2014 | CSCV/PBO framework | Existing (evals/robustness.py) |
| "The Deflated Sharpe Ratio" | Lopez de Prado | 2014 | Multi-trial Sharpe adjustment | Existing (evals/robustness.py) |
| "A Reality Check for Data Snooping" | White | 2000 | Bootstrap significance test | Existing (evals/robustness.py) |
| "A Test for Superior Predictive Ability" | Hansen | 2005 | Stepwise SPA test | Existing (evals/robustness.py) |
| "A Machine Learning Approach to Regime Modeling" | Two Sigma | 2021 | GMM on factor returns for 4 market conditions | ML-P1 |
| "Understanding deep learning requires rethinking generalization" | Zhang et al. | 2017 | Label randomization test | ML-P0 |
| GP for rule discovery (published hiring/research) | Man AHL | Various | Genetic programming for trading rules | ML-P1.5 |
| CMA-ES/DE for hyperparameters (published research) | D.E. Shaw, AQR | Various | Population-based parameter optimization | ML-P1 |
| NSGA-II multi-objective optimization | Deb et al. | 2002 | Pareto frontier optimization | ML-P1 |
| NEAT neuroevolution | Kenneth Stanley (Uber AI Labs) | 2002+ | Topology+weight co-evolution | ML-P3c |
| Temporal Fusion Transformers | Google Research | 2019 | Time series forecasting architecture | ML-P3a |
| PPO/SAC for execution optimization | AQR, Two Sigma (practice) | Various | RL for position sizing | ML-P3b |

---

## Decisions Log

| Decision | Rationale | Date |
| --- | --- | --- |
| EvA = Evolutionary Algorithm, EA = Expert Advisor — never conflate | MT5 EAs coexist with EvAs in the same codebase | 2026-04-19 |
| OANDA-primary, MT5-validated data policy | Distribution mismatch between data sources acknowledged; OANDA canonical for research, MT5 for deployment readiness | 2026-04-19 |
| XGBoost over LightGBM | Better SHAP ecosystem for Goblin's data size | 2026-04-19 |
| CMA-ES over grid/random search | Handles continuous parameter spaces efficiently with population-based search | 2026-04-19 |
| No torch until Phase 1 proves value | EvAs and trees first; neural nets only if justified by evidence | 2026-04-19 |
| Phase 2 and 3 are HITL-gated | High-risk phases require explicit owner Go/No-Go approval | 2026-04-19 |
| Phase 3 per-capability Go/No-Go | TFT, RL, NEAT, autoencoder each need separate approval — no bundling | 2026-04-19 |
| Anti-bias self-audit mandatory | Every Go/No-Go analysis must pass 6-point self-audit before delivery | 2026-04-19 |
| All ML must beat rule-only baseline | If deterministic logic alone performs comparably, ML adds complexity without value | 2026-04-19 |
| AF-CAND-0263 immutable | No ML/EvA modifications to locked benchmark | 2026-04-19 |
| Hard-excluded: LLM-as-trader, GANs, full-scale transformers | Governance conflicts with deterministic kernel, truth stack, or data proportionality | 2026-04-19 |

---

## Update Rule

Whenever ML evolution work changes implementation reality, this plan and the main `Goblin/IMPLEMENTATION_TRACKER.md` must both be updated in the same change. Phase status, bundle status, Go/No-Go decision log, and incident log must be kept current.
