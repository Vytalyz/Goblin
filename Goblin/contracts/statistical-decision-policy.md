# Statistical Decision Policy

This contract defines the numeric thresholds and classification rules that govern Goblin decisions: when to open an incident, when to promote a candidate, when to treat a live-demo result as within ordinary variance, and when to treat it as an unexplained failure. All thresholds are strategy-class-based and must not be adjusted to accommodate a specific candidate's performance history.

## Governing Principle

Thresholds in this contract are set at the strategy-class level, not calibrated to any individual candidate. Raising a threshold to avoid triggering an incident for a specific candidate is a governance failure. If a candidate cannot meet the declared thresholds for its class, the correct response is to investigate the candidate, not to relax the policy.

## Strategy Classes

| Class | Description | Examples |
| --- | --- | --- |
| `intraday_scalp` | Short-hold, session-bounded, high signal frequency | London-open scalp, overlap resolution |
| `intraday_swing` | Intraday directional holds, lower frequency | session breakout continuation |
| `multi_session` | Holds across sessions, capped intraday | morning bias with late exit |

## Minimum Live Trade Counts

Before a live/demo run can be treated as evidence for a promotion decision, it must meet the minimum trade count for its strategy class. Counts below this floor mean the run is observation-only.

| Class | Minimum Trades (Observation) | Minimum Trades (Promotion-Eligible) |
| --- | --- | --- |
| `intraday_scalp` | 10 | 30 |
| `intraday_swing` | 5 | 20 |
| `multi_session` | 5 | 15 |

These floors are deliberately lower than research validation minimums (`validation.minimum_test_trade_count = 100`) because live data accumulates slowly. Observation-only evidence cannot support promotion but can support continued monitoring.

## Ordinary Variance Bands

These bands define what counts as normal adverse performance within a live run, distinguishing ordinary variance from an unexplained loss requiring an incident.

| Class | Max Consecutive Losses (No Incident) | Max Single-Run Drawdown % (No Incident) | Observation Window |
| --- | --- | --- | --- |
| `intraday_scalp` | 6 | 3.0% | rolling 20 trades |
| `intraday_swing` | 4 | 5.0% | rolling 15 trades |
| `multi_session` | 4 | 6.0% | rolling 10 trades |

Exceeding these bands triggers an incident of class `live_loss_ordinary_variance_exceeded`. This is NOT a parity failure — it is a performance monitoring trigger.

**Important:** An incident triggered by variance-band breach does not block live execution automatically. It requires operator review within the SLA defined in `incident-sla.md`. The incident closes if the run recovers within the same observation window or the operator concludes the deviation is consistent with known strategy behaviour in the current regime.

## Same-Window Incident Classification Thresholds

When a live-demo window is being compared against the MT5 replay baseline for the same window (strict executable parity check), the following apply:

| Metric | Threshold | Incident Class |
| --- | --- | --- |
| Missing trades (EA audit vs MT5) | > 0 | `parity_missing_trade` |
| Extra trades (MT5 vs EA audit) | > 0 | `parity_extra_trade` |
| Timing delta | > `parity_timestamp_tolerance_seconds` (default 90s) | `parity_timing_deviation` |
| Price delta | > `parity_price_tolerance_pips` (default 0.30 pips) | `parity_price_deviation` |
| Trade count rate | < `parity_min_match_rate` (default 80%) | `parity_match_rate_failure` |

Thresholds reference `config/eval_gates.toml` as the source of record. If `eval_gates.toml` is updated, this contract must be reviewed.

## Promotion-vs-Monitoring Boundary

A candidate is eligible for promotion when all of the following are satisfied simultaneously. If any condition is not met, the candidate must remain in monitoring.

| Condition | Threshold |
| --- | --- |
| Live trade count | ≥ promotion-eligible minimum for class |
| No open incidents | all incidents must be `closed` or `monitoring` with accepted rationale |
| MT5 parity status | `deployment_grade` |
| Broker reconciliation | `matched` or `mismatch` with accepted closure packet |
| Variance band | not currently in breach of ordinary-variance threshold |
| Deployment ladder | `observed_demo` or higher (see `deployment-ladder.md`) |

## Incident Closure Thresholds

An incident may be closed only when:
1. The root cause has been identified and documented in the closure packet.
2. The corrective action (if any) has been applied and verified.
3. For `parity_*` incidents: a verification replay has confirmed the fix.
4. For `live_loss_*` incidents: the operator has accepted that the loss is within strategy-class expectations for the current regime, with documented rationale.
5. All required evidence references declared in `incident-sla.md` for the incident's severity class are present.

## Overfitting Guard

These thresholds must not be used as targets during strategy development. Researchers must not tune strategies to produce results just above these floors. The floors represent minimum evidence of real-world viability, not design objectives.

If a strategy is consistently at the minimum thresholds after optimisation, treat it as a warning sign that the edge is fragile, not as a confirmation that it passes governance.
