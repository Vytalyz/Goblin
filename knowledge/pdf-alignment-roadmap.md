# PDF Alignment Roadmap

## Decision Snapshot

- Date: `2026-03-23`
- Status: `active`
- Source: `Algorithmic Trading - Winning Strategies and Their Rationale (2013)`
- Scope: gap review between the current `Agentic Forex` workflow and the book's later chapter recommendations

## Implemented Now

- Family-specific evidence gates for throughput-lane seeding.
- Structured evidence tags on `market_rationale`.
- Program-policy enforcement that blocks a throughput lane when the seed does not carry the required evidence for that family style.
- MT5 broker-history parity as the official primary parity gate, so MT5 validation rebuilds executable expectations from the same tester bars the EA actually saw.
- Policy-enforced parity classes assigned prospectively at the approved family or hypothesis root, inherited through candidate lineage, and blocked from post-result switching after first official parity evidence.

## Why This Exists

- Chapter 1 already influenced the control-plane shape:
  - backtest hygiene
  - data-snooping caution
  - implementation realism
- The later chapters add strategy-style-specific requirements that should improve seed quality:
  - mean reversion should be justified with stationarity-style evidence
  - momentum should be justified with explicit horizon evidence
  - FX overnight strategies need quote and rollover realism
  - live-capital risk controls should be stronger than research-stage gates

## Evidence Tags To Use

- `mean_reversion_stationarity`
  - Use when the family depends on stationarity, cointegration, Hurst, variance ratio, or ADF-style evidence.
- `mean_reversion_half_life`
  - Use when the family depends on a practical reversion horizon rather than a vague reversal claim.
- `momentum_horizon_correlation`
  - Use when the family depends on time-series momentum, lookback/holding-period logic, or lagged return relationships.
- `fx_common_quote_realism`
  - Use when the family depends on FX cross-rate portfolio construction and common quote-currency math.
- `fx_rollover_realism`
  - Use when the family may hold overnight and total return depends materially on rollover/carry treatment.

## Working Rule

- New throughput families should declare the evidence tags they require in `program_policy.toml`.
- New seeds should carry those tags in `market_rationale.evidence_tags`, either explicitly or through rationale text that infers them.
- If the seed cannot justify the family-specific evidence, the program loop should stop before mutation, compile, or smoke.

## Deferred Recommendations

### 1. Rolling Retrain Walk-Forward

- Status: `deferred`
- Trigger:
  - implement once the system is consistently producing `reviewable_candidate`s that survive the current anchored-window stability screen
- Why:
  - the current anchored walk-forward is a stronger stability check than before, but it is still not a true retrain-and-roll evaluation

### 2. Archetype Scorecard Report

- Status: `deferred`
- Trigger:
  - implement after a few more family retirements or novelty blocks so the report has enough evidence to be useful
- Why:
  - it should make archetype exhaustion visible without reading raw failure records

### 3. FX Overnight Realism Layer

- Status: `deferred`
- Trigger:
  - implement before approving any family that can hold through rollover or trades synthetic cross-rate portfolios
- Why:
  - Chapter 5 highlights that rollover and common quote-currency handling can materially distort FX backtests

### 3a. Detailed Execution-Delta Diagnostics

- Status: `active`
- Trigger:
  - broker-history parity is now the default gate and current promotable candidates fail on `execution_cost_failure` rather than broad `parity_failure`
- Why:
  - once the data-feed mismatch is removed, the next honest blocker is trade-level execution drift
  - the system should surface which dimensions fail first: entry price, exit price, fill delta, or close timing
  - when `1 minute OHLC` parity cannot explain the remaining tails, a separate real-ticks rerun should be used as a diagnostic lane only, not as the authoritative promotion gate

### 3b. Tick-Aware Official Parity Policy

- Status: `deferred`
- Trigger:
  - implement only if path-sensitive intraday families remain strategically in scope after policy review
- Current boundary:
  - `m1_official` is the only approved official parity class
  - `tick_required` may be assigned prospectively, but those families remain blocked until a class-wide official standard is approved
- Why:
  - this keeps parity-class changes prospective and class-wide rather than candidate-specific
  - it prevents near-pass candidates from being rescued by switching to a more favorable standard after results are known

### 4. Risk Governor And Leverage Layer

- Status: `deferred`
- Trigger:
  - implement before any candidate is allowed to move beyond research promotion into real capital-bearing workflows
- Why:
  - Chapter 8 emphasizes leverage as an upper bound, not a target
  - Monte Carlo leverage stress, drawdown-constrained sizing, and leading risk indicators belong closer to deployment than discovery

### 5. Portfolio-Level Allocator

- Status: `deferred`
- Trigger:
  - implement only when more than one family is simultaneously promotable
- Why:
  - capital allocation, correlation, and drawdown constraints are portfolio questions, not single-candidate questions

## Review Trigger

Revisit this roadmap when either condition becomes true:

- a new family is being seeded under the rationale contract
- the first candidate becomes promotable beyond pure research review
